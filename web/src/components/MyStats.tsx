import { useEffect, useState } from "react";
import type { Account } from "../account";
import { SEAT_NAME, contractLabel, signed } from "../cards";
import type { BoardResult, Contract, Seat } from "../types";
import { LevelInfo } from "./Explain";
import ResultPanel from "./ResultPanel";
import SuitText from "./SuitText";

interface Summary {
  boards: number;
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
}

interface Stats {
  now: Summary;
  before: Summary | null;
  trend: { day: string; vs_par: number; boards: number }[];
  level: { level: number | null; low?: number; high?: number; declaring: number | null; defending: number | null; hands: number; needed: number };
  bots: number | null;
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
      <span className="d">
        {l.declaring != null && `Declaring ${l.declaring.toFixed(1)}`}
        {l.declaring != null && l.defending != null && " · "}
        {l.defending != null && `Defending ${l.defending.toFixed(1)}`} · last {l.hands} hands
      </span>
    </div>
  );
}

export default function MyStats({ account, onClose, back = "Lobby" }: { account: Account; onClose: () => void; back?: string }) {
  const [days, setDays] = useState(30);
  const [stats, setStats] = useState<Stats | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [filter, setFilter] = useState<"all" | "declarer" | "defender">("all");
  const [open, setOpen] = useState<{ row: Row; rec: BoardResult & { players?: Record<string, string>; help?: any } } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const call = account.call; // the same function while the token stays the same
  useEffect(() => {
    call<Stats>(`/api/me/stats?days=${days}`).then(setStats, (e) => setErr(e.message));
  }, [call, days]);
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
    const names = open.rec.players ?? {};
    const nameOf = (s: Seat) => (s === open.row.seat ? "You" : names[s] ?? `Bot ${SEAT_NAME[s]}`);
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
        <ResultPanel
          result={open.rec}
          me={open.row.seat}
          nameOf={nameOf}
          help={open.rec.help?.[open.row.seat]}
          title={`Board ${open.row.board} · ${new Date(open.row.at * 1000).toLocaleDateString(undefined, { month: "long", day: "numeric" })}`}
        />
        <div className="stats-top board-nav bottom">{steps}</div>
      </div>
    );
  }

  const n = stats?.now;
  const b = stats?.before ?? undefined;
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
          {stats && <Level s={stats} />}
          {n && n.boards === 0 && <p className="small muted-on-felt">No boards {days ? "in the last 30 days" : "yet"}. Finish a board while signed in and it shows here.</p>}
          {n && n.boards > 0 && (
            <>
              <div className="stat">
                <span className="k">Results</span>
                <span className="l">Score against par, per board ({n.boards} {n.boards === 1 ? "board" : "boards"})</span>
                <span className={`v ${n.vs_par != null && n.vs_par >= 0 ? "up" : ""}`}>{n.vs_par == null ? "–" : signed(Math.round(n.vs_par))}</span>
                <Trend points={stats!.trend} />
                <span className="d">Dotted line: par. Above it, you beat par.</span>
              </div>
              <div className="stat">
                <span className="k">Declaring</span>
                <span className="l">Made, of those that could make</span>
                <span className="v">{n.makeable ? `${n.made} / ${n.makeable}` : "–"}</span>
                <span className="d">
                  {n.declarer_lost == null ? "No hands declared yet." : <>Tricks lost per hand: {n.declarer_lost}<Change now={n.declarer_lost} before={b?.declarer_lost} /></>}
                </span>
              </div>
              <div className="stat">
                <span className="k">Defending</span>
                <span className="l">Tricks given away per hand</span>
                <span className="v">{n.defender_lost ?? "–"}</span>
                <span className="d">
                  {n.leads ? `Opening leads that cost a trick: ${n.costly_leads} of ${n.leads}` : "No opening leads yet."}
                  <Change now={n.defender_lost} before={b?.defender_lost} />
                </span>
              </div>
              <div className="stat">
                <span className="k">Bidding</span>
                <span className="l">Calls off the system, per 10 boards</span>
                <span className="v">{n.off_system_per_10 ?? "–"}</span>
                <span className="d">
                  {n.off_system_by.length ? `Most often: ${n.off_system_by.map(([t, c]) => `${t} (${c})`).join(", ")}` : "Sensible alternatives aren't counted."}
                  <Change now={n.off_system_per_10} before={b?.off_system_per_10} />
                </span>
                {n.off_system_points != null && (
                  <>
                    <span className="l second">Points per call against the system's call</span>
                    <span className={`v second ${n.off_system_points > 0 ? "up" : ""}`}>{signed(Math.round(n.off_system_points))}</span>
                    <span className="d">
                      Helped {n.off_system_helped} · cost {n.off_system_cost} · no difference {n.off_system_same}
                      <Change now={n.off_system_points} before={b?.off_system_points} up />
                    </span>
                  </>
                )}
              </div>
              <div className="stat">
                <span className="k">Help used</span>
                <span className="l">Hints · undos{n.coach_per_board ? " · AI coach" : ""} per board</span>
                <span className="v">
                  {n.hints_per_board} · {n.undos_per_board}
                  {n.coach_per_board ? ` · ${n.coach_per_board}` : ""}
                </span>
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
