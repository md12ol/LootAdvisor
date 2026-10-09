// Dev tool: drive a Chromium browser (Chrome / Edge) over the DevTools protocol to check the local Sets page.
//   node tools/sets_ship/cdp.js <browser exe> <file url> <out.png> [waitMs] [js-to-eval-after]
// Uses a throw-away profile (--user-data-dir in %TEMP%), headless, 1600x1000.
const { spawn } = require("child_process"), fs = require("fs"), os = require("os"), path = require("path");
const [exe, url, out, waitMs = "15000", evalJs = ""] = process.argv.slice(2);
const port = 9300 + Math.floor(Math.random() * 500);
const prof = fs.mkdtempSync(path.join(os.tmpdir(), "la-cdp-"));
const p = spawn(exe, ["--headless=new", "--remote-debugging-port=" + port, "--user-data-dir=" + prof, "--no-first-run",
  "--no-default-browser-check", "--window-size=1600,1000", "--allow-file-access-from-files", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  let tabs;
  for (let i = 0; i < 50; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; } catch (e) { await sleep(200); } }
  const tab = tabs.find((t) => t.type === "page");
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0; const pend = {}; const logs = [];
  ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; }
    if (d.method === "Runtime.consoleAPICalled") logs.push(d.params.type + ": " + d.params.args.map((a) => a.value || a.description).join(" "));
    if (d.method === "Runtime.exceptionThrown") logs.push("EXC: " + JSON.stringify(d.params.exceptionDetails).slice(0, 400)); });
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Runtime.enable"); await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  const t0 = Date.now();
  await send("Page.navigate", { url });
  let info = null;
  while (Date.now() - t0 < +waitMs) {
    const r = await send("Runtime.evaluate", { expression: "JSON.stringify(window.LA_SHIP_INFO||null)", returnByValue: true });
    info = r.result && r.result.result && r.result.result.value;
    if (info && info !== "null") break;
    await sleep(250);
  }
  console.log("boot", Date.now() - t0, "ms; info", info);
  if (evalJs) { const r = await send("Runtime.evaluate", { expression: evalJs, returnByValue: true, awaitPromise: true }); console.log("eval:", JSON.stringify(r.result && r.result.result && r.result.result.value)); }
  await sleep(1500);
  const shot = await send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(out, Buffer.from(shot.result.data, "base64"));
  console.log(logs.slice(0, 20).join("\n"));
  ws.close(); p.kill(); process.exit(0);
})();
