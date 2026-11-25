"""examples/pyodide/serve.py maps URLs to files: the page's folder, plus the repository's sdk/js/ at /sdk/js/ (where the
page's ../../sdk/js/ resolves), and nothing else outside the folder."""

import importlib.util

import pytest

from tests.jsrun import ROOT

PAGE = ROOT / "examples" / "pyodide"
_spec = importlib.util.spec_from_file_location("serve", PAGE / "serve.py")
serve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve)


def _handler():
    """A request handler as the server makes one, without a socket: translate_path needs only the directory."""
    factory = serve.handler("none")
    h = factory.func.__new__(factory.func)
    h.directory = factory.keywords["directory"]
    return h


@pytest.mark.parametrize(
    ("url", "path"),
    [
        ("/index.html", PAGE / "index.html"),
        ("/link.mjs?v=1", PAGE / "link.mjs"),
        ("/sdk/js/transport/webserial.js", ROOT / "sdk" / "js" / "transport" / "webserial.js"),
        # out of sdk/js: back in the page's folder, where these do not exist
        ("/sdk/js/../../pyproject.toml", PAGE / "pyproject.toml"),
        ("/sdk/js/%2e%2e/%2e%2e/pyproject.toml", PAGE / "pyproject.toml"),
        ("/sdk/README.md", PAGE / "sdk" / "README.md"),
    ],
)
def test_urls_map_to_the_page_folder_and_sdk_js(url, path):
    h = _handler()
    assert h.translate_path(url) == str(path)
    assert h.directory == str(PAGE)  # an /sdk/js/ request does not change where the next one looks
