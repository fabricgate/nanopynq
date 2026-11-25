// Mode A: Pyodide in this Worker. A port call posts the request to the page, which owns the Web Serial port, and
// blocks on shared memory until the page answers. ctl: [0] the number of the last answered call, [1] 1 if it failed,
// [2] the length of its bytes in `data` (the answer, or the error message).
import { loadNanopynq } from "./pyload.mjs";

let ctl, data, py, ns, calls = 0;

function call(op, ...args) {
  const mine = ++calls;
  postMessage({ type: "io", seq: mine, op, args });
  for (let seen; (seen = Atomics.load(ctl, 0)) !== mine;) {
    // a Stop is seen while waiting too; the answer to an abandoned call comes later and is skipped by its number
    if (Atomics.wait(ctl, 0, seen, 50) === "timed-out") py.checkInterrupt();
  }
  const out = data.slice(0, ctl[2]); // a copy: TextDecoder does not take shared memory
  if (ctl[1]) throw new Error(new TextDecoder().decode(out));
  return out;
}

const link = {
  open: (baudRate) => { call("open", baudRate); },
  close: () => { call("close"); },
  resetInput: () => { call("resetInput"); },
  write: (bytes) => { call("write", Uint8Array.from(bytes)); },
  read: (n, timeoutMs) => call("read", n, timeoutMs),
};

const print = (text) => postMessage({ type: "out", text });

onmessage = async ({ data: m }) => {
  if (m.type === "init") {
    ctl = new Int32Array(m.sab, 0, 4);
    data = new Uint8Array(m.sab, 16);
    try {
      const napCell = new Int32Array(new SharedArrayBuffer(4)); // nobody wakes it: Atomics.wait only times out
      const nap = (ms) => { Atomics.wait(napCell, 0, 0, ms); };
      const r = await loadNanopynq(print, "time.sleep = stoppable_sleep(nap, pyodide_js.checkInterrupt)\n" +
                                          "Overlay = overlay_factory(link)", { link, nap });
      ({ py, ns } = r);
      py.setInterruptBuffer(new Uint8Array(m.interrupt));
      postMessage({ type: "ready", load: r.load });
    } catch (e) {
      postMessage({ type: "error", text: e.message });
    }
  } else if (m.type === "run") {
    try {
      await py.loadPackagesFromImports(m.code);
      await py.runPythonAsync(m.code, { globals: ns });
    } catch (e) {
      print(e.message);
    }
    postMessage({ type: "done" });
  }
};
