import argparse
import sys
from pathlib import Path

from nanopynq.boards import list_boards
from nanopynq.doctor import default_checks, run_checks
from nanopynq.errors import BuildError, ManifestError


def _key_lines(log: str, n: int = 15) -> str:
    errors = [line for line in log.splitlines() if "ERROR" in line or "Error" in line]
    return "\n".join(errors[:n] or log.splitlines()[-n:])


def build(folder: Path, check: bool = True) -> int:
    from nanopynq.build.design import CONFIG, CollectError, ConfigError, CrosscheckFailed, ToolsMissing, build_design

    where = folder / CONFIG
    try:
        dist = build_design(folder, check=check)
    except ToolsMissing as e:
        print(e, file=sys.stderr)
        return 2
    except CrosscheckFailed as e:
        res = e.result
        lines = [f"{where}: the ips do not match the RTL; nothing was built"]
        lines += [f"  error: {p.message}" for p in res.errors] + [f"  warning: {p.message}" for p in res.warnings]
        if any(p.kind == "cannot_check" for p in res.errors):
            lines.append(
                "The top must follow the rules in README (Building your own gateware); "
                "nanopynq build --no-crosscheck builds without the check."
            )
        else:
            lines.append(f"Fix the ips in {CONFIG} or the RTL so that they agree.")
        lines.append(f"The check's files: {folder / 'build' / 'crosscheck'}")
        print("\n".join(lines), file=sys.stderr)
        return 1
    except (ConfigError, CollectError) as e:
        print(f"{where}: {e}", file=sys.stderr)
        return 1
    except ManifestError as e:  # NpqError: rule and place of spec 5.9, the place being the key under [ips]
        print(
            f"{where}: {e}\n(the rules for ips are in spec 5.9 of nanopynq's docs/spec_design_metadata.md)",
            file=sys.stderr,
        )
        return 1
    except BuildError as e:
        log = folder / "build" / f"{e.step}.log"
        log.write_text(e.log, encoding="utf-8")
        print(f"{e}\n{_key_lines(e.log)}\nthe whole output of the tool: {log}", file=sys.stderr)
        return 1
    npq = next(dist.glob("*.npq"))
    print(f"{dist}\n  {npq.stem}.fs, {npq.name}, build.json\n  use it with Overlay({str(dist)!r})")
    return 0


def main(argv: list[str] | None = None, checks: dict | None = None) -> int:
    p = argparse.ArgumentParser(prog="nanopynq")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="check the setup for programming and talking to a board")
    d.add_argument("--board", default="tangnano9k", choices=list_boards())
    b = sub.add_parser("build", help="build the design in a folder with nanopynq.toml into its dist/ folder")
    b.add_argument("folder", nargs="?", default=".", type=Path)
    b.add_argument("--no-crosscheck", action="store_true", help="do not check the ips against the RTL before synthesis")
    args = p.parse_args(argv)
    if args.cmd == "build":
        return build(args.folder, check=not args.no_crosscheck)
    return run_checks(checks if checks is not None else default_checks(args.board))


if __name__ == "__main__":
    sys.exit(main())
