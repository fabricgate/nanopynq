"""The Pyodide page (examples/pyodide) in the real Chrome, driven by Playwright, with a mock Web Serial port.

Mode A runs Pyodide in a Worker that waits on shared memory; mode B runs it in the page and waits with JSPI. Needs
Chrome, the network (Pyodide comes from the jsDelivr CDN) and Playwright, which is not a project dependency:

    uv run --with playwright==1.64.1 pytest -s tests/test_pyodide_page.py

Skipped without Playwright (CI). The measurements are printed (-s) for reports/report_pyodide_spike.md.
"""

import http.server
import importlib.metadata
import importlib.util
import json
import threading
import time

import pytest

from tests import jsrun
from tests.jsrun import ROOT

sync_api = pytest.importorskip("playwright.sync_api")

PAGE = ROOT / "examples" / "pyodide"
MOCK = ROOT / "tests" / "js" / "mock_serial.js"
OPEN = 'ol = Overlay("base", board="tangnano9k")\n'
MODES = {"a": "credentialless", "b": "none"}  # mode -> the COEP header it is served with ("none": no isolation)
LOAD_MS = 180_000

_spec = importlib.util.spec_from_file_location("serve", PAGE / "serve.py")
serve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve)


def report(name: str, value) -> None:
    print(f"\nMEASURE {name} {json.dumps(value)}")


@pytest.fixture(scope="module")
def server():
    wheel = serve.build_wheel()
    assert f'"dist/{wheel.name}"' in (PAGE / "pyload.mjs").read_text(encoding="utf-8"), "pyload.mjs names another wheel"
    servers = {}

    def start(coep: str) -> str:
        if coep not in servers:
            servers[coep] = http.server.ThreadingHTTPServer(("127.0.0.1", 0), serve.handler(coep))
            threading.Thread(target=servers[coep].serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{servers[coep].server_port}/"

    yield start
    for s in servers.values():
        s.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=jsrun.chrome())
        report("browser", {"version": b.version, "playwright": importlib.metadata.version("playwright")})
        yield b
        b.close()


@pytest.fixture(scope="module")
def context(browser):
    """One HTTP cache for the module: Pyodide comes from the CDN once."""
    c = browser.new_context()
    c.add_init_script(path=MOCK)
    yield c
    c.close()


def load(context, url: str):
    page = context.new_page()
    page.goto(url)
    page.wait_for_function("document.body.dataset.state !== 'loading'", timeout=LOAD_MS)
    return page


def ready_page(context, server, mode: str):
    page = load(context, server(MODES[mode]) + f"index.html?mode={mode}")
    assert page.evaluate("document.body.dataset.state") == "ready", page.text_content("#out")
    page.click("#port")
    return page


def start(page, code: str) -> None:
    page.fill("#code", code)
    page.click("#run")


def finish(page, timeout: int = 30_000) -> str:
    page.wait_for_function("document.body.dataset.state === 'ready'", timeout=timeout)
    return page.text_content("#out")


def run(page, code: str, timeout: int = 30_000) -> str:
    start(page, code)
    return finish(page, timeout)


def stopped(out: str) -> bool:
    """The cell ended with KeyboardInterrupt itself, not with an error that only has it as its cause."""
    return out.strip().splitlines()[-1] == "KeyboardInterrupt"


def test_what_chrome_has_and_the_mock_copies(context, server):
    page = load(context, server("none") + "index.html?mode=b")
    assert page.evaluate("__mock.real") == {"serial": True, "missing": []}  # the mock has only what SerialPort has
    in_worker = page.evaluate("""() => new Promise((resolve) => {
      const src = "navigator.serial.getPorts().then((p) => postMessage(Array.isArray(p)), (e) => postMessage(String(e)))";
      new Worker(URL.createObjectURL(new Blob([src]))).onmessage = (e) => resolve(e.data);
    })""")
    assert in_worker is True  # Web Serial exists in a Worker too (getPorts only: choosing a port needs the page)
    assert page.evaluate("typeof WebAssembly.Suspending") == "function"  # JSPI, which mode B needs


@pytest.mark.parametrize("mode", "ab")
def test_a_cell_drives_the_board(context, server, mode):
    page = ready_page(context, server, mode)
    assert page.evaluate("crossOriginIsolated") == (mode == "a")  # B needs no headers
    out = run(
        page,
        OPEN + "ol.leds[0].on()\n"
        "print('buttons', ol.buttons[0].read(), ol.buttons[1].read())\n"
        "import time\n"
        "for _ in range(4):\n"
        "    ol.leds[1].toggle()\n"
        "    time.sleep(0.05)\n"
        "ol.close()\n",
    )
    assert "buttons 1 0" in out
    assert page.evaluate("__mock.writes.filter(([a]) => a === 0x1000).map(([, v]) => v)") == [1, 3, 1, 3, 1]
    assert page.evaluate("__mock.opens") == [115200]


@pytest.mark.parametrize("mode", "ab")
def test_stop_ends_a_loop_that_talks_to_the_board(context, server, mode):
    """Ten times: a Stop that only sometimes arrives, or arrives as another error, fails here."""
    page = ready_page(context, server, mode)
    run(page, OPEN)
    times = []
    for _ in range(10):
        writes = page.evaluate("__mock.writes.length")
        start(page, "while True:\n    ol.leds[0].toggle()\n")
        page.wait_for_function(f"__mock.writes.length > {writes + 50}", timeout=30_000)
        t = time.perf_counter()
        page.click("#stop")
        out = finish(page)
        times.append(round((time.perf_counter() - t) * 1e3))
        assert stopped(out), out
    report(f"stop_io_{mode}", {"ms": times})
    out = run(page, "ol.leds[0].on()\nprint('again', ol.leds[0].read())\n")  # the port still works
    assert "again 1" in out
    # a stopped cell leaves ol open: running the cell again (Overlay first) takes the port over
    out = run(page, OPEN + "print('reopened', ol.leds[0].read())\nol.close()\n")
    assert "reopened 1" in out
    assert page.evaluate("__mock.opens") == [115200, 115200]


GAP = """window.__gap = 0; { let last = performance.now();
  setInterval(() => { const n = performance.now(); __gap = Math.max(__gap, n - last); last = n; }, 10); }"""


@pytest.mark.parametrize("mode", "ab")
def test_a_loop_without_io_and_the_page(context, server, mode):
    """A keeps the page live and can stop pure Python; in B the page freezes until the loop ends."""
    page = ready_page(context, server, mode)
    page.evaluate(GAP)
    start(page, "import time\nt = time.time()\nwhile time.time() - t < 1.5:\n    pass\nprint('done')\n")
    if mode == "a":
        page.wait_for_timeout(300)
        page.click("#stop")
    out = finish(page)
    gap = page.evaluate("__gap")
    report(f"busy_loop_{mode}", {"max_timer_gap_ms": round(gap), "out": out.strip()[-60:]})
    if mode == "a":
        assert stopped(out) and "done" not in out
        assert gap < 200
    else:
        assert "done" in out
        assert gap > 1000


@pytest.mark.parametrize("mode", "ab")
def test_time_sleep_keeps_the_page_live_and_stops(context, server, mode):
    """A blinking loop spends its time in time.sleep (page.py's): the page runs meanwhile in B too, and Stop ends it."""
    page = ready_page(context, server, mode)
    page.evaluate(GAP)
    times = []
    for _ in range(5):
        start(page, "import time\nwhile True:\n    time.sleep(0.1)\n")
        page.wait_for_timeout(500)
        t = time.perf_counter()
        page.click("#stop")
        out = finish(page)
        times.append(round((time.perf_counter() - t) * 1e3))
        assert stopped(out), out
    gap = page.evaluate("__gap")
    report(f"sleep_loop_{mode}", {"stop_ms": times, "max_timer_gap_ms": round(gap)})
    assert gap < 200


@pytest.mark.parametrize("mode", "ab")
def test_a_board_that_does_not_answer(context, server, mode):
    page = ready_page(context, server, mode)
    page.evaluate("__mock.silent = true")
    assert "BoardNotResponding" in run(page, OPEN)
    assert page.evaluate("__mock.port.readable === null")  # Overlay closed the port
    page.evaluate("__mock.silent = false")
    assert "open" in run(page, OPEN + "print('open')\nol.close()\n")


@pytest.mark.parametrize("mode", "ab")
def test_stop_while_waiting_for_a_board_that_does_not_answer(context, server, mode):
    """The wrong port, or a board not programmed: Overlay retries for about 4 s; Stop must not wait for that.

    It waits for the read under way to time out (1 s): A stops Python at once, but Overlay's close() then queues
    behind that read in the page; B looks at Stop when the next transaction starts."""
    page = ready_page(context, server, mode)
    page.evaluate("__mock.silent = true")
    start(page, OPEN)
    page.wait_for_timeout(500)
    t = time.perf_counter()
    page.click("#stop")
    out = finish(page)
    ms = round((time.perf_counter() - t) * 1e3)
    report(f"stop_silent_{mode}", {"ms": ms, "last": out.strip().splitlines()[-1]})
    assert stopped(out), out
    assert ms < 2500


@pytest.mark.parametrize("mode", "ab")
def test_round_trip_overhead(context, server, mode):
    """Python's register read against the same mock and link as JavaScript alone: the difference is the overhead."""
    page = ready_page(context, server, mode)
    page.evaluate("__mock.delayMs = 0")
    out = run(
        page,
        OPEN + "import time\nn = 300\nt = time.perf_counter()\n"
        "for _ in range(n):\n    ol.sys.read(0x8)\n"
        "print('rtt_ms', (time.perf_counter() - t) / n * 1e3)\nol.close()\n",
    )
    python_ms = float(out.split("rtt_ms")[1].split()[0])
    js_ms = page.evaluate("""async () => {
      const link = spike.link, frame = Uint8Array.of(0x02, 1, 0, 0, 0, 2), n = 300;
      await link.open(115200);
      const t = performance.now();
      for (let i = 0; i < n; i++) { link.resetInput(); await link.write(frame); await link.read(4, 1000); }
      const ms = (performance.now() - t) / n;
      await link.close();
      return ms;
    }""")
    report(f"rtt_{mode}", {"python_ms": round(python_ms, 3), "js_only_ms": round(js_ms, 3)})
    assert python_ms > 0 and js_ms > 0


@pytest.mark.parametrize("mode", "ab")
def test_load_size_and_time(browser, server, mode):
    """Cold: a new context, so nothing is cached. Warm: the same page loaded again."""
    c = browser.new_context()
    c.add_init_script(path=MOCK)
    try:
        for when in ("cold", "warm"):
            page = load(c, server(MODES[mode]) + f"index.html?mode={mode}")
            spike = page.evaluate("spike.load")
            assert page.evaluate("document.body.dataset.state") == "ready"
            files = {
                r["name"].rsplit("/", 1)[-1]: [r["transferSize"], r["encodedBodySize"], r["decodedBodySize"]]
                for r in spike["resources"]
            }
            assert any(n.startswith("nanopynq-") for n in files)
            report(
                f"load_{mode}_{when}",
                {
                    "ms": {k: round(v) for k, v in spike["ms"].items()},
                    "total_ms": round(spike["total"]),
                    "transfer": sum(v[0] for v in files.values()),
                    "encoded": sum(v[1] for v in files.values()),
                    "decoded": sum(v[2] for v in files.values()),
                    "files": files,
                },
            )
            page.close()
    finally:
        c.close()


def test_mode_a_needs_cross_origin_isolation(context, server):
    page = load(context, server("none") + "index.html?mode=a")
    assert page.evaluate("document.body.dataset.state") == "error"
    assert "crossOriginIsolated" in page.text_content("#out")


def test_what_the_headers_do_to_resources_from_other_sites(context, server):
    """img, script and fetch(no-cors) go through the same check; the other site here sends no CORP header."""
    other = server("none") + "page.py"
    seen = {}
    for coep in ("none", "require-corp", "credentialless"):
        page = context.new_page()
        page.goto(server(coep) + "no-such-page")  # the 404 page carries the headers too
        seen[coep] = page.evaluate(
            """async (url) => ({
          isolated: crossOriginIsolated,
          noCors: await fetch(url, { mode: "no-cors" }).then(() => "loaded", (e) => "blocked"),
        })""",
            other,
        )
        page.close()
    report("headers", seen)
    assert seen == {
        "none": {"isolated": False, "noCors": "loaded"},
        "require-corp": {"isolated": True, "noCors": "blocked"},
        "credentialless": {"isolated": True, "noCors": "loaded"},
    }


def test_what_does_not_work_and_why(context, server):
    """The error the report quotes for installing with the dependencies."""
    page = ready_page(context, server, "b")
    out = run(
        page,
        "import js, micropip\n"
        "try:\n"
        "    await micropip.install(js.location.href.split('index.html')[0] + js.spike.wheel)\n"
        "except Exception as e:\n"
        "    print('micropip:', type(e).__name__, e)\n",
        timeout=120_000,
    )
    report("errors", out)
    assert "micropip:" in out and "libusb" in out


def test_a_npq_opens_without_its_fs(context, server):
    """The page's Overlay (download=False) opens a .npq alone: no .fs is read (V12 skipped, sha256 None), and
    opening still checks the board's sys.design_id against the .npq."""
    page = ready_page(context, server, "b")
    out = run(
        page,
        "import os, shutil\n"
        "from nanopynq.resolve import resolve_design\n"
        "os.makedirs('/tmp/npq', exist_ok=True)\n"
        "shutil.copy(resolve_design('base', 'tangnano9k') / 'base.npq', '/tmp/npq/base.npq')\n"
        "ol = Overlay('/tmp/npq/base.npq')\n"
        "print('npq-only:', ol.manifest.sha256, hex(ol.manifest.design_id))\n",
    )
    assert "npq-only: None 0xabf78d8c" in out, out
    page.evaluate("__mock.regs.set(0xc, 0x12345678)")  # another design on the board
    out = run(
        page,
        "try:\n    Overlay('/tmp/npq/base.npq')\nexcept Exception as e:\n    print('mismatch:', type(e).__name__)\n",
    )
    assert "mismatch: DesignMismatch" in out, out
