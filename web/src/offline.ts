import { VERSION } from "./version";
import { deviceId, deviceName } from "./connection";

/** Playing with no internet, or none good enough: the server's own game runs on this phone (public/offline/worker.js,
 * server/bridge/local.py), and the table it plays is kept here until the server can take it back.
 *
 * - While you play the bots on the server, the server sends this phone a copy of the table after every change (a
 *   "carry" message, kept as CARRY). If the server stops answering, the table carries on here from that copy.
 * - With no internet at all, Play with bots starts a table here.
 * - Finished boards wait here (BOARDS) until they can go to your account, for My stats and the review.
 * - Once the server answers again, the table goes back to it at the end of the board (unless this device is set to
 *   play the bots here). */

const TABLE = "bridge-offline-table"; // the table being played here: {snap (JSON text), room}
const CARRY = "bridge-carry"; // the server table's latest copy: {room, snap (JSON text)}
const BOARDS = "bridge-offline-boards"; // finished boards for your account: [{user, rec}]
const DROPS = "bridge-offline-drops"; // boards Undo took back after they went to your account
const READY = "bridge-offline-ready"; // the version whose engine files are all on this phone
const WHERE = "bridge-bots-here"; // "0": the server plays the bots while there's internet (the menu's switch)

interface Kept {
  snap: string;
  room: string;
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* full or private mode: the game goes on, it just won't be kept */
  }
}

/** This browser can run the engine: a worker, WebAssembly, and somewhere to keep the files. */
export function offlineSupported(): boolean {
  return typeof Worker !== "undefined" && typeof WebAssembly !== "undefined" && "serviceWorker" in navigator;
}

/** Every file the engine needs is on this phone, so it can start with no internet. */
export function offlineReady(): boolean {
  return offlineSupported() && read<string | null>(READY, null) === VERSION;
}

/** Bot tables play on this phone (the default), not the server. */
export function botsHere(): boolean {
  return read<string | null>(WHERE, null) !== "0";
}

export function setBotsHere(on: boolean) {
  write(WHERE, on ? "1" : "0");
}

const key = (r: any) => `${r.finished_at}-${r.room}-${r.board}`;

// --- getting the files onto the phone ---------------------------------------------------------------------------
// Two caches, which the service worker (public/sw.js) answers from when there's no internet: the app itself (its page
// and the files it loads, refreshed with each version), and the engine (Pyodide, kept until Pyodide is updated, and
// the game, about 260 KB, again with each version). update.ts's Reload keeps the engine's.
export const APP_CACHE = "bridge-app";
export const ENGINE_CACHE = "bridge-engine";
const FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
const pyodideUrl = (f: string) => `/offline/pyodide/${__PYODIDE__}/${f}`;
const engineUrl = () => `/offline/engine.zip?v=${encodeURIComponent(VERSION)}`;
const path = (u: string) => {
  const url = new URL(u, location.href);
  return url.pathname + url.search;
};
let preparing: Promise<boolean> | null = null;
// how far the first download has got, 0 to 1, for the menu's switch (weighted by each file's rough size)
const WEIGHT: Record<string, number> = { "pyodide.asm.wasm": 9, "python_stdlib.zip": 2.4, "pyodide.asm.js": 1.2 };
const progress = new Set<(done: number) => void>();
export function onOfflineProgress(fn: (done: number) => void): () => void {
  progress.add(fn);
  return () => progress.delete(fn);
}

/** Puts what the app needs with no internet on this phone (about 12 MB the first time, then a few hundred KB with each
 * new version), so it's there before the internet goes. */
export function prepareOffline(): Promise<boolean> {
  if (!offlineSupported() || typeof caches === "undefined") return Promise.resolve(false);
  if (offlineReady()) return Promise.resolve(true);
  preparing ??= (async () => {
    try {
      await navigator.serviceWorker.register("/sw.js");
      const engine = await caches.open(ENGINE_CACHE);
      const wanted = [...FILES.map(pyodideUrl), engineUrl()];
      const weight = (url: string) => WEIGHT[url.split("/").pop()!] ?? 0.3;
      const total = wanted.reduce((a, u) => a + weight(u), 0) + 1; // + 1 for the app's own files
      let done = 0;
      const tell = () => progress.forEach((fn) => fn(Math.min(1, done / total)));
      for (const url of wanted) {
        done += weight(url);
        if (await engine.match(url)) continue;
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) throw new Error(url);
        await engine.put(url, res);
        tell();
      }
      for (const req of await engine.keys()) if (!wanted.includes(path(req.url))) await engine.delete(req);
      // the app: this page and the files it loaded, and the lists the table menu shows
      const app = await caches.open(APP_CACHE);
      await import("./components/WifiPair"); // loaded only when it's used, so load it now to keep it
      const loaded = [...document.querySelectorAll("script[src], link[rel=stylesheet], link[rel=modulepreload]")].map(
        (el) => (el as HTMLScriptElement).src || (el as HTMLLinkElement).href,
      );
      const own = [...loaded, ...performance.getEntriesByType("resource").map((e) => e.name)]
        .filter((u) => u && new URL(u).origin === location.origin && (new URL(u).pathname.startsWith("/assets/") || loaded.includes(u)))
        .map(path)
        .filter((u, i, all) => all.indexOf(u) === i);
      const page = ["/", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/apple-touch-icon.png", "/offline/worker.js",
        "/api/conventions", "/api/lessons", ...own];
      for (const url of page) {
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) throw new Error(url);
        await app.put(url, res);
      }
      for (const req of await app.keys()) if (path(req.url).startsWith("/assets/") && !own.includes(path(req.url))) await app.delete(req);
      write(READY, VERSION);
      done = total;
      tell();
      return true;
    } catch {
      return false;
    } finally {
      preparing = null;
    }
  })();
  return preparing;
}

// --- the engine -------------------------------------------------------------------------------------------------
type Msg = { op: string; [k: string]: any };

class Engine {
  game: Worker;
  helper: Worker | null = null;
  booted: Promise<void>;
  started: Promise<void> | null = null;
  room: string | null = null; // the table it's playing
  sockets = new Map<number, { hear: (text: string) => void }>();
  next = 1;

  constructor() {
    this.game = new Worker("/offline/worker.js");
    const channel = new MessageChannel();
    const boots: Promise<unknown>[] = [this.ask(this.game, { op: "boot", version: VERSION, pyodide: __PYODIDE__, role: "game", port: channel.port1 }, "booted", [channel.port1])];
    // the helper works out hints and the review's odds ahead of time; a phone short of memory plays without it
    const memory = (navigator as { deviceMemory?: number }).deviceMemory;
    if (!memory || memory >= 2) {
      this.helper = new Worker("/offline/worker.js");
      boots.push(this.ask(this.helper, { op: "boot", version: VERSION, pyodide: __PYODIDE__, role: "helper", port: channel.port2 }, "booted", [channel.port2]).catch(() => {
        this.helper?.terminate();
        this.helper = null;
      }));
    }
    this.game.addEventListener("message", (ev) => this.heard(ev.data as Msg));
    this.booted = Promise.all(boots).then(() => undefined);
  }

  private ask(w: Worker, m: Msg, answer: string, transfer: Transferable[] = []): Promise<Msg> {
    return new Promise((resolve, reject) => {
      const on = (ev: MessageEvent) => {
        const r = ev.data as Msg;
        if (r.op === answer || r.op === "error") {
          w.removeEventListener("message", on);
          if (r.op === "error") reject(new Error(r.message));
          else resolve(r);
        }
      };
      w.addEventListener("message", on);
      w.addEventListener("error", (e) => reject(new Error(e.message || "the engine didn't start")), { once: true });
      w.postMessage(m, transfer);
    });
  }

  private heard(m: Msg) {
    if (m.op === "post") {
      if (m.conn === 0) kept(JSON.parse(m.text));
      else this.sockets.get(m.conn)?.hear(m.text);
    } else if (m.op === "fault") {
      console.warn("offline engine:", m.message);
    }
  }

  /** Plays `room`: carries on with the copy kept on this phone, or starts a new table. Once only (see engineFor). */
  table(room: string, fresh?: { settings: object; practice?: string }): Promise<void> {
    if (this.started) return this.started;
    this.room = room;
    const keptTable = read<Kept | null>(TABLE, null);
    const snapshot = !fresh && keptTable?.room === room ? keptTable.snap : null;
    this.started = this.booted.then(() =>
      this.ask(this.game, { op: "start", snapshot, code: room, settings: fresh?.settings ?? {}, practice: fresh?.practice }, "started").then(() => undefined),
    );
    return this.started;
  }

  open(sock: { hear: (text: string) => void }) {
    const conn = this.next++;
    this.sockets.set(conn, sock);
    return conn;
  }

  send(conn: number, text: string) {
    this.game.postMessage({ op: "msg", conn, text });
  }

  close(conn: number) {
    this.sockets.delete(conn);
    this.game.postMessage({ op: "close", conn });
  }
}

let engine: Engine | null = null;
const theEngine = () => (engine ??= new Engine());
function dropEngine() {
  engine?.game.terminate();
  engine?.helper?.terminate();
  engine = null;
}

/** The engine for `room`: one engine plays one table, so another table (or a new one) gets fresh workers. */
function engineFor(room: string, fresh?: object): Engine {
  if (engine?.started && (engine.room !== room || fresh)) dropEngine();
  return theEngine();
}

/** Done with the table on this phone: a fresh engine gets ready for the next one. */
export function retireEngine() {
  if (!engine?.started) return;
  dropEngine();
  warmEngine();
}

/** Start the engine early (it takes a few seconds), e.g. when the server stops answering. */
export function warmEngine() {
  if (offlineReady()) theEngine();
}

/** What the game hands back after every change: the table to keep, boards for your account, settings to remember. */
let boardsKept: (() => void) | null = null;
/** App.tsx sends finished boards to your account as soon as there are some (when there's internet). */
export function onBoardsKept(fn: (() => void) | null) {
  boardsKept = fn;
}

let parking: ((snap: object) => void) | null = null;
/** App.tsx sends each copy of the table to your account on the server, so your other devices can carry on with it. */
export function parkWith(fn: ((snap: object) => void) | null) {
  parking = fn;
}

function kept(m: { type: string; snap: object; boards?: { user: string | null; rec: any }[]; drop?: { user: string | null; rec: any }[]; chose?: object[] }) {
  const snap = m.snap as { code: string };
  write(TABLE, { snap: JSON.stringify(m.snap), room: snap.code } satisfies Kept);
  parking?.(m.snap);
  let boards = read<{ user: string | null; rec: any }[]>(BOARDS, []);
  // a board's record comes again once its review is complete: the newer one replaces it
  for (const b of m.boards ?? []) {
    // a partner's board on this phone's Wi-Fi table goes to their phone (wifi.ts)
    if (b.user && !forward?.(b.user, b.rec)) boards = [...boards.filter((x) => key(x.rec) !== key(b.rec)), b];
  }
  const drops = read<{ user: string; rec: any }[]>(DROPS, []);
  for (const d of m.drop ?? []) {
    const queued = boards.some((x) => key(x.rec) === key(d.rec));
    boards = boards.filter((x) => key(x.rec) !== key(d.rec));
    if (!queued && d.user) drops.push({ user: d.user, rec: d.rec });
  }
  write(BOARDS, boards);
  write(DROPS, drops);
  if (m.boards?.length || m.drop?.length) boardsKept?.();
  if (m.chose?.length) {
    try {
      const prefs = JSON.parse(localStorage.getItem("bridge-prefs") || "{}");
      prefs.table = Object.assign(prefs.table || {}, ...m.chose);
      localStorage.setItem("bridge-prefs", JSON.stringify(prefs));
    } catch {
      /* not remembered: fine */
    }
  }
}

/** A WebSocket to the table on this phone: the app's table code (connection.ts) uses it just as it uses the server's. */
export class LocalSocket {
  static readonly OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  private conn = 0;
  private engine: Engine;

  constructor(room: string, fresh?: { settings: object; practice?: string }) {
    const e = engineFor(room, fresh);
    this.engine = e;
    e.table(room, fresh).then(
      () => {
        if (this.readyState === 3) return;
        this.conn = e.open(this);
        this.readyState = 1;
        this.onopen?.();
      },
      (err) => {
        console.warn("offline engine:", String(err?.message || err));
        dropEngine(); // the next table here starts it afresh
        if (this.readyState === 3) return;
        this.readyState = 1;
        this.onmessage?.({ data: JSON.stringify({ type: "error", fatal: true, message: `The game couldn't start on this ${deviceName() || "device"}` }) });
        this.readyState = 3;
      },
    );
  }

  hear(text: string) {
    if (this.readyState === 1) this.onmessage?.({ data: text });
  }

  send(text: string) {
    if (this.readyState === 1) this.engine.send(this.conn, text);
  }

  close() {
    if (this.readyState === 1) this.engine.close(this.conn);
    this.readyState = 3;
  }
}

/** Someone else at this phone's table, joined over the Wi-Fi (wifi.ts): `send` passes on what their phone says, and
 * `hear` what the table says to them. */
export interface Link {
  send: (text: string) => void;
  hear: (text: string) => void;
  close: () => void;
}

export function hostLink(toPartner: (text: string) => void): Link {
  const e = theEngine();
  const conn = e.open({ hear: toPartner });
  return { send: (text) => e.send(conn, text), hear: toPartner, close: () => e.close(conn) };
}

let forward: ((user: string, rec: unknown) => boolean) | null = null;
export function forwardBoards(fn: (user: string, rec: unknown) => boolean) {
  forward = fn;
}

/** A board played at a table on another phone, for your account: it waits here like the boards played on this one. */
export function keepBoard(user: string, rec: any) {
  write(BOARDS, [...read<{ user: string | null; rec: any }[]>(BOARDS, []).filter((x) => key(x.rec) !== key(rec)), { user, rec }]);
}

/** Whether this phone is playing a table now, so a partner can join it. */
export function hostingTable(): boolean {
  return !!engine?.started;
}

// --- the server's copy -------------------------------------------------------------------------------------------
export function keepCarry(room: string, snap: object) {
  write(CARRY, { room, snap: JSON.stringify(snap) } satisfies Kept);
}

export function forgetCarry() {
  write(CARRY, null);
}

/** The server stopped answering at this table: there's a copy here to carry on from. */
export function canCarryOn(room: string): boolean {
  return offlineReady() && read<Kept | null>(CARRY, null)?.room === room;
}

/** Carry on with the server's last copy of `room` on this phone. */
export function carryOn(room: string) {
  const c = read<Kept | null>(CARRY, null);
  if (c?.room === room) write(TABLE, c);
}

/** A table being played on this phone, to go back to. */
export function keptTable(): string | null {
  return read<Kept | null>(TABLE, null)?.room ?? null;
}

export function forgetTable() {
  write(TABLE, null);
}

// --- back to the server -------------------------------------------------------------------------------------------
/** The server answers. */
export async function serverAnswers(): Promise<boolean> {
  try {
    const ctl = new AbortController();
    const t = window.setTimeout(() => ctl.abort(), 4000);
    const res = await fetch("/api/version", { cache: "no-store", signal: ctl.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

/** Sends boards played here to your account. Returns how many went. */
export async function sendBoards(token: string | null, userId: string | null): Promise<number> {
  if (!token || !userId) return 0;
  const boards = read<{ user: string | null; rec: any }[]>(BOARDS, []).filter((b) => b.user === userId);
  const drops = read<{ user: string; rec: any }[]>(DROPS, []).filter((b) => b.user === userId);
  if (!boards.length && !drops.length) return 0;
  let sent = 0;
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  for (const b of boards) {
    const res = await fetch("/api/me/offline-boards", { method: "POST", headers, body: JSON.stringify({ boards: [b.rec] }) });
    if (!res.ok) break;
    sent++;
    write(BOARDS, read<{ user: string | null; rec: any }[]>(BOARDS, []).filter((x) => key(x.rec) !== key(b.rec)));
  }
  if (drops.length) {
    const res = await fetch("/api/me/offline-boards", { method: "POST", headers, body: JSON.stringify({ drop: drops.map((d) => d.rec) }) });
    if (res.ok) write(DROPS, read<{ user: string; rec: any }[]>(DROPS, []).filter((d) => d.user !== userId));
  }
  return sent;
}

/** Sends this phone's table to your account on the server (Rooms.park). Returns the table's code there once another
 * of your devices has carried on with it. */
export async function parkTable(snap: object, seat: string, auth: string): Promise<{ taken?: string; closed?: string }> {
  const res = await fetch("/api/me/parked", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth}` },
    body: JSON.stringify({ snap, token: seat, device: deviceId() }), // two devices at once meet at one table (Rooms.park)
  });
  if (!res.ok) return {};
  const body = await res.json().catch(() => ({}));
  if (body.taken || body.closed) write(TABLE, null); // gone to another device, or closed on the Admin page
  return body;
}

/** Where to ask whether the Admin page closed a table: by its code, and by this phone's seat at it (the copy here
 * can have another code than the server's, "HOME" for one started here). */
export function closedUrl(room: string, seat?: string | null): string {
  return `/api/rooms/${encodeURIComponent(room)}/closed` + (seat ? `?seat=${encodeURIComponent(seat)}` : "");
}

/** Whether the Admin page closed the table `room` played here (asked with this phone's seat at it). */
export async function tableClosed(room: string, seat?: string | null): Promise<boolean> {
  const kept = read<Kept | null>(TABLE, null);
  const res = await fetch(closedUrl(room, seat || (kept?.room === room ? keptSeat(kept) : null)));
  return res.ok && !!(await res.json()).closed;
}

function keptSeat(kept: Kept): string | null {
  try {
    const players = (JSON.parse(kept.snap) as { players?: Record<string, { token?: string }> }).players ?? {};
    return Object.values(players).find((p) => p.token)?.token ?? null;
  } catch {
    return null;
  }
}

/** The Admin page closed this table: a copy of it here is let go. */
export class TableClosed extends Error {}

/** Whether the Admin page closed the table kept here (it's let go if so). False when the server can't be asked. */
export async function keptTableClosed(): Promise<boolean> {
  const kept = read<Kept | null>(TABLE, null);
  const room = kept?.room;
  if (!room) return false;
  try {
    const res = await fetch(closedUrl(room, keptSeat(kept)));
    if (!res.ok || !(await res.json()).closed) return false;
  } catch {
    return false;
  }
  if (keptTable() === room) write(TABLE, null);
  return true;
}

/** The table played here goes back to the server. Returns its code there. */
export async function carryBack(token: string, auth: string | null): Promise<string> {
  const t = read<Kept | null>(TABLE, null);
  if (!t) throw new Error("no table to send back");
  const res = await fetch("/api/rooms/carry", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(auth ? { Authorization: `Bearer ${auth}` } : {}) },
    body: JSON.stringify({ snap: JSON.parse(t.snap), token }),
  });
  const body = await res.json().catch(() => ({}));
  if (res.status === 410) {
    write(TABLE, null);
    throw new TableClosed(body.detail || "This table was closed");
  }
  if (!res.ok) throw new Error(body.detail || "The server didn't take the table back");
  write(TABLE, null);
  return body.code as string;
}
