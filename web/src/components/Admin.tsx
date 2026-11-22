import { useCallback, useEffect, useRef, useState } from "react";
import { adminDownload, cancelled, lastSeen, withFaceId, type Account } from "../account";
import { SEAT_NAME, callLabel } from "../cards";
import type { Seat } from "../types";
import SuitText from "./SuitText";

/** The Admin page, for the site's owner only (the server refuses everyone else): players, tables, suggestions,
 * backups, abuse and a notice for everyone. Removing or restoring anything asks for Face ID again. */

type Tab = "players" | "friends" | "tables" | "load" | "feedback" | "backups" | "safety" | "notice" | "log";
const TABS: [Tab, string][] = [
  ["players", "Players"],
  ["friends", "Friends"],
  ["tables", "Tables"],
  ["load", "Load"],
  ["feedback", "Feedback"],
  ["backups", "Backups"],
  ["safety", "Safety"],
  ["notice", "Notice"],
  ["log", "Log"],
];

const when = (t?: number | null) =>
  t ? new Date(t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "–";
const day = (t?: number | null) => (t ? new Date(t * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "–");
const kb = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

export default function Admin({ account, onClose, back = "Lobby" }: { account: Account; onClose: () => void; back?: string }) {
  const [tab, setTab] = useState<Tab>("players");
  // Each tab's newest answer, kept by tab: a slow answer for a tab you tapped away from must not replace the one
  // you're looking at (it used to, leaving the new tab on "Loading…" for good).
  const [loaded, setLoaded] = useState<Partial<Record<Tab, any>>>({});
  const shown = useRef(tab);
  shown.current = tab;
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState<{ text: string; go: () => Promise<void> } | null>(null);

  const load = useCallback(
    (t: Tab = tab) => {
      account
        .call(`/api/admin/${t}`)
        .then((data) => setLoaded((m) => ({ ...m, [t]: data })))
        .catch((e: Error) => {
          if (shown.current === t) setMsg(e.message); // an error from a tab you left isn't about this one
        });
    },
    [account, tab],
  );
  useEffect(() => {
    setMsg(null);
    setAsk(null);
    load(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const data = loaded[tab] ?? null; // never one tab's answer shown on another

  /** Runs an action, asking for Face ID first when the server wants it, then reloads the tab. */
  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await withFaceId(account, fn);
      if (done) setMsg(done);
      setAsk(null);
      load();
    } catch (e) {
      if (!cancelled(e)) setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const post = (path: string, body: object = {}) => () => account.call(path, body);
  /** "Are you sure?" with the action's own words, for anything that can't be taken back. */
  const sure = (text: string, go: () => Promise<void>) => setAsk({ text, go });

  return (
    <div className="stats-page admin">
      <div className="stats-top">
        <button className="link" onClick={onClose}>
          ‹ {back}
        </button>
      </div>
      <div className="stats-head">
        <h2>Admin</h2>
      </div>
      <div className="admin-tabs" role="tablist">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {label}
          </button>
        ))}
      </div>
      {ask && (
        <div className="admin-ask" role="alert">
          <p>{ask.text}</p>
          <div className="row">
            <button className="small leave" disabled={busy} onClick={ask.go}>
              Yes
            </button>
            <button className="small" disabled={busy} onClick={() => setAsk(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {msg && <p className="admin-msg">{msg}</p>}
      {!data && !msg && <p className="small muted-on-felt">Loading…</p>}
      {data && tab === "players" && <Players data={data} busy={busy} run={run} post={post} sure={sure} />}
      {data && tab === "friends" && <Friends data={data} />}
      {data && tab === "tables" && <Tables data={data} busy={busy} run={run} post={post} sure={sure} />}
      {data && tab === "load" && <Load data={data} account={account} />}
      {data && tab === "feedback" && <Feedback data={data} busy={busy} run={run} post={post} sure={sure} />}
      {data && tab === "backups" && <Backups data={data} busy={busy} run={run} post={post} sure={sure} account={account} />}
      {data && tab === "safety" && <Safety data={data} busy={busy} run={run} post={post} sure={sure} />}
      {data && tab === "notice" && <Notice data={data} busy={busy} run={run} post={post} account={account} />}
      {data && tab === "log" && <Log data={data} />}
    </div>
  );
}

interface Props {
  data: any;
  busy: boolean;
  run: (fn: () => Promise<unknown>, done?: string) => Promise<void>;
  post: (path: string, body?: object) => () => Promise<unknown>;
  sure: (text: string, go: () => Promise<void>) => void;
}

/** "You → Ann → Dev", with the shorter way through friendships made later when there is one. */
function separation(p: any, name: (id: string) => string): string {
  const byFriends = p.friend_steps != null && (p.steps == null || p.friend_steps < p.steps) ? ` · ${steps(p.friend_steps)} by friends` : "";
  if (p.steps == null) return p.invited_by ? `Invited by ${name(p.invited_by)}${byFriends}` : `How they joined isn't known${byFriends}`;
  return `${p.chain.map((id: string, i: number) => (i === 0 ? "You" : name(id))).join(" → ")}${byFriends}`;
}
/** Players grouped by invites from you (you first, then 1 step, 2 steps…, then anyone the invites don't reach),
 * each group in the server's order (most recently here first). */
function bySteps(players: any[]): [string, any[]][] {
  const groups = new Map<number, any[]>();
  for (const p of players) {
    const k = p.admin ? 0 : (p.steps ?? Infinity);
    groups.set(k, [...(groups.get(k) ?? []), p]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([k, g]) => [k === 0 ? "You" : k === Infinity ? "Not linked to you by invites" : k === 1 ? "1 step: invited by you" : steps(k), g]);
}
/** "Claude connected (last used 5 min ago)": `used` is the last call that pulled the player's data, not a sign-in.
 * An app since removed still shows its last use: "ChatGPT removed (last used 6 days ago)". */
function aiCoach(p: any): string {
  const apps: { app: string; used?: number | null }[] = p.ai_apps ?? [];
  const used = (t?: number | null) => (t ? `last used ${ago(t)}` : "not used yet");
  const parts = apps.map((a) => `${a.app} connected (${used(a.used)})`);
  if (p.ai_used && !apps.some((a) => a.app === p.ai_used.app)) parts.push(`${p.ai_used.app} removed (${used(p.ai_used.at)})`);
  return parts.map((x) => ` · ${x}`).join("");
}
const ago = (t: number) => {
  const mins = Math.max(0, (Date.now() / 1000 - t) / 60);
  if (mins < 2) return "just now";
  if (mins < 60) return `${Math.round(mins)} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
};
const steps = (n: number) => `${n} step${n === 1 ? "" : "s"}`;

function Players({ data, busy, run, post, sure }: Props) {
  const players: any[] = data.players;
  const names = new Map(players.map((p) => [p.id, p.name]));
  const old = new Set<string>(data.old);
  return (
    <section className="admin-sec">
      <p className="small muted-on-felt">
        {players.length} account{players.length === 1 ? "" : "s"}. Removing one deletes its Face ID passkeys, friends, invites and hand history. Suggestions it sent stay.
      </p>
      {old.size > 0 && (
        <div className="admin-box">
          <b>Old accounts</b>
          <span className="small muted-on-felt">
            {`${old.size} not used for 12 months: ${players.filter((p) => old.has(p.id)).map((p) => p.name).join(", ")}`}
          </span>
          <button className="small" disabled={busy} onClick={() => sure(`Remove ${old.size} old account${old.size === 1 ? "" : "s"} and all their saved hands?`, () => run(post("/api/admin/players/clear-old"), "Old accounts removed."))}>
            Clear old accounts
          </button>
        </div>
      )}
      {bySteps(players).map(([head, group]) => (
        <div key={head}>
          <div className="steps-head">{head}</div>
          {group.map((p) => (
            <div key={p.id} className="admin-row">
              <div>
                <b>{p.name}</b>
                {p.admin && <span className="pill">you</span>}
                {old.has(p.id) && <span className="pill">old</span>}
                <small>
                  {lastSeen(p.last_seen)} · joined {day(p.created)} · {p.boards} boards · {p.friends} friend{p.friends === 1 ? "" : "s"} · {p.passkeys} passkey{p.passkeys === 1 ? "" : "s"}
                  {aiCoach(p)}
                  {p.notify ? " · notifications on" : ""} · {p.friend_code}
                </small>
                {!p.admin && <small>{separation(p, (id) => names.get(id) ?? "?")}</small>}
              </div>
              {!p.admin && (
                <button className="small" disabled={busy} onClick={() => sure(`Remove ${p.name}'s account and all their saved hands? This can only be undone by restoring a backup.`, () => run(post("/api/admin/players/remove", { id: p.id }), `${p.name} was removed.`))}>
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

interface FriendsData {
  players: { id: string; name: string; admin: boolean; steps?: number | null }[];
  links: { a: string; b: string; since?: number | null }[];
  waiting: { from: string; to: string }[];
}

/** Players around a circle in an order that keeps friends near each other: groups of friends together (biggest
 * first), each walked outward from its best-connected player, then anyone with no friends yet. */
function circleOrder(ids: string[], friendsOf: Map<string, string[]>, name: (id: string) => string): string[] {
  const seen = new Set<string>();
  const groups: string[][] = [];
  const byLinks = [...ids].sort((x, y) => friendsOf.get(y)!.length - friendsOf.get(x)!.length || name(x).localeCompare(name(y)));
  for (const start of byLinks) {
    if (seen.has(start) || !friendsOf.get(start)!.length) continue;
    const group: string[] = [];
    const queue = [start];
    seen.add(start);
    while (queue.length) {
      const id = queue.shift()!;
      group.push(id);
      for (const f of friendsOf.get(id)!) if (!seen.has(f)) (seen.add(f), queue.push(f));
    }
    groups.push(group);
  }
  groups.sort((x, y) => y.length - x.length);
  const alone = ids.filter((id) => !seen.has(id)).sort((x, y) => name(x).localeCompare(name(y)));
  return [...groups.flat(), ...alone];
}

/** Who is friends with whom: a chart (tap a name to pick out their friends) and the same as a list. */
function Friends({ data }: { data: FriendsData }) {
  const [pick, setPick] = useState<string | null>(null);
  const names = new Map(data.players.map((p) => [p.id, p.name]));
  const name = (id: string) => names.get(id) ?? "?";
  const friendsOf = new Map<string, string[]>(data.players.map((p) => [p.id, []]));
  for (const l of data.links) {
    friendsOf.get(l.a)?.push(l.b);
    friendsOf.get(l.b)?.push(l.a);
  }
  for (const list of friendsOf.values()) list.sort((x, y) => name(x).localeCompare(name(y)));
  const order = circleOrder(data.players.map((p) => p.id), friendsOf, name);
  const alone = data.players.filter((p) => !friendsOf.get(p.id)!.length);

  // the chart: a square, players on a circle, names outside it
  const size = 360;
  const c = size / 2;
  const r = order.length > 14 ? 112 : 120;
  const at = new Map(
    order.map((id, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, order.length) - Math.PI / 2;
      return [id, { x: c + r * Math.cos(a), y: c + r * Math.sin(a), a }];
    }),
  );
  const away = new Map(data.players.map((p) => [p.id, p.steps ?? 0]));
  /** A name with its steps from you raised after it (nothing for you, or when the invites don't reach you). */
  const tagged = (id: string) => (
    <span key={id} className="named">
      {name(id)}
      {away.get(id) ? <sup>{away.get(id)}</sup> : null}
    </span>
  );
  const lit = (id: string) => !pick || id === pick || friendsOf.get(pick)!.includes(id);
  const tap = (id: string) => setPick((p) => (p === id ? null : id));

  return (
    <section className="admin-sec">
      <p className="small muted-on-felt">
        {`${data.links.length} friendship${data.links.length === 1 ? "" : "s"} among ${data.players.length} player${data.players.length === 1 ? "" : "s"}.`}
        {alone.length ? ` ${alone.length} ${alone.length === 1 ? "has" : "have"} no friends yet.` : ""} Tap a name to see their friends. The small number is how many invites away from you they are.
      </p>
      {data.players.length > 0 && (
        <svg className="friends-chart" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Chart of who is friends with whom">
          {data.links.map((l) => {
            const p = at.get(l.a)!;
            const q = at.get(l.b)!;
            const on = pick === l.a || pick === l.b;
            return <line key={`${l.a}-${l.b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} className={on ? "on" : pick ? "dim" : ""} />;
          })}
          {order.map((id) => {
            const { x, y, a } = at.get(id)!;
            const cos = Math.cos(a);
            const anchor = Math.abs(cos) < 0.3 ? "middle" : cos > 0 ? "start" : "end";
            const lx = c + (r + 12) * cos;
            const ly = c + (r + 12) * Math.sin(a) + (Math.sin(a) > 0.7 ? 10 : Math.sin(a) < -0.7 ? -4 : 4);
            const n = friendsOf.get(id)!.length;
            return (
              <g key={id} className={`node${id === pick ? " pick" : ""}${lit(id) ? "" : " dim"}`} onClick={() => tap(id)}>
                <title>{`${name(id)}: ${n} friend${n === 1 ? "" : "s"}`}</title>
                <circle cx={x} cy={y} r={18} className="hit" />
                <circle cx={x} cy={y} r={n ? 5 : 4} className={n ? "dot" : "dot alone"} />
                <text x={lx} y={ly} textAnchor={anchor}>
                  {name(id)}
                  {away.get(id) ? (
                    <tspan dy={-5} className="sup">
                      {away.get(id)}
                    </tspan>
                  ) : null}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      <h3>Friends of each player</h3>
      {data.players.map((p) => {
        const fs = friendsOf.get(p.id)!;
        const asked = data.waiting.filter((w) => w.from === p.id).map((w) => name(w.to));
        return (
          <div key={p.id} className={`admin-row friends-row${pick === p.id ? " pick" : ""}`} onClick={() => tap(p.id)}>
            <div>
              <b>{tagged(p.id)}</b>
              {p.admin && <span className="pill">you</span>}
              <small>
                {fs.length ? (
                  <>
                    {`${fs.length} friend${fs.length === 1 ? "" : "s"}: `}
                    {fs.map((f, i) => [i ? ", " : "", tagged(f)])}
                  </>
                ) : (
                  "No friends yet"
                )}
                {asked.length ? ` · asked ${asked.join(", ")}, waiting` : ""}
              </small>
            </div>
          </div>
        );
      })}
    </section>
  );
}

function Tables({ data, busy, run, post, sure }: Props) {
  const [limit, setLimit] = useState(String(data.limit));
  const live = data.tables.filter((t: any) => t.here).length;
  return (
    <section className="admin-sec">
      <div className="admin-box">
        <b>Table limit</b>
        <span className="small muted-on-felt">
          {`New tables can't be started while ${data.limit} are in use (${live} now), so the ones in play stay quick. You can always start one.`}
        </span>
        <div className="row">
          <input type="number" inputMode="numeric" min={1} max={100} value={limit} onChange={(e) => setLimit(e.target.value)} aria-label="Table limit" />
          <button className="small" disabled={busy || !limit || Number(limit) === data.limit} onClick={() => run(post("/api/admin/tables/limit", { tables: Number(limit) }), `Limit set to ${limit} tables.`)}>
            Save
          </button>
        </div>
      </div>
      <h3>Signed in now</h3>
      <p className="small muted-on-felt">{data.online.length ? data.online.map((o: any) => o.name).join(", ") : "Nobody has the app open."}</p>
      <h3>Tables</h3>
      {!data.tables.length && <p className="small muted-on-felt">No tables in play.</p>}
      {data.tables.map((t: any) => (
        <div key={t.code} className="admin-row">
          <div>
            <b>{t.code}</b>
            {t.here ? <span className="pill">live</span> : <span className="pill dim">idle</span>}
            <small>
              {(["N", "E", "S", "W"] as const).map((s) => `${s} ${t.seats[s] ? t.seats[s].name + (t.seats[s].here ? "" : " (away)") : "bot"}`).join(" · ")}
              {t.watchers ? ` · ${t.watchers} watching` : ""} · board {t.board} · last move {when(t.active)}
            </small>
          </div>
          <button className="small" disabled={busy} onClick={() => sure(`Close table ${t.code}? Anyone at it goes back to the lobby.`, () => run(post("/api/admin/tables/close", { code: t.code }), `Table ${t.code} was closed.`))}>
            Close
          </button>
        </div>
      ))}
      <h3>Invite links not yet used</h3>
      {!data.invites.length && <p className="small muted-on-felt">None.</p>}
      {data.invites.map((i: any) => (
        <div key={i.code} className="admin-row">
          <div>
            <b>{i.kind === "device" ? "New device code" : "Invite link"}</b>
            <small>
              from {i.by} · {i.code} · {i.kind === "device" ? "" : i.sent ? `sent ${when(i.sent)} · ` : i.made ? "made but not sent yet · " : ""}until {when(i.expires)}
            </small>
          </div>
          <button className="small" disabled={busy} onClick={() => run(post("/api/admin/invites/cancel", { code: i.code }), "Cancelled.")}>
            Cancel
          </button>
        </div>
      ))}
    </section>
  );
}

// --- Load: tables in use and how long players waited, over time ----------------------------------------------
type Wait = { n: number; p50: number; p90: number; max: number } | null;
type Sample = { at: number; tables: number; people: number; bot: Wait; hint: Wait; review?: Wait; mem?: number | null; away: number };
type Bucket = { at: number; tables: number | null; bot: number | null; hint: number | null; review: number | null; mem: number | null; away: number };
type Machine = { cpu: string | null; cpus: number | null; mem: number | null; mem_limit: number | null };
const RANGES: [number, string, number][] = [
  [1, "Day", 15 * 60], // days shown, label, seconds per bar
  [7, "Week", 3600],
  [30, "Month", 4 * 3600],
];
const SLOW = 5; // seconds: past this a wait is noticeable (load test, 2026-10-29)

function buckets(rows: Sample[], days: number, step: number): Bucket[] {
  const end = Math.ceil(Date.now() / 1000 / step) * step;
  const out: Bucket[] = [];
  for (let t = end - days * 86400; t < end; t += step) out.push({ at: t, tables: null, bot: null, hint: null, review: null, mem: null, away: 0 });
  const top = (a: number | null, b: number | null | undefined) => (b == null ? a : Math.max(a ?? 0, b));
  for (const r of rows) {
    const b = out[Math.floor((r.at - (end - days * 86400)) / step)];
    if (!b) continue;
    b.tables = top(b.tables, r.tables);
    b.bot = top(b.bot, r.bot?.p90);
    b.hint = top(b.hint, r.hint?.p90);
    b.review = top(b.review, r.review?.p90);
    b.mem = top(b.mem, r.mem);
    b.away += r.away;
  }
  return out;
}

function Bars({ data, value, line, label, unit }: { data: Bucket[]; value: (b: Bucket) => number | null; line?: number; label: string; unit: string }) {
  const W = 300;
  const H = 70;
  const vals = data.map(value);
  const top = Math.max(line ?? 0, ...vals.map((v) => v ?? 0), 1) * 1.1;
  const bw = W / data.length;
  const y = (v: number) => H - (v / top) * H;
  return (
    <svg className="load-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
      {vals.map((v, i) =>
        v ? <rect key={i} x={i * bw} y={y(v)} width={Math.max(bw - 0.5, 0.5)} height={H - y(v)} className={line != null && v >= line ? "over" : ""}><title>{`${when(data[i].at)}: ${Math.round(v * 10) / 10}${unit}`}</title></rect> : null,
      )}
      {data.map((b, i) => (b.away ? <rect key={`a${i}`} x={i * bw} y={0} width={Math.max(bw, 2)} height={4} className="away"><title>{`${when(b.at)}: ${b.away} turned away`}</title></rect> : null))}
      {line != null && <line x1="0" x2={W} y1={y(line)} y2={y(line)} className="limit" />}
    </svg>
  );
}

function mb(n: number): string {
  return n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${n} MB`;
}

function machineLine(m: Machine): string {
  const cpu = m.cpu ? `${m.cpu.replace(/\((R|TM)\)/g, "").replace(/\s+/g, " ").trim()}, ` : "";
  const cpus = m.cpus ? `${m.cpus} CPU${m.cpus === 1 ? "" : "s"}` : "";
  const mem = m.mem != null ? `. Memory ${mb(m.mem)}${m.mem_limit ? ` of ${mb(m.mem_limit)}` : ""} in use now` : "";
  return `Running on ${cpu}${cpus}${mem}. Azure picks the processor, and it can change after an update.`;
}

function Load({ data, account }: { data: any; account: Account }) {
  const [days, setDays] = useState(1);
  const [rows, setRows] = useState<Sample[] | null>(null);
  useEffect(() => {
    if (days === 7) return setRows(data.rows); // the tab loads a week
    setRows(null);
    let current = true; // a slow answer for a range you tapped away from is dropped
    account
      .call(`/api/admin/load?days=${days}`)
      .then((r: any) => current && setRows(r.rows))
      .catch(() => current && setRows([]));
    return () => {
      current = false;
    };
  }, [days, account, data]);
  const step = RANGES.find((r) => r[0] === days)![2];
  const b = rows ? buckets(rows, days, step) : [];
  const busiest = rows?.reduce<Sample | null>((m, r) => (!m || r.tables > m.tables ? r : m), null);
  const away = rows?.reduce((n, r) => n + r.away, 0) ?? 0;
  const worst = (k: "bot" | "hint" | "review") => Math.max(0, ...(rows ?? []).map((r) => r[k]?.p90 ?? 0));
  const memPeak = Math.max(0, ...(rows ?? []).map((r) => r.mem ?? 0));
  const m: Machine | undefined = data.machine;
  const span = (
    <div className="load-span small muted-on-felt">
      <span>{b.length ? when(b[0].at) : ""}</span>
      <span>now</span>
    </div>
  );
  return (
    <section className="admin-sec">
      <p className="small muted-on-felt">
        {`${data.now.tables} table${data.now.tables === 1 ? "" : "s"} in use now, ${data.now.people} ${data.now.people === 1 ? "person" : "people"} playing. Limit ${data.limit}. Written down every ${Math.round(data.every / 60)} minutes.`}
        {m && ` ${machineLine(m)}`}
      </p>
      <div className="admin-tabs" role="tablist">
        {RANGES.map(([d, label]) => (
          <button key={d} role="tab" aria-selected={days === d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>
            {label}
          </button>
        ))}
      </div>
      {!rows && <p className="small muted-on-felt">Loading…</p>}
      {rows && !rows.length && <p className="small muted-on-felt">Nothing written down yet. The first figures appear a few minutes after the server starts.</p>}
      {rows && rows.length > 0 && (
        <>
          <p className="small">
            {`Busiest: ${busiest!.tables} table${busiest!.tables === 1 ? "" : "s"}${busiest!.tables ? `, ${when(busiest!.at)}` : ""}. Turned away by the limit: ${away}. Slowest bot ${worst("bot").toFixed(1)} s, slowest hint ${worst("hint").toFixed(1)} s, slowest review ${worst("review").toFixed(1)} s.${memPeak ? ` Most memory ${mb(memPeak)}.` : ""}`}
          </p>
          <h3>Tables in use</h3>
          <Bars data={b} value={(x) => x.tables} line={data.limit} label="Tables in use, with the limit" unit=" tables" />
          {span}
          <p className="small muted-on-felt">The dashed line is the limit. A red mark at the top: someone couldn't start a table.</p>
          <h3>Bot thinking time</h3>
          <Bars data={b} value={(x) => x.bot} line={SLOW} label="Seconds a bot took to choose a card" unit=" s" />
          {span}
          <h3>Hint wait</h3>
          <Bars data={b} value={(x) => x.hint} line={SLOW} label="Seconds a player waited for a tapped hint" unit=" s" />
          {span}
          <p className="small muted-on-felt">
            {`Seconds players waited on the server: 9 in 10 bot cards and tapped hints came quicker than the bar, not counting the pause the app adds on purpose. Bars past the dashed line (${SLOW} s) are slow enough to notice.`}
          </p>
          <h3>Review wait</h3>
          <Bars data={b} value={(x) => x.review} line={SLOW} label="Seconds from a board's end until its review had its odds" unit=" s" />
          {span}
          <p className="small muted-on-felt">Seconds from the end of a board until its review had all its odds and Helped or Cost figures.</p>
          <h3>Memory in use</h3>
          <Bars data={b} value={(x) => x.mem} line={m?.mem_limit ?? undefined} label="Memory the server used, with its limit" unit=" MB" />
          {span}
          <p className="small muted-on-felt">Everything the server does, feedback included.{m?.mem_limit ? " The dashed line is the limit." : ""}</p>
        </>
      )}
    </section>
  );
}

const STATUS: [string, string][] = [
  ["new", "New"],
  ["build", "Build"],
  ["maybe", "Maybe"],
  ["ignore", "Ignore"],
  ["done", "Done"],
];

function Feedback({ data, busy, run, post, sure }: Props) {
  const [show, setShow] = useState<"open" | "all">("open");
  const items: any[] = data.items.filter((f: any) => show === "all" || !["ignore", "done"].includes(f.status));
  return (
    <section className="admin-sec">
      <div className="seg">
        <button className={show === "open" ? "on" : ""} onClick={() => setShow("open")}>
          To review
        </button>
        <button className={show === "all" ? "on" : ""} onClick={() => setShow("all")}>
          All
        </button>
      </div>
      <p className="small muted-on-felt">Ignore and Done close the suggestion's GitHub issue; the others keep it open.</p>
      {!items.length && <p className="small muted-on-felt">Nothing here.</p>}
      {items.map((f) => (
        <div key={f.key} className="admin-feedback">
          <p>
            {f.about?.call ? (
              <>
                <b>
                  Bid: {SEAT_NAME[f.about.seat as Seat]}'s <SuitText text={callLabel(f.about.call)} />, board {f.about.board}
                </b>{" "}
                ({f.about.rule ?? "no rule"}).{" "}
              </>
            ) : f.about ? (
              <>
                <b>Board {f.about.board}</b> (table {f.about.room}).{" "}
              </>
            ) : null}
            {f.text}
          </p>
          <small>
            {f.name || "A guest"} · {f.at.slice(0, 10)} · version {f.version || "?"}
            {f.issue ? ` · issue #${f.issue}` : ""}
          </small>
          <div className="seg">
            {STATUS.map(([s, label]) => (
              <button key={s} disabled={busy} className={(f.status || "new") === s ? "on" : ""} onClick={() => run(post("/api/admin/feedback/mark", { key: f.key, status: s }))}>
                {label}
              </button>
            ))}
          </div>
          <button className="link small" disabled={busy} onClick={() => sure("Delete this suggestion? Use this for spam.", () => run(post("/api/admin/feedback/delete", { key: f.key }), "Deleted."))}>
            Delete
          </button>
        </div>
      ))}
    </section>
  );
}

function Backups({ data, busy, run, post, sure, account }: Props & { account: Account }) {
  const files: any[] = data.files;
  const label = (n: string) => n.replace(/\.json\.gz$/, "").replace(/^backup-/, "Week of ").replace(/^before-restore-(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})\d{2}$/, "Before restore, $1 $2:$3 UTC");
  return (
    <section className="admin-sec">
      <p className="small muted-on-felt">
        A backup of every account, friend, saved hand, table and suggestion is made each week, and the last 12 are kept. Restoring puts back every record in the backup; anything made since stays. A copy of everything is saved just before, so a restore can be undone.
      </p>
      {data.error && <p className="admin-msg">{data.error}</p>}
      <button disabled={busy} onClick={() => run(post("/api/admin/backups/run"), "Backup made.")}>
        Make a backup now
      </button>
      {!files.length && !data.error && <p className="small muted-on-felt">No backups yet.</p>}
      {files.map((f) => (
        <div key={f.name} className="admin-row">
          <div>
            <b>{label(f.name)}</b>
            <small>{kb(f.size)}</small>
          </div>
          <div className="row">
            <button className="small" disabled={busy} onClick={() => run(() => adminDownload(account, `/api/admin/backups/file?name=${encodeURIComponent(f.name)}`, f.name))}>
              Download
            </button>
            <button className="small" disabled={busy} onClick={() => sure(`Restore ${label(f.name)}? Records in it replace the ones there now, and removed players come back.`, () => run(post("/api/admin/backups/restore", { name: f.name }), "Restored."))}>
              Restore
            </button>
          </div>
        </div>
      ))}
      <p className="small muted-on-felt">A downloaded backup holds the site's sign-in keys too. Keep it somewhere private.</p>
    </section>
  );
}

function Safety({ data, busy, run, post, sure }: Props) {
  const [address, setAddress] = useState("");
  const block = (a: string) => sure(`Block ${a}? Nothing from that address will reach the site.`, () => run(post("/api/admin/safety/block", { address: a }), `${a} is blocked.`));
  const row = (r: any, extra: string) => (
    <div key={r.address} className="admin-row">
      <div>
        <b>{r.address}</b>
        <small>{extra}</small>
      </div>
      {r.address !== data.you && (
        <button className="small" disabled={busy} onClick={() => block(r.address)}>
          Block
        </button>
      )}
    </div>
  );
  return (
    <section className="admin-sec">
      <p className="small muted-on-felt">Your address right now is {data.you}. Counts start again whenever the site is updated.</p>
      <h3>Turned away in the last day</h3>
      {!data.refused.length && <p className="small muted-on-felt">Nobody went over a limit.</p>}
      {data.refused.map((r: any) => row(r, `${r.count} refused · ${r.buckets.join(", ")} · last ${when(r.last)}`))}
      <h3>Busiest in the last 10 minutes</h3>
      {!data.busy.length && <p className="small muted-on-felt">Quiet.</p>}
      {data.busy.map((r: any) => row(r, `${r.count} requests${r.address === data.you ? " · you" : ""}`))}
      <h3>Blocked</h3>
      {!data.blocked.length && <p className="small muted-on-felt">No addresses are blocked.</p>}
      {data.blocked.map((b: any) => (
        <div key={b.address} className="admin-row">
          <div>
            <b>{b.address}</b>
            <small>since {when(b.at)}</small>
          </div>
          <button className="small" disabled={busy} onClick={() => run(post("/api/admin/safety/unblock", { address: b.address }), "Unblocked.")}>
            Unblock
          </button>
        </div>
      ))}
      <div className="row">
        <input value={address} onChange={(e) => setAddress(e.target.value.trim())} placeholder="Address to block" />
        <button disabled={busy || !address} onClick={() => block(address)}>
          Block
        </button>
      </div>
    </section>
  );
}

function Notice({ data, busy, run, account }: Omit<Props, "sure"> & { account: Account }) {
  const current = data.notice; // what the server shows now, not what this phone saw when the app opened
  const [text, setText] = useState(current?.text ?? "");
  const [push, setPush] = useState(false);
  const [now, setNow] = useState(current?.text ?? "");
  const send = (t: string) =>
    run(async () => {
      const r = await account.call("/api/admin/notice", { text: t, push: push && !!t });
      setNow(r.notice?.text ?? "");
      return r;
    }, t ? "Posted." : "Taken down.");
  return (
    <section className="admin-sec">
      <p className="small muted-on-felt">A short message shown at the top of everyone's lobby until you take it down, for example "The site is being updated at 9pm."</p>
      {now && (
        <div className="admin-box">
          <b>Showing now</b>
          <span>{now}</span>
          <button className="small" disabled={busy} onClick={() => send("")}>
            Take it down
          </button>
        </div>
      )}
      <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={300} rows={3} placeholder="Your message" />
      <label className="toggle">
        <input type="checkbox" checked={push} onChange={(e) => setPush(e.target.checked)} />
        <span>Also send it as a phone notification to everyone who has notifications on</span>
      </label>
      <button className="primary" disabled={busy || !text.trim()} onClick={() => send(text)}>
        Post notice
      </button>
    </section>
  );
}

function Log({ data }: { data: any }) {
  return (
    <section className="admin-sec">
      {!data.rows.length && <p className="small muted-on-felt">Nothing done here yet.</p>}
      {data.rows.map((r: any, i: number) => (
        <div key={i} className="admin-row">
          <div>
            <b>{r.action}</b>
            <small>
              {when(r.at)} · {r.who}
              {r.detail ? ` · ${r.detail}` : ""}
            </small>
          </div>
        </div>
      ))}
    </section>
  );
}
