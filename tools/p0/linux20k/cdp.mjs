// Drive a page in a fresh Chrome profile (on DISPLAY :20) over CDP. Usage: node cdp.mjs <url> '<json steps>'
// steps: ["click", id] | ["file", id, path] | ["wait", ms] | ["until", "a|b", ms] | ["log"] | ["eval", js]
// e.g. node cdp.mjs file://$PWD/examples/webusb/index.html \
//   '[["click","connect"],["until","opened|error",150000],["file","fs","/abs/base.fs"],["click","load"],
//     ["until","loaded|error: ",60000],["click","bridge"],["until","round trip|error: ",30000],["log"]]'
// Chrome 157 did not raise the WebUSB chooser in the DeviceAccess domain: pick the device on the screen,
// e.g. with x.py (shot, then click the device and the connect button).
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const [url, stepsJson] = process.argv.slice(2);
const prof = mkdtempSync(join(tmpdir(), "chrome-"));
const chrome = spawn("google-chrome", [`--user-data-dir=${prof}`, "--remote-debugging-port=0", "--no-first-run",
  "--no-default-browser-check", "--disable-sync", url], { env: { ...process.env, DISPLAY: ":20" }, stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const portFile = join(prof, "DevToolsActivePort");
for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100);
const port = readFileSync(portFile, "utf8").split("\n")[0];
await sleep(1000);
const page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let seq = 0;
const pending = new Map();
ws.addEventListener("message", async (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === "DeviceAccess.deviceRequestPrompted") {
    const { id, devices } = m.params;
    console.log("prompt:", JSON.stringify(devices));
    if (devices.length) console.log("select:", JSON.stringify(await send("DeviceAccess.selectPrompt", { id, deviceId: devices[0].id })));
  } else if (m.method === "Runtime.consoleAPICalled") {
    console.log("console:", m.params.args.map((a) => a.value ?? a.description).join(" "));
  } else if (m.method === "Runtime.exceptionThrown") {
    console.log("exception:", m.params.exceptionDetails.exception?.description);
  }
});
const send = (method, params = {}) => new Promise((r) => { const id = ++seq; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const evalJs = async (expression) => (await send("Runtime.evaluate", { expression, userGesture: true, awaitPromise: true, returnByValue: true })).result;
console.log("DeviceAccess.enable:", JSON.stringify(await send("DeviceAccess.enable")));
await send("Runtime.enable");
for (const [op, a, b] of JSON.parse(stepsJson)) {
  if (op === "click") await evalJs(`document.getElementById(${JSON.stringify(a)}).click()`);
  else if (op === "wait") await sleep(a);
  else if (op === "until") {  // until the page log contains a, or b ms pass
    for (let t = 0; t < b; t += 250) {
      const text = (await evalJs("document.getElementById('log').textContent")).result.value;
      if (a.split("|").some((s) => text.includes(s))) break;
      await sleep(250);
    }
  }
  else if (op === "log") console.log("---- page log ----\n" + (await evalJs("document.getElementById('log').textContent")).result.value);
  else if (op === "eval") console.log("eval:", JSON.stringify((await evalJs(a)).result));
  else if (op === "file") {
    const obj = (await send("Runtime.evaluate", { expression: `document.getElementById(${JSON.stringify(a)})` })).result.result;
    console.log("setFile:", JSON.stringify(await send("DOM.setFileInputFiles", { files: [b], objectId: obj.objectId })));
    await evalJs(`document.getElementById(${JSON.stringify(a)}).dispatchEvent(new Event("change"))`);
  }
}
ws.close();
chrome.kill();
await sleep(500);
process.exit(0);
