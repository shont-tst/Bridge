// The app's offline engine: the server's own game (bridge/local.py), in Python built for the browser (Pyodide).
// Two of these run at an offline table: the game, and a helper that works out hints and review odds ahead of time,
// so the game never waits on them. They talk to each other directly over a MessageChannel the page gives them.
// The page (src/offline.ts) starts them, passes the phones' messages in and out, and keeps the table it's handed.
let py = null;
let host = null; // the game's LocalHost, once started
let queue = Promise.resolve(); // the game's messages, one at a time and in order
let helperPort = null;

const post = (m, transfer) => self.postMessage(m, transfer || []);

async function boot(version, pyodide) {
  importScripts(`/offline/pyodide/${pyodide}/pyodide.js`);
  py = await loadPyodide({ indexURL: `/offline/pyodide/${pyodide}/` });
  const res = await fetch(`/offline/engine.zip?v=${encodeURIComponent(version)}`);
  if (!res.ok) throw new Error(`the engine didn't download (${res.status})`);
  py.unpackArchive(await res.arrayBuffer(), "zip", { extractDir: "/engine" });
  py.runPython(`
import os, sys
os.environ["BRIDGE_SOLVER_IN_PROCESS"] = "1"   # no worker processes in a browser
os.environ["BRIDGE_DATA_DIR"] = "/tmp/bridge"
sys.path.insert(0, "/engine")
import bridge.local
`);
}

async function startGame(m) {
  py.globals.set("js_post", (conn, text) => post({ op: "post", conn, text }));
  py.globals.set("js_helper", helperPort ? (n, call) => {
    const bytes = call.toJs();
    call.destroy();
    helperPort.postMessage({ n, call: bytes }, [bytes.buffer]);
  } : null);
  py.globals.set("start_args", py.toPy({ snapshot: m.snapshot || null, settings: m.settings || {}, code: m.code || "HOME", practice: m.practice || null }));
  await py.runPythonAsync(`
import json
from bridge.local import LocalHost
_a = start_args
host = LocalHost(js_post, snapshot=json.loads(_a["snapshot"]) if _a["snapshot"] else None,
                 settings=dict(_a["settings"]), code=_a["code"], practice=_a["practice"],
                 helper=(lambda n, call: js_helper(n, __import__("pyodide.ffi").ffi.to_js(call))) if js_helper else None)
`);
  host = py.globals.get("host");
  if (helperPort) {
    helperPort.onmessage = (ev) => {
      const { n, answer } = ev.data;
      queue = queue.then(() => host.helper_done(n, answer)).catch(report);
    };
  }
}

function report(e) {
  post({ op: "fault", message: String((e && e.message) || e).slice(-800) });
}

// the helper: runs one job at a time, handed over by the game
function startHelper() {
  const run = py.globals.get("bridge").local.helper_run;
  helperPort.onmessage = (ev) => {
    const { n, call } = ev.data;
    let answer;
    try {
      const out = run(call);
      answer = out.toJs();
      out.destroy();
    } catch (e) {
      report(e);
      return;
    }
    helperPort.postMessage({ n, answer }, [answer.buffer]);
  };
}

self.onmessage = async (ev) => {
  const m = ev.data;
  try {
    if (m.op === "boot") {
      if (m.port) helperPort = m.port;
      const t0 = performance.now();
      await boot(m.version, m.pyodide);
      if (m.role === "helper") startHelper();
      post({ op: "booted", seconds: (performance.now() - t0) / 1000 });
    } else if (m.op === "start") {
      await startGame(m);
      post({ op: "started" });
    } else if (m.op === "msg") {
      queue = queue.then(() => host.receive(m.conn, m.text)).catch(report);
    } else if (m.op === "close") {
      queue = queue.then(() => host.close(m.conn)).catch(report);
    } else if (m.op === "snapshot") {
      queue = queue.then(() => post({ op: "snapshot", text: host.snapshot() })).catch(report);
    }
  } catch (e) {
    post({ op: "error", message: String((e && e.message) || e).slice(-800) });
  }
};
