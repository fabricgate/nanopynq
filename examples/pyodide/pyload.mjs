// Loads Pyodide and nanopynq, for the page (mode B) and for the worker (mode A).
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.mjs";

export const WHEEL = "dist/nanopynq-0.1.0-py3-none-any.whl"; // serve.py builds it; the test checks the name

// `prelude` sets up the namespace the cells run in, after `names` (JavaScript objects page.py uses) are put there.
export async function loadNanopynq(print, prelude, names) {
  const ms = {};
  let t = performance.now();
  const lap = (k) => { const now = performance.now(); ms[k] = now - t; t = now; };
  const py = await loadPyodide({ stdout: print, stderr: print });
  lap("pyodide");
  // The wheel without its dependencies: pyyaml comes from Pyodide; pyserial, pyusb and libusb-package are left out
  // (libusb-package has no wheel for the browser, and none of them can reach a port here).
  await py.loadPackage(["pyyaml", new URL(WHEEL, import.meta.url).href], { messageCallback: () => {} });
  lap("packages");
  const page = await fetch(new URL("page.py", import.meta.url));
  py.FS.writeFile("/home/pyodide/page.py", await page.text()); // the working directory, on sys.path
  const ns = py.globals.get("dict")();
  for (const [k, v] of Object.entries(names)) ns.set(k, v);
  py.runPython("import time, pyodide_js\nfrom page import overlay_factory, stop_check, stoppable_sleep\n" + prelude, { globals: ns });
  lap("nanopynq");
  const resources = performance.getEntriesByType("resource").map(
    ({ name, transferSize, encodedBodySize, decodedBodySize }) => ({ name, transferSize, encodedBodySize, decodedBodySize }));
  return { py, ns, load: { ms, resources } };
}
