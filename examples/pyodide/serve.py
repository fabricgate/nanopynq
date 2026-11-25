"""Serve this folder for the Pyodide page, with the headers mode A needs. Builds the nanopynq wheel into dist/ first.

uv run python examples/pyodide/serve.py                # http://127.0.0.1:8000/  (mode A and B)
uv run python examples/pyodide/serve.py --coep none    # no cross-origin isolation: mode B only
"""

import argparse
import functools
import http.server
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
# credentialless: resources from other sites still load (without cookies), require-corp blocks those without CORP
COEPS = ("credentialless", "require-corp", "none")


def build_wheel() -> Path:
    dist = HERE / "dist"
    subprocess.run(["uv", "build", "--wheel", "--quiet", "--out-dir", str(dist), str(HERE.parents[1])], check=True)
    (wheel,) = dist.glob("nanopynq-*.whl")  # one version in the tree; a stale wheel of another version fails here
    return wheel


def handler(coep: str):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            if coep != "none":  # both, or SharedArrayBuffer stays off (crossOriginIsolated is false)
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Cross-Origin-Embedder-Policy", coep)
            super().end_headers()

        def log_message(self, *args):
            pass

    return functools.partial(Handler, directory=str(HERE))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--coep", choices=COEPS, default=COEPS[0])
    args = ap.parse_args()
    print(f"built {build_wheel().name}")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler(args.coep))
    print(f"http://127.0.0.1:{args.port}/  (COEP {args.coep})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
