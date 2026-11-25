// Runs examples/webserial/npq.js on the cases of tests/data/npq_vectors.json, in Node (require) and in a browser
// (a classic script after npq.js). Resolves to {"<name>": {"design_id": "0x..."} | {"rule": "Vn"} | {"crash": "..."}}.
"use strict";

async function runNpqVectors(reader, vectors) {
  // the file contents: "text" as UTF-8 or "base64", then spaces up to "pad_to" bytes
  const contents = (c) => {
    const b = c.base64 !== undefined ? Uint8Array.from(atob(c.base64), (ch) => ch.charCodeAt(0)) : new TextEncoder().encode(c.text);
    if (!c.pad_to) return b;
    const padded = new Uint8Array(c.pad_to).fill(0x20);
    padded.set(b);
    return padded;
  };
  const out = {};
  for (const c of vectors.cases) {
    try {
      const doc = await reader.readNpq(contents(c));
      out[c.name] = { design_id: reader.hex8(await reader.designId(doc.ips)) }; // computed, not the field echoed back
    } catch (e) {
      out[c.name] = e instanceof reader.NpqError ? { rule: e.rule } : { crash: `${e.name}: ${e.message}` };
    }
  }
  return out;
}

if (typeof module !== "undefined") module.exports = { runNpqVectors };
