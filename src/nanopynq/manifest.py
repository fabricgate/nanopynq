"""manifest.yaml loader: validates the bitstream and normalises `ips` to the DefaultIP description shape."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from nanopynq.errors import ManifestError

DEFAULT_ADDR_RANGE = 0x1000  # R9: used when an ip has no addr_range


@dataclass(frozen=True)
class Manifest:
    board: str
    bitstream: Path
    sha256: str | None  # None when load_npq(check_bitstream=False) skipped the .fs
    ips: dict[str, dict]


def _int(v) -> int:
    return int(v, 0) if isinstance(v, str) else int(v)


def _streams(name: str, raw) -> dict:
    """ips.<ip>.streams.<name>: {dir: read|write, mtu: bytes > 0, ...}; other keys are kept as they are."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"ip {name!r}: streams must be a mapping")
    for s, v in raw.items():
        mtu = v.get("mtu") if isinstance(v, dict) else None
        if not isinstance(v, dict) or v.get("dir") not in ("read", "write") or type(mtu) is not int or mtu <= 0:
            raise ValueError(f"ip {name!r}: stream {s!r} needs dir (read or write) and mtu (bytes, > 0)")
    return {s: dict(v) for s, v in raw.items()}


def _ip(name: str, ip: dict) -> dict:
    return {
        "name": name,
        "type": ip["type"],
        "phys_addr": _int(ip["base"]),
        "addr_range": _int(ip.get("addr_range", DEFAULT_ADDR_RANGE)),
        "parameters": dict(ip.get("parameters") or {}),
        "registers": {
            r: {"offset": _int(v["offset"]), "width": int(v["width"]), "access": v["access"]}
            for r, v in (ip.get("registers") or {}).items()
        },
        "streams": _streams(name, ip.get("streams")),
    }


def load_manifest(design_dir: Path) -> Manifest:
    design_dir = Path(design_dir)
    path = design_dir / "manifest.yaml"
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw["runtime"] != "nanopynq":
            raise ManifestError(f"{path}: runtime is {raw['runtime']!r}, expected 'nanopynq'")
        art = raw["artifacts"]["bitstream"]
        bitstream = (design_dir / art["file"]).resolve()
        sha = str(art["sha256"]).lower()
        ips = {name: _ip(name, ip) for name, ip in (raw.get("ips") or {}).items()}
        board = raw["board"]
    except ManifestError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError) as e:
        raise ManifestError(f"{path}: malformed manifest ({type(e).__name__}: {e})") from e
    if not bitstream.is_relative_to(design_dir.resolve()):
        raise ManifestError(f"{path}: bitstream path escapes the design directory: {art['file']}")
    if not bitstream.is_file():
        raise ManifestError(f"bitstream not found: {bitstream}")
    actual = hashlib.sha256(bitstream.read_bytes()).hexdigest()
    if actual != sha:
        raise ManifestError(f"sha256 mismatch for {bitstream.name}: manifest {sha}, actual {actual}")
    return Manifest(board=board, bitstream=bitstream, sha256=sha, ips=ips)
