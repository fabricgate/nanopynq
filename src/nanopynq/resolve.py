import os
import re
import shutil
import tempfile
import warnings
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from nanopynq.npq import BOARD

_DESIGNS = Path(str(files("nanopynq").joinpath("data/designs")))
# FabricGate's namespace and design names follow the same rule as board names; the version is X.Y.Z
FABRICGATE_REF = re.compile(
    rf"fabricgate://(?P<ref>(?P<ns>{BOARD.pattern})/(?P<design>{BOARD.pattern})"
    r":(?P<version>(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)))"
)
# what the registry said about a pulled version (yanked, deprecated), saved next to it in the cache
WARNINGS = ".nanopynq-warnings"


def bundled_boards(name: str) -> list[str]:
    """Boards that ship a bundled design called `name` (folder data/designs/<board>-<name>)."""
    return sorted(p.name[: -len(name) - 1] for p in _DESIGNS.glob(f"*-{name}") if p.is_dir())


def resolve_design(design: str | Path, board: str | None) -> Path:
    if str(design).startswith("fabricgate://"):
        return _pull_fabricgate(str(design), board)
    name = str(design)
    if board is not None and "/" not in name and "\\" not in name and (_DESIGNS / f"{board}-{name}").is_dir():
        return _DESIGNS / f"{board}-{name}"
    return Path(design)


def _pull_fabricgate(design: str, board: str | None) -> Path:
    """The folder of `fabricgate://<namespace>/<design>:<version>` for `board`, pulled with the FabricGate SDK into
    <cache>/nanopynq/fabricgate/<registry>/<namespace>/<design>/<version>/<board> the first time and reused after
    that."""
    m = FABRICGATE_REF.fullmatch(design)
    if m is None:
        raise ValueError(
            f"{design!r}: expected fabricgate://<namespace>/<design>:<version>, "
            "e.g. fabricgate://fabricgate/tangnano9k-base:1.0.0"
        )
    if board is None or not BOARD.fullmatch(board):
        raise ValueError(
            f"board is required for design {design!r} (it picks the platform <board>/nanopynq), got {board!r}"
        )
    try:
        from fabricgate.client.config import load_config  # the registry the fabricgate CLI uses: FG_REGISTRY, config
        from fabricgate.sdk import pull
    except ImportError as e:
        if e.name != "fabricgate":  # installed but changed or broken: its own error says what is wrong
            raise
        raise ImportError(f'{design} needs the FabricGate SDK: pip install "nanopynq[fabricgate]"') from e
    registry = load_config().registry
    u = urlsplit(registry)  # the folder name keeps host, port and path apart but leaves out user:password@
    where = re.sub(r"[^a-z0-9.-]+", "_", (u.netloc.rpartition("@")[2] + u.path).lower()).strip("._") or "registry"
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")  # here, so import never needs a home
    dest = cache / "nanopynq" / "fabricgate" / where / m["ns"] / m["design"] / m["version"] / board
    if not dest.is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{board}-", dir=dest.parent))  # a cut-off pull never becomes dest
        try:
            r = pull(m["ref"], platform=f"{board}/nanopynq", output=tmp, registry=registry)
            said = [
                w
                for w in (r.yanked_warning, r.deprecated_warning, r.shell_yanked_warning, *r.dependency_yanked_warnings)
                if w
            ]
            # kept with the design, as later calls never ask the registry again. Written even when empty, so a file
            # of that name pulled from the publisher is replaced. The registry's text is the publisher's too: no
            # escape sequences or line breaks reach the terminal
            (tmp / WARNINGS).write_text(
                "".join("".join(c if c.isprintable() else "?" for c in w) + "\n" for w in said), encoding="utf-8"
            )
            try:
                tmp.rename(dest)
            except OSError:
                if not dest.is_dir():  # otherwise another process finished the same pull first
                    raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    # shortcut: a version yanked after its first pull is not seen; ask the registry on each open if that matters
    if (dest / WARNINGS).is_file():
        for line in (dest / WARNINGS).read_text(encoding="utf-8").splitlines():
            warnings.warn(f"FabricGate: {line}", stacklevel=4)  # points at the Overlay(...) call
    return dest
