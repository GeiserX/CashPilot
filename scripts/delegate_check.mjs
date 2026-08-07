// What the delegated dispatcher actually HANDS a handler, measured by clicking.
//
// The dashboard's Restart, Stop and Logs buttons were built as
//
//     data-a1="'${slug}', ${workerId}"
//
// which is the leftover source text of onclick="viewLogs('slug', 123)". The
// dispatcher passes each data-aN as ONE string, so the handler was called with
// slug = "'anyone-protocol', 335094" and workerId = undefined. The server then
// answered "worker_id is required (multiple workers online)" -- and even with a
// single worker the slug would have 404'd, because it still had a quote in it.
//
// The expandable row was worse: data-a2="event" with no substitution anywhere,
// so toggleInstances got the literal string "event" and "event".target is
// undefined, throwing a TypeError instead of expanding.
//
// None of that is visible to a static check. The markup is well-formed, the
// handler exists, the action name is correct, and every existing test passes.
// Only clicking it shows what arrives.
//
//   ./scripts/delegate_check.sh
//
// Exits non-zero on a wrong argument list, and exits 2 with no browser --
// "skipped" must never read as "passed".

import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const DELEGATE = path.join(ROOT, "app", "static", "js", "delegate.js");
const PORT = process.env.CHROME_DEBUG_PORT || 9224;

// Mirrors how renderServicesBreakdown builds a row: slug in a1, worker id in a2
// when there is one, and the sentinel for a handler that needs the event.
const fixture = `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
  <table><tbody>
    <tr id="row" data-action="toggleInstances" data-a1="anyone-protocol" data-a2="$event">
      <td>
        <button id="logs"    data-action="viewLogs"       data-a1="anyone-protocol" data-a2="335094">Logs</button>
        <button id="restart" data-action="restartService" data-a1="anyone-protocol" data-a2="335094">Restart</button>
        <button id="stop"    data-action="stopService"    data-a1="anyone-protocol" data-a2="335094">Stop</button>
        <button id="solo"    data-action="viewLogs"       data-a1="honeygain">Logs (single worker)</button>
      </td>
    </tr>
  </tbody></table>
  <script>
    window.__calls = [];
    const record = (name) => (...args) => window.__calls.push({
      name,
      args: args.map((a) => (a && typeof a === "object" && "target" in a) ? "<EVENT:" + (a.target ? "has-target" : "NO-TARGET") + ">" : a),
      argc: args.length,
    });
    window.CP = {
      viewLogs: record("viewLogs"),
      restartService: record("restartService"),
      stopService: record("stopService"),
      toggleInstances: record("toggleInstances"),
    };
  </script>
  <script src="file://${DELEGATE}"></script>
</body></html>`;

const fixturePath = path.join(process.env.TMPDIR || "/tmp", "cashpilot-delegate.html");
fs.writeFileSync(fixturePath, fixture);

const version = await fetch(`http://127.0.0.1:${PORT}/json/version`).catch(() => null);
if (!version || !version.ok) {
  console.error(`FAIL  no headless Chrome on port ${PORT}.`);
  console.error("      This check needs a real browser: what a delegated handler");
  console.error("      RECEIVES cannot be read off the markup.");
  process.exit(2);
}

const target = await (
  await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent("file://" + fixturePath)}`, { method: "PUT" })
).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
const send = (method, params = {}) =>
  new Promise((r) => { pending.set(++id, r); ws.send(JSON.stringify({ id, method, params })); });
await new Promise((r) => ws.addEventListener("open", r));
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
});
await send("Runtime.enable");
await new Promise((r) => setTimeout(r, 400));

const clickAndRead = async (selector) => {
  const res = await send("Runtime.evaluate", {
    expression: `(() => {
      window.__calls = [];
      document.querySelector(${JSON.stringify(selector)}).click();
      return JSON.stringify(window.__calls);
    })()`,
    returnByValue: true,
  });
  return JSON.parse(res.result.value);
};

let failures = 0;
let checks = 0;
const check = (name, cond, detail = "") => {
  checks++;
  if (cond) return;
  failures++;
  console.error(`FAIL  ${name}${detail ? `\n      ${detail}` : ""}`);
};

// --------------------------------------------------------------------------
// THE BUG: two arguments must arrive as TWO arguments.
// --------------------------------------------------------------------------
for (const [sel, action] of [["#logs", "viewLogs"], ["#restart", "restartService"], ["#stop", "stopService"]]) {
  const calls = await clickAndRead(sel);
  const call = calls.find((c) => c.name === action);
  check(`${action} is called at all`, !!call, `got: ${JSON.stringify(calls)}`);
  if (!call) continue;
  check(
    `${action} receives the slug CLEANLY, not a quoted argument list`,
    call.args[0] === "anyone-protocol",
    `got slug: ${JSON.stringify(call.args[0])}`,
  );
  check(
    `${action} receives the worker id as a SECOND argument`,
    call.argc === 2 && call.args[1] === "335094",
    `got argc=${call.argc} args=${JSON.stringify(call.args)}`,
  );
}

// A row with a single worker and no id must pass exactly one argument -- not an
// empty string, which would send worker_id= and mean something different.
{
  const calls = await clickAndRead("#solo");
  const call = calls.find((c) => c.name === "viewLogs");
  check("a worker-less button passes ONE argument", call && call.argc === 1,
    `got: ${JSON.stringify(call)}`);
}

// --------------------------------------------------------------------------
// The $event sentinel: a handler that must inspect the click gets a real event.
// --------------------------------------------------------------------------
{
  const calls = await clickAndRead("#row");
  const call = calls.find((c) => c.name === "toggleInstances");
  check("the row handler fires", !!call, `got: ${JSON.stringify(calls)}`);
  if (call) {
    check("it receives a REAL event, not the string \"event\"",
      call.args[1] === "<EVENT:has-target>",
      `got: ${JSON.stringify(call.args[1])}`);
  }
}

// --------------------------------------------------------------------------
// One click runs ONE action. The dispatcher resolves event.target.closest(),
// so a button inside a row with its own data-action must not also fire the
// row's. This holds structurally rather than because of any attribute -- an
// earlier version of this file added data-stop="1" to "guarantee" it, and a
// mutation removing that attribute changed nothing, which is how the
// redundancy was found. Kept as a guard on the dispatcher's semantics.
// --------------------------------------------------------------------------
{
  const calls = await clickAndRead("#logs");
  check("one click runs exactly one action (closest wins)",
    !calls.some((c) => c.name === "toggleInstances"),
    `got: ${JSON.stringify(calls.map((c) => c.name))}`);
}

ws.close();
console.log(`${checks - failures}/${checks} delegate argument checks passed`);
if (failures) process.exit(1);
