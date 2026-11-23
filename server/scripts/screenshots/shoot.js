// Takes the public README's iPad screenshots from the demo in demo.json (made by make_demo.py; update.py puts them in place):
//   node server/scripts/screenshots/shoot.js OUT_DIR     (needs the built web app and the sandbox's Playwright)
// Each table moment gets its own throwaway server (serve.py) with the clock stopped at the demo's date.
const { chromium, devices } = require("playwright");
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const here = __dirname;
const out = path.resolve(process.argv[2] || "screenshots-new");
const demo = JSON.parse(fs.readFileSync(path.join(here, "demo.json"), "utf8"));
const python = process.env.PYTHON || "python3";
const device = { ...devices["iPad Pro 11"], reducedMotion: "reduce" }; // wide enough for dummy in suit columns
const user = demo.rows.find((r) => r.tbl === "users");
let port = 8780;

async function withServer(moment, fn) {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "bridge-shots-"));
  const p = port++;
  const server = spawn(python, [path.join(here, "serve.py"), path.join(here, "demo.json"), moment, String(p), data], {
    cwd: path.join(here, "..", ".."), stdio: ["ignore", "pipe", "inherit"] });
  const token = await new Promise((ok, fail) => {
    let buf = "";
    server.stdout.on("data", (d) => { buf += d; const m = buf.match(/TOKEN (\S+)/); if (m) ok(m[1]); });
    server.on("exit", (c) => fail(new Error(`demo server stopped (${c})`)));
  });
  const base = `http://127.0.0.1:${p}`;
  for (let i = 0; i < 100; i++) { // wait until it answers
    try { if ((await fetch(base + "/api/version")).ok) break; } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  try { await fn(base, token); } finally {
    const gone = new Promise((r) => server.once("exit", r));
    server.kill();
    await gone; // before its data goes
    fs.rmSync(data, { recursive: true, force: true });
  }
}

async function open(browser, base, token) {
  const ctx = await browser.newContext(device);
  await ctx.addInitScript(([token, u]) => {
    localStorage.setItem("bridge-bots-here", '"0"'); // the server plays the bots, as in the demo
    if (token) {
      localStorage.setItem("bridge-account", token);
      localStorage.setItem("bridge-user", JSON.stringify({ id: u.rk, name: u.data.name, friend_code: u.data.friend_code,
        notify: true, push: false, admin: false }));
    }
  }, [token, user]);
  const page = await ctx.newPage();
  await page.clock.setFixedTime(new Date(demo.now * 1000));
  await page.goto(base, { waitUntil: "load" });
  await page.waitForTimeout(3000);
  return page;
}

const click = (loc) => loc.first().evaluate((el) => el.click());

async function hint(page, wait) {
  await click(page.getByRole("button", { name: "Hint" }));
  await page.locator(".hinted").first().waitFor({ timeout: 30000 });
  if (wait) await page.getByText(wait).first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(1500);
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const shot = (page, name) => page.screenshot({ path: path.join(out, `${name}.png`) });

  await withServer("bid", async (base, token) => {
    const page = await open(browser, base, token);
    await page.getByText("Your call").first().waitFor({ timeout: 30000 });
    await hint(page);
    await shot(page, "bidding");
  });

  await withServer("play", async (base, token) => {
    const page = await open(browser, base, token);
    await page.getByText(/^(Your card|Play from)/).first().waitFor({ timeout: 30000 });
    await hint(page, /Makes|Beats/);
    await shot(page, "play");
  });

  await withServer("none", async (base, token) => {
    const page = await open(browser, base, token);
    await click(page.locator(".avatar"));
    await page.waitForTimeout(800);
    await click(page.getByRole("button", { name: "My stats" }));
    await page.getByText("Hand history").first().waitFor();
    await page.waitForTimeout(2500);
    await shot(page, "stats");
    await click(page.getByText(demo.review.board, { exact: true }));
    await page.waitForTimeout(2500);
    for (const t of demo.review.open) {
      await click(page.locator("summary", { hasText: t }));
      await page.waitForTimeout(600);
    }
    await shot(page, "review");

    const guest = await open(browser, base, null);
    await click(guest.getByRole("button", { name: "Play as a guest" }));
    await guest.waitForTimeout(1500);
    await click(guest.getByRole("button", { name: "Learn to play" }));
    await guest.waitForTimeout(1500);
    await click(guest.getByRole("button", { name: "None of these" }));
    await click(guest.getByRole("button", { name: "Start" }));
    await guest.waitForTimeout(1500);
    await click(guest.getByRole("button", { name: "See the steps" }));
    await guest.waitForTimeout(1500);
    await shot(guest, "learn");
  });

  await browser.close();
  console.log(`screenshots in ${out}`);
})().catch((e) => { console.error(e); process.exit(1); });
