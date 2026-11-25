"""Serve this folder for the Pyodide page, with the headers mode A needs. Builds the nanopynq wheel into dist/ first.
Also serves the repository's sdk/js/ at /sdk/js/, where the page's ../../sdk/js/ resolves.

uv run python examples/pyodide/serve.py                # http://127.0.0.1:8000/  (mode A and B)
uv run python examples/pyodide/serve.py --coep none    # no cross-origin isolation: mode B only
"""

import argparse
import functools
import http.server
import posixpath
import subprocess
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
# credentialless: resources from other sites still load (without cookies), require-corp blocks those without CORP
COEPS = ("credentialless", "require-corp", "none")


def build_wheel() -> Path:
    dist = HERE / "dist"
    subprocess.run(["uv", "build", "--wheel", "--quiet", "--out-dir", str(dist), str(ROOT)], check=True)
    (wheel,) = dist.glob("nanopynq-*.whl")  # one version in the tree; a stale wheel of another version fails here
    return wheel


def handler(coep: str):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):
            # /sdk/js/... comes from the repository (normalised first, so /sdk/js/../ cannot leave it)
            clean = posixpath.normpath(urllib.parse.unquote(urllib.parse.urlsplit(path).path))
            base = self.directory
            if clean.startswith("/sdk/js/"):
                self.directory = str(ROOT)
            try:
                return super().translate_path(path)
            finally:
                self.directory = base

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
