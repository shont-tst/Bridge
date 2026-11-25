import { useEffect, useState } from "react";
import type { Account } from "../account";
import { SEAT_NAME, contractLabel, signed } from "../cards";
import type { Contract, ReplaySpec, Seat } from "../types";
import CheatSheetLink from "./CheatSheet";
import { BiddingStatsInfo, DeclaringStatsInfo, DefenseStatsInfo, HelpUsedInfo, LevelInfo, ParInfo, SecondTableInfo } from "./Explain";
import { SavedBoardPanel, type SavedRecord } from "./SavedBoard";
import SuitText from "./SuitText";

interface Summary {
  boards: number;
  all_boards?: number; // boards before any were excluded
  vs_par: number | null;
  at_or_above_par: number | null;
  declared: number;
  made: number;
  makeable: number;
  declarer_lost: number | null;
  defended: number;
  defender_lost: number | null;
  leads: number;
  costly_leads: number;
  off_system_per_10: number | null;
  off_system_by: [string, number][];
  off_system_points?: number | null; // points per call against the system's call, perfect play (calls nobody bid after)
  off_system_helped?: number;
  off_system_cost?: number;
  off_system_same?: number;
  hints_per_board: number | null;
  undos_per_board: number | null;
  coach_per_board?: number | null;
  second_imps?: number | null; // IMPs a board against the same deal played with level 10 in your seat
  second_boards?: number;
  second_bidding?: number | null; // where those IMPs came from
  second_declaring?: number | null;
  second_defending?: number | null;
}

interface Stats {
  now: Summary;
  before: Summary | null;
  trend: { day: string; vs_par: number; boards: number }[];
  level: { level: number | null; low?: number; high?: number; declaring: number | null; defending: number | null; hands: number; needed: number };
  bots: number | null;
  left_out?: Help[];
}

type Help = "hints" | "undo" | "coach";
const HELP: [Help, string, keyof Summary][] = [["hints", "Hints", "hints_per_board"], ["undo", "Undo", "undos_per_board"], ["coach", "AI coach", "coach_per_board"]];
const EXCLUDE_KEY = "statsExclude"; // this phone's ticks, kept between visits

function loadExclude(): Help[] {
  try {
    const v = JSON.parse(localStorage.getItem(EXCLUDE_KEY) || "[]");
    return Array.isArray(v) ? v.filter((h) => HELP.some(([k]) => k === h)) : [];
  } catch {
    return [];
  }
}

function saveExclude(v: Help[]) {
  try {
    localStorage.setItem(EXCLUDE_KEY, JSON.stringify(v));
  } catch {
    // private browsing: the ticks just aren't remembered
  }
}

interface Row {
  key: string;
  at: number;
  board: number;
  seat: Seat;
  contract: Contract | null;
  tricks: number;
  score: number;
  par: number | null;
  partner: string | null;
  role: string | null;
  bots: Seat[];
}

const partnerOf: Record<Seat, Seat> = { N: "S", S: "N", E: "W", W: "E" };

/** Better or worse than the 30 days before, for a number where lower is better (or higher, with `up`). */
/** An average to one decimal, with its sign: "+0.8", "−0.9". */
const one = (v: number) => signed(Math.round(v * 10) / 10);

const TIP_BOARDS = 20; // second-table boards before the weakest area gets a tip

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const listOf = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** A part of the game's heading, with its IMPs a board against the second table at the right. */
function Part({ name, imps, info }: { name: string; imps: number | null | undefined; info: React.ReactNode }) {
  return (
    <div className="part-head">
      <span className="k">
        {name} {info}
      </span>
      {imps != null && (
        <span className={`v ${imps >= 0 ? "up" : "low"}`}>
          {one(imps)} <small>IMPs</small>
        </span>
      )}
    </div>
  );
}

function Row({ label, value, change }: { label: string; value: string | number; change?: React.ReactNode }) {
  return (
    <div className="row">
      <span>
        {label}
        {change}
      </span>
      <b>{value}</b>
    </div>
  );
}

function Change({ now, before, up = false }: { now: number | null; before: number | null | undefined; up?: boolean }) {
  if (now == null || before == null || Math.abs(now - before) < 0.05) return null;
  const better = up ? now > before : now < before;
  return <span className={better ? "better" : "worse"}>{better ? " ▲ better" : " ▼ worse"}</span>;
}

function Trend({ points }: { points: Stats["trend"] }) {
  if (points.length < 2) return <p className="small muted-on-felt">Play on two days to see the line.</p>;
  const vals = points.map((p) => p.vs_par);
  const top = Math.max(100, ...vals.map(Math.abs));
  const W = 260, H = 50;
  const x = (i: number) => (i / (points.length - 1)) * W;
  const y = (v: number) => H / 2 - (v / top) * (H / 2 - 4);
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.vs_par).toFixed(1)}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Score against par, day by day">
      <line x1="0" y1={H / 2} x2={W} y2={H / 2} className="par-line" />
      <polyline points={line} className="trend-line" />
      <circle cx={x(points.length - 1)} cy={y(vals[vals.length - 1])} r="3" className="trend-dot" />
    </svg>
  );
}

function Level({ s }: { s: Stats }) {
  const l = s.level;
  if (l.level == null)
    return (
      <div className="rating">
        <div>
          <span className="rk">Your level</span>
        </div>
        <span className="d">
          Your level on the bots' 1 to 10 scale shows after {l.needed} hands declared or defended. You have {l.hands} so far.
        </span>
      </div>
    );
  const pct = (v: number) => `${((v - 1) / 9) * 100}%`;
  return (
    <div className="rating">
      <div>
        <span className="rk">
          Your level <LevelInfo hands={l.hands} />
        </span>
        <span className="rv">{l.level.toFixed(1)}</span>
      </div>
      {l.low != null && l.high != null && (
        <span className="d">
          Likely between {l.low.toFixed(1)} and {l.high.toFixed(1)}
        </span>
      )}
      <div className="rbar">
        <i style={{ left: pct(l.level) }} />
        {s.bots && <b style={{ left: pct(s.bots) }} />}
      </div>
      <div className="rs">
        <span>1</span>
        {s.bots && <span>Bots set to {s.bots}</span>}
        <span>10</span>
      </div>
      <span className="d">Last {l.hands} hands</span>
    </div>
  );
}

export default function MyStats({ account, onClose, back = "Lobby", onReplay }: {
  account: Account;
  onClose: () => void;
  back?: string;
  onReplay?: (spec: ReplaySpec) => void; // Play on from here, or Play this deal again, under a board's review
}) {
  const [days, setDays] = useState(30);
  const [exclude, setExclude] = useState<Help[]>(loadExclude);
  const [stats, setStats] = useState<Stats | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [filter, setFilter] = useState<"all" | "declarer" | "defender">("all");
  const [open, setOpen] = useState<{ row: Row; rec: SavedRecord } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const call = account.call; // the same function while the token stays the same
  useEffect(() => {
    const ex = exclude.map((h) => `&${h}=1`).join("");
    call<Stats>(`/api/me/stats?days=${days}${ex}`).then(setStats, (e) => setErr(e.message));
  }, [call, days, exclude]);
  const toggle = (h: Help) => {
    const next = exclude.includes(h) ? exclude.filter((x) => x !== h) : [...exclude, h];
    saveExclude(next);
    setExclude(next);
  };
  // the latest 200 boards, of the chosen kind: asked of the server, so a long history isn't all sent at once
  useEffect(() => {
    call<Row[]>(`/api/me/boards${filter === "all" ? "" : `?role=${filter}`}`).then(setRows, (e) => setErr(e.message));
  }, [call, filter]);

  const show = (row: Row) =>
    account.call(`/api/me/boards/${encodeURIComponent(row.key)}`).then(
      (rec) => {
        setOpen({ row, rec });
        window.scrollTo(0, 0);
      },
      (e) => setErr(e.message),
    );
  const list = (rows ?? []).filter((r) => filter === "all" || r.role === filter); // until the new page arrives

  if (open) {
    // walk through the list without going back to it: newer is up the list, older down it
    const at = list.findIndex((r) => r.key === open.row.key);
    const newer = at > 0 ? list[at - 1] : undefined;
    const older = at >= 0 && at < list.length - 1 ? list[at + 1] : undefined;
    const steps = (
      <span className="board-steps">
        <button className="link" disabled={!newer} onClick={() => newer && show(newer)}>
          ‹ Newer
        </button>
        <button className="link" disabled={!older} onClick={() => older && show(older)}>
          Older ›
        </button>
      </span>
    );
    return (
      <div className="stats-page">
        <div className="stats-top board-nav">
          <button className="link" onClick={() => setOpen(null)}>
            ‹ Hand history
          </button>
          {steps}
        </div>
        <SavedBoardPanel
          rec={open.rec}
          seat={open.row.seat}
          title={`Board ${open.row.board} · ${new Date(open.row.at * 1000).toLocaleDateString(undefined, { month: "long", day: "numeric" })}`}
          onReplay={onReplay}
        />
        <div className="stats-top board-nav bottom">{steps}</div>
      </div>
    );
  }

  const n = stats?.now;
  const b = stats?.before ?? undefined;
  // the part of the game that costs most against the second table, once there are enough boards to say
  const parts: [string, number | null | undefined][] = [["bidding", n?.second_bidding], ["declaring", n?.second_declaring], ["defense", n?.second_defending]];
  const worst = (n?.second_boards ?? 0) >= TIP_BOARDS ? parts.filter(([, v]) => v != null && v < 0).sort((x, y) => x[1]! - y[1]!)[0] : undefined;
  const weakest = worst?.[0];
  let lastDay = "";

  return (
    <div className="stats-page">
      <div className="stats-top">
        <button className="link" onClick={onClose}>
          ‹ {back}
        </button>
      </div>
      <div className="stats-cols">
        <section>
          <div className="stats-head">
            <h2>My stats</h2>
            <div className="seg">
              <button className={days === 30 ? "on" : ""} onClick={() => setDays(30)}>
                30 days
              </button>
              <button className={days === 0 ? "on" : ""} onClick={() => setDays(0)}>
                All time
              </button>
            </div>
          </div>
          {err && <p className="error">{err}</p>}
          {exclude.length > 0 && n && (
            <div className="excluded">
              <span>
                Excluding {listOf(exclude.map((h) => HELP.find(([k]) => k === h)![1].replace("Hints", "hints")))}
                {n.all_boards != null && (
                  <small>
                    {n.boards} of {n.all_boards} boards
                  </small>
                )}
              </span>
              <button className="link" onClick={() => { saveExclude([]); setExclude([]); }}>
                Show all
              </button>
            </div>
          )}
          {stats && <Level s={stats} />}
          {n && n.boards === 0 && (
            <p className="small muted-on-felt">
              No boards {exclude.length ? "left once those are excluded" : days ? "in the last 30 days" : "yet"}.
              {!exclude.length && " Finish a board while signed in and it shows here."}
            </p>
          )}
          {n && n.boards > 0 && (
            <>
              <div className="tiles">
                <div className="tile">
                  <span className="k">
                    Against par <ParInfo />
                  </span>
                  <span className={`v ${n.vs_par != null && n.vs_par >= 0 ? "up" : ""}`}>{n.vs_par == null ? "–" : signed(Math.round(n.vs_par))}</span>
                  <Trend points={stats!.trend} />
                  <span className="d">a board · {plural(n.boards, "board")}</span>
                </div>
                <div className="tile">
                  <span className="k">
                    Second table <SecondTableInfo />
                  </span>
                  <span className={`v ${n.second_imps != null && n.second_imps >= 0 ? "up" : ""}`}>{n.second_imps == null ? "–" : one(n.second_imps)}</span>
                  <span className="d">
                    IMPs a board against level 10 in your seat
                    <Change now={n.second_imps ?? null} before={b?.second_imps} up />
                  </span>
                </div>
              </div>
              <div className="stat">
                <Part name="Bidding" imps={n.second_bidding} info={<BiddingStatsInfo />} />
                <Row label="Calls off the system, per 10 boards" value={n.off_system_per_10 ?? "–"} change={<Change now={n.off_system_per_10} before={b?.off_system_per_10} />} />
                {n.off_system_points != null && (
                  <Row label="Points per call when you left it" value={signed(Math.round(n.off_system_points))} change={<Change now={n.off_system_points} before={b?.off_system_points} up />} />
                )}
                <span className="d">
                  {n.off_system_points != null && `Helped ${n.off_system_helped} · cost ${n.off_system_cost} · no difference ${n.off_system_same}. `}
                  {n.off_system_by.length ? `Most often: ${n.off_system_by.map(([t, c]) => `${t} (${c})`).join(", ")}` : "Sensible alternatives aren't counted."}
                </span>
                {weakest === "bidding" && (
                  <p className="tip">
                    Your weakest area. Check your calls against the <CheatSheetLink>cheat sheet</CheatSheetLink>.
                  </p>
                )}
              </div>
              <div className="stat">
                <Part name="Declaring" imps={n.second_declaring} info={<DeclaringStatsInfo />} />
                {stats!.level.declaring != null && <Row label="Level" value={stats!.level.declaring.toFixed(1)} />}
                <Row label="Tricks lost per hand" value={n.declarer_lost ?? "–"} change={<Change now={n.declarer_lost} before={b?.declarer_lost} />} />
                <Row label="Made, of those that could make" value={n.makeable ? `${n.made} of ${n.makeable}` : "–"} />
                {weakest === "declaring" && <p className="tip">Your weakest area. Open a hand you declared, below, to see which cards cost a trick.</p>}
              </div>
              <div className="stat">
                <Part name="Defense" imps={n.second_defending} info={<DefenseStatsInfo />} />
                {stats!.level.defending != null && <Row label="Level" value={stats!.level.defending.toFixed(1)} />}
                <Row label="Tricks given away per hand" value={n.defender_lost ?? "–"} change={<Change now={n.defender_lost} before={b?.defender_lost} />} />
                <Row label="Opening leads that cost a trick" value={n.leads ? `${n.costly_leads} of ${n.leads}` : "–"} />
                {weakest === "defense" && <p className="tip">Your weakest area. Practice Opening leads and Signals from the ☰ menu.</p>}
              </div>
              <div className="stat">
                <span className="k">
                  Help used <HelpUsedInfo />
                </span>
                <span className="d">Tick to exclude the boards where you used it.</span>
                <div className="ticks">
                  {HELP.filter(([h]) => h !== "coach" || n.coach_per_board || exclude.includes("coach")).map(([h, label, key]) => (
                    <label key={h}>
                      <input type="checkbox" checked={exclude.includes(h)} onChange={() => toggle(h)} />
                      <span>{label}</span>
                      <span className="n">
                        {(n[key] as number | null) ?? 0} <small>a board</small>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </>
          )}
        </section>
        <section>
          <div className="stats-head">
            <h2>Hand history</h2>
          </div>
          <div className="seg">
            {(["all", "declarer", "defender"] as const).map((f) => (
              <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                {f === "all" ? "All" : f === "declarer" ? "Declared" : "Defended"}
              </button>
            ))}
          </div>
          {rows && !list.length && <p className="small muted-on-felt">No boards here yet.</p>}
          <div className="hist">
            {list.slice(0, 200).map((r) => {
              const day = new Date(r.at * 1000).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
              const pn = r.partner ?? (r.bots.includes(partnerOf[r.seat]) ? `Bot ${SEAT_NAME[partnerOf[r.seat]]}` : "partner");
              const head = `${day} · with ${pn}`;
              const showHead = head !== lastDay;
              lastDay = head;
              const c = r.contract;
              const result = c ? r.tricks - (c.level + 6) : 0;
              return (
                <div key={r.key}>
                  {showHead && <div className="daygap">{head}</div>}
                  <button className="hrow" onClick={() => show(r)}>
                    <span className="b">Bd {r.board}</span>
                    <span className="c">
                      <SuitText text={contractLabel(c)} />
                      {c && <span className="pill">{result === 0 ? "made" : result > 0 ? `+${result}` : `down ${-result}`}</span>}
                    </span>
                    <span className="s">
                      {signed(r.score)}
                      {r.par != null && <small>par {signed(r.par)}</small>}
                    </span>
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
