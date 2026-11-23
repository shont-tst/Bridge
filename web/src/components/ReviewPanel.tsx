import { useRef, useState } from "react";
import { RANKS, SEAT_NAME, callLabel, cardLabel, compass, contractLabel, partnerOf, sameSide, signed } from "../cards";
import type { BidReview, BoardResult, CardReview, SecondTable as Second, Seat } from "../types";
import AuctionView from "./AuctionView";
import { ReviewInfo, SecondTableInfo } from "./Explain";
import Hand from "./Hand";
import PlayView from "./PlayView";
import SuitText from "./SuitText";
import TrickArea from "./TrickArea";

function Card({ card }: { card: string }) {
  return <SuitText text={cardLabel(card)} />;
}

/** "a", "a and b", "a, b and c", skipping empty parts. */
const listed = (parts: string[]) => {
  const p = parts.filter(Boolean);
  return p.length > 1 ? `${p.slice(0, -1).join(", ")} and ${p[p.length - 1]}` : p[0] ?? "";
};

const isMistake = (c: CardReview) =>
  !!c.odds && (c.odds.better ?? (c.odds.best !== c.card && c.odds.best_pct > c.odds.played));

/** A card that cost a trick with all cards seen, weighed on the layouts its player could not rule out:
 * a mistake when another card was clearly the better bet, unlucky when the card played was as good a bet or better. */
function Verdict({ c, goal }: { c: CardReview; goal: string }) {
  const o = c.odds!;
  const pct = (n: number) => <><b>{n}%</b> of the time</>;
  if (o.tricks == null)
    // boards reviewed before 1.29: odds for making or beating the contract
    return (
      <div className="odds">
        <Card card={o.best} /> <SuitText text={goal} /> {pct(o.best_pct)}, <Card card={c.card} /> {pct(o.played)}.
      </div>
    );
  const tricks = `${o.tricks} ${o.tricks === 1 ? "trick" : "tricks"}`;
  if (isMistake(c)) {
    const other = o.hindsight && o.hindsight !== o.best;
    return (
      <div className="odds">
        <span className="tag mistake">Mistake</span> Better bet <Card card={o.best} />: {tricks} <b>{o.best_pct}%</b> vs{" "}
        <b>{o.played}%</b>.{other && <> <Card card={o.hindsight!} /> would have worked this time.</>}
      </div>
    );
  }
  const h = o.hindsight ?? c.best[0];
  const close = o.hindsight_pct == null || o.played - o.hindsight_pct < 10;
  return (
    <div className="odds">
      <span className="tag unlucky">Unlucky</span> <Card card={h} /> would have worked this time, but <Card card={c.card} /> was{" "}
      {close ? "as good a bet" : "the better bet"}: <b>{o.played}%</b>
      {o.hindsight_pct != null && <> vs <b>{o.hindsight_pct}%</b></>}.
    </div>
  );
}

/** "4♠ by South =", "3NT by West −2", "Passed out". */
const contractResult = (c: BoardResult["contract"], tricks: number) => {
  if (!c) return "Passed out";
  const over = tricks - (c.level + 6);
  return `${contractLabel(c)} ${over === 0 ? "=" : signed(over)}`;
};

/** The same deal played again with level 10 in your seat, in IMPs against your result, with its auction and play:
 * the body of the review's Second table pull-down, whose line carries the IMPs. */
function SecondTable({ s, pending }: { s?: Second; pending?: boolean }) {
  const [about, setAbout] = useState(false);
  if (!s) return pending ? <p className="muted">Playing it again with level 10 in your seat…</p> : null;
  const imps = s.imps;
  return (
    <div className="second-table">
      <p>
        Level {s.level} in your seat: <SuitText text={contractResult(s.contract, s.tricks)} />. {signed(s.score)} vs your {signed(s.table_score)}:{" "}
        {/* tap the IMPs for what they are and how they're worked out */}
        <button className={`imps ${imps > 0 ? "plus-ink" : imps < 0 ? "minus-ink" : "muted"}`} onClick={() => setAbout(true)}>
          {signed(imps)} {Math.abs(imps) === 1 ? "IMP" : "IMPs"}
        </button>{" "}
        <SecondTableInfo />
      </p>
      {s.bidding_imps != null && s.play_imps != null && (
        <p>From the bidding {signed(s.bidding_imps)}, from the play {signed(s.play_imps)}.</p>
      )}
      {about && <SecondTableInfo onClose={() => setAbout(false)} />}
      <h4>Their auction</h4>
      <AuctionView auction={s.auction} dealer={s.auction[0]?.seat ?? "N"} turn={null} room="" board={0} />
      {s.play.length > 0 && (
        <>
          <h4>Their play</h4>
          <PlayView play={s.play} whys={{}} dummy={s.contract ? partnerOf(s.contract.declarer) : undefined} contract={s.contract} room="" board={0} />
          {s.claimed ? <p className="muted small">Claimed the last {s.claimed === 1 ? "trick" : `${s.claimed} tricks`}.</p> : null}
        </>
      )}
    </div>
  );
}

/** Trick `n` (from 1) of the play: its cards in order, and who won it. */
function trickOf(result: BoardResult, n: number) {
  const cards = (result.play ?? []).slice((n - 1) * 4, n * 4).map(([seat, card]) => ({ seat, card }));
  if (cards.length === 0) return null;
  const trump = result.contract?.strain;
  const beats = (a: string, b: string) =>
    a[0] === b[0] ? RANKS.indexOf(a[1]) > RANKS.indexOf(b[1]) : a[0] === trump;
  const winner = cards.reduce((w, c) => (beats(c.card, w.card) ? c : w)).seat;
  return { leader: cards[0].seat, cards, winner: cards.length === 4 ? winner : undefined };
}

/** What `seat` held when trick `n` began. */
function heldAt(result: BoardResult, seat: Seat, n: number): string[] {
  const gone = new Set((result.play ?? []).slice(0, (n - 1) * 4).filter(([s]) => s === seat).map(([, c]) => c));
  return result.hands[seat].split(".").flatMap((p, i) => [...p].map((r) => "SHDC"[i] + r)).filter((c) => !gone.has(c));
}

/** The trick a costly card was played to, laid out as at the table, with the hand(s) its player could see and the
 * review's words for it again. */
function TrickPopup({ c, result, me, who, line, onClose }: {
  c: CardReview;
  result: BoardResult;
  me: Seat;
  who: (s: Seat) => string;
  line: React.ReactNode;
  onClose: () => void;
}) {
  const trick = trickOf(result, c.trick)!;
  const pos = compass(me);
  const better = c.odds ? (isMistake(c) ? c.odds.best : c.odds.hindsight ?? c.best[0]) : c.best[0];
  // the hands on show, as at the table: yours and dummy's, and the hand the card came from if it's neither
  const dummy = result.contract ? partnerOf(result.contract.declarer) : undefined;
  const shown = new Set<Seat>([me, c.seat, ...(dummy ? [dummy] : [])]);
  // dummy is "dummy", not the bot or player sitting there
  const label = (s: Seat) => (s === me ? "You" : s === dummy ? "Dummy" : who(s));
  const inline = (s: Seat) => (s === dummy && s !== me ? "dummy" : label(s));
  // each side's tricks before this one, shown as at the table: declarer taken/needed, and the
  // defenders' count by you, or else by the defender on your right
  const k = result.contract;
  const won = { NS: 0, EW: 0 };
  for (let n = 1; n < c.trick; n++) {
    const w = trickOf(result, n)?.winner;
    if (w) won[sameSide(w, "N") ? "NS" : "EW"]++;
  }
  const counter = (s: Seat) =>
    !!k && (s === k.declarer || (!sameSide(s, k.declarer) && (sameSide(me, k.declarer) ? s === pos.right : s === me)));
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet trick-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>Trick {c.trick}</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="trick-table">
          {(["top", "left", "right", "bottom"] as const).map((p) => {
            const s = pos[p];
            const name = (
              <div className={`seat-name ${s === trick.winner ? "won" : ""}`}>
                {label(s)}
                {k && counter(s) && (
                  <span className="tricks">
                    {" "}
                    • {won[sameSide(s, "N") ? "NS" : "EW"]}
                    {s === k.declarer && <small>/{k.level + 6}</small>}
                  </span>
                )}
              </div>
            );
            return (
              <div key={p} className={`seat-${p}`}>
                {p !== "bottom" && name}
                {shown.has(s) && <Hand cards={heldAt(result, s, c.trick)} compact hinted={s === c.seat ? better : undefined} />}
                {p === "bottom" && name}
              </div>
            );
          })}
          <div className="seat-mid">
            <TrickArea trick={trick} me={me} costly={c.card} />
          </div>
        </div>
        <p className="small">
          <SuitText
            text={trick.cards.map((x, i) => `${i === 0 ? label(x.seat) : inline(x.seat)} ${i === 0 ? "led " : ""}${cardLabel(x.card)}`).join(", ")}
          />
          {trick.winner && <>. {label(trick.winner)} won the trick.</>}
        </p>
        <div className="review trick-review">{line}</div>
        {better && (
          <p className="small muted">
            <span className="hint-ring card-ring"><SuitText text={cardLabel(better)} /></span>, {isMistake(c) ? "the better bet" : "the card that would have worked this time"}. Hands and trick counts as they were before the trick.
          </p>
        )}
      </div>
    </div>
  );
}

function Call({ call }: { call: string }) {
  return <SuitText text={callLabel(call)} />;
}

const SAME = 20; // points either way that count as no difference (as in server bidpath.py)

/** Helped, Cost or No difference for a call off the system, as BidOutcome tags it (null while it's worked out). */
function bidTag(b: BidReview, pending?: boolean) {
  const o = b.outcome;
  if (!o || (pending && !o.avg)) return null;
  const sign = b.seat === "N" || b.seat === "S" ? 1 : -1;
  const diff = o.avg ? o.avg.points_ns * sign : (o.actual_dd_ns - o.system_dd_ns) * sign;
  return diff > SAME ? <span className="tag helped">Helped {signed(diff)}</span>
    : diff < -SAME ? <span className="tag mistake">Cost {signed(diff)}</span>
    : <span className="tag unlucky">No difference</span>;
}

/** How this deal went against the 30-deal average, when they differ: "No harm this time" beside a Cost the deal
 * didn't pay at all, "Cost little this time" when it paid 20 points or less, and so on. Null when they agree or the
 * average isn't worked out yet. */
function thisTime(b: BidReview): string | null {
  const o = b.outcome;
  if (!o?.avg) return null;
  const sign = b.seat === "N" || b.seat === "S" ? 1 : -1;
  const kind = (d: number) => (d > SAME ? 1 : d < -SAME ? -1 : 0);
  const points = (o.actual_dd_ns - o.system_dd_ns) * sign;
  const here = kind(points);
  const usual = kind(o.avg.points_ns * sign);
  if (here === usual) return null;
  if (usual < 0) return here > 0 ? "Worked this time" : points < 0 ? "Cost little this time" : "No harm this time";
  if (usual > 0) return here < 0 ? "Cost this time" : points > 0 ? "Helped little this time" : "No gain this time";
  return here > 0 ? "Worked this time" : "Cost this time";
}

/** Did leaving the system help? The auction bid again from the system's call, both contracts scored with all cards
 * face up, from the bidder's side: on average over deals like this one when the server has worked that out (2.5 on),
 * else on this deal alone. */
function BidOutcome({ b, me, pending }: { b: BidReview; me: Seat; pending?: boolean }) {
  const o = b.outcome;
  if (!o) return null;
  const sign = b.seat === "N" || b.seat === "S" ? 1 : -1;
  const mine = o.actual_dd_ns * sign;
  const sys = o.system_dd_ns * sign;
  const avg = o.avg;
  const diff = avg ? avg.points_ns * sign : mine - sys;
  const sc = o.system_contract;
  const reaches = (start: string) =>
    sc ? <>{start} reaches <SuitText text={contractLabel(sc)} /></> : <>{start} passes it out</>;
  const later = o.bid_after ?? [];
  const mate = partnerOf(b.seat);
  const others = later.length === 0 ? "" : later.length === 1 && later[0] === mate ? "Partner" : later.includes(mate) ? "Both sides" : "Opponents";
  // when this deal went another way from the average, say so in words
  const usual = diff > SAME ? 1 : diff < -SAME ? -1 : 0;
  const onAverage = usual > 0 ? "it helps" : usual < 0 ? "it costs" : "it makes no difference";
  const note = thisTime(b);
  const luck = note ? `${note}, but on average ${onAverage}.` : "";
  return (
    <div className="odds">
      {bidTag(b, pending) ?? <span className="muted">Working out the odds…</span>}{" "}
      {avg && <>On average over {avg.deals} deals like this. This deal: </>}
      {reaches(avg ? "system" : "System")}: <b>{signed(sys)}</b> vs {b.seat === me ? "your " : ""}<b>{signed(mine)}</b>.
      {luck && <> {luck}</>}
      {others && <span className="muted"> {others} bid again after it.</span>}
    </div>
  );
}

/** After the board: a few lines that sum it up (par, your play, your bidding, the second table), the hands, then a
 * pull-down for each part in full: the auction, the play, the cards that cost a trick (each marked a mistake or
 * unlucky on the odds), the calls that left the system, the second table and the tricks with all cards seen. Tapping
 * a line opens its pull-down. Without a review (an old board, or one it couldn't be worked out for), just par, the
 * hands and the pull-downs there are. */
export default function ReviewPanel({ result, me, nameOf, help, watching, par, hands, auction, play: playRecord, dd }: {
  result: BoardResult;
  me: Seat;
  nameOf: (s: Seat) => string;
  help?: { hints?: number; undos?: number; coach?: number }; // what you used on this board
  watching?: boolean;
  par?: React.ReactNode; // "+110 for you (3♣ by North or South)"
  hands: React.ReactNode;
  auction?: React.ReactNode;
  play?: React.ReactNode; // the play, trick by trick
  dd?: React.ReactNode; // the tricks with all cards seen
}) {
  const [everyone, setEveryone] = useState(false);
  const [alternatives, setAlternatives] = useState(false);
  const [open, setOpen] = useState<CardReview | null>(null);
  const pulls = useRef<Record<string, HTMLDetailsElement | null>>({});
  const raw = result.review;
  const review = raw && !raw.error ? raw : undefined;
  const play = review?.play;
  const allBids = review?.bidding ?? [];
  const minor = allBids.filter((b) => b.minor).length;
  const bids = alternatives ? allBids : allBids.filter((b) => !b.minor);
  const offSystem = allBids.filter((b) => !b.minor);
  const ours = (s: Seat) => (s === "N" || s === "S") === (me === "N" || me === "S");
  // what a card is charged: its cost, less any the other side gave straight back
  const charged = (c: CardReview) => c.lost - (c.back ?? 0);
  const costly = (play?.cards ?? []).filter((c) => charged(c) > 0);
  const shown = (play?.cards ?? []).filter((c) => (charged(c) > 0 || (c.given_back && c.lost > 0)) && (everyone || ours(c.by)));
  const lostOurs = costly.filter((c) => ours(c.by)).reduce((a, c) => a + charged(c), 0);
  const gifts = costly.filter((c) => !ours(c.by)).reduce((a, c) => a + charged(c), 0);
  const tricks = (n: number) => `${n} ${n === 1 ? "trick" : "tricks"}`;
  const who = (s: Seat) => (s === me ? "You" : nameOf(s));
  // which calls and cards came right after a hint or an AI coach question (#153: so it's clear which turn a hint was for)
  const marks = result.asked ?? [];
  const markOf = (kind: "call" | "card", index: number) => marks.find((m) => m.kind === kind && m.index === index);
  const cardIndex = (c: CardReview) => (result.play ?? []).findIndex(([s, card], i) => s === c.seat && card === c.card && Math.floor(i / 4) + 1 === c.trick);
  const after = (m?: { asked: ("hints" | "coach")[] }) =>
    m && <span className="muted"> {m.asked.includes("hints") ? "After a hint." : "After asking the AI coach."}</span>;
  const order: Seat[] = ["N", "E", "S", "W"];
  const seatOfCall = (i: number) => order[(order.indexOf(result.dealer ?? "N") + i) % 4];
  // "Pass after East's Dbl": a call is named by the last call before it that wasn't a pass
  const callPlace = (i: number) => {
    const calls = result.calls ?? [];
    let j = i - 1;
    while (j >= 0 && calls[j] === "P") j--;
    return `${callLabel(calls[i])}${j >= 0 ? ` after ${seatOfCall(j) === me ? "your" : `${nameOf(seatOfCall(j))}'s`} ${callLabel(calls[j])}` : ""}`;
  };
  const myHints = marks
    .filter((m) => m.seat === me && m.asked.includes("hints"))
    .map((m) =>
      m.kind === "call"
        ? result.calls?.[m.index] ? callPlace(m.index) : null
        : result.play?.[m.index] ? `${cardLabel(result.play[m.index][1])} at trick ${Math.floor(m.index / 4) + 1}` : null,
    )
    .filter((x): x is string => !!x);
  // the hand whose cards someone else chose: dummy, or a bot declarer's hand that the person opposite played
  const playedFor = play?.cards.find((c) => c.seat !== c.by)?.seat;
  const dummy = result.contract ? partnerOf(result.contract.declarer) : undefined;
  const c0 = result.contract;
  const contract = c0 ? `${c0.level}${c0.strain === "N" ? "NT" : { S: "♠", H: "♥", D: "♦", C: "♣" }[c0.strain]}` : "";
  // what a costly card cost and the better bet, in the list and again in its trick's pop-up
  const from = (seat: Seat, by: Seat) =>
    seat !== by && <> {seat === dummy ? "from dummy" : `from ${nameOf(seat)}'s hand`}</>;
  const costLine = (c: CardReview) => (
    <>
      {who(c.by)} played <Card card={c.card} />
      {from(c.seat, c.by)}
      {charged(c) > 0 && <> <span className="minus-ink">(−{tricks(charged(c))})</span></>}.
      {charged(c) > 0 && c.later_back && (
        <>
          {" "}{who(c.later_back.by)} gave it back at trick {c.later_back.trick} with <Card card={c.later_back.card} />
          {from(c.later_back.seat, c.later_back.by)}.
        </>
      )}
      {after(markOf("card", cardIndex(c)))}
      {c.given_back && (
        <>
          {" "}{who(c.given_back.by)} gave it straight back with <Card card={c.given_back.card} />
          {from(c.given_back.seat, c.given_back.by)}.
        </>
      )}
      {charged(c) <= 0 ? null : c.odds ? (
        <Verdict c={c} goal={c.odds.goal === "make" ? `makes ${contract}` : `beats ${contract}`} />
      ) : (
        <>
          {" "}Better: {c.best.slice(0, 4).map((b, j) => (
            <span key={b}>
              {j > 0 && ", "}
              <Card card={b} />
            </span>
          ))}
          {c.best.length > 4 && "…"}
          {review?.odds_pending && <div className="odds muted">Working out the odds…</div>}
        </>
      )}
    </>
  );

  // the summary lines
  const mistakes = costly.filter((c) => ours(c.by) && isMistake(c));
  const unlucky = costly.filter((c) => ours(c.by) && c.odds && !isMistake(c));
  const m = mistakes.reduce((a, c) => a + charged(c), 0);
  const u = unlucky.reduce((a, c) => a + charged(c), 0);
  const whyLost = m && u ? `${m} from ${mistakes.length === 1 ? "a mistake" : "mistakes"}, ${u} unlucky`
    : m ? (mistakes.length === 1 ? "a mistake" : `${mistakes.length} mistakes`)
    : u ? "unlucky" : "";
  const second = review?.second?.[me];
  const impsOf = (s: Second) => (
    <b className={s.imps > 0 ? "plus-ink" : s.imps < 0 ? "minus-ink" : "muted"}>
      {signed(s.imps)} {Math.abs(s.imps) === 1 ? "IMP" : "IMPs"}
    </b>
  );
  // a line opens its pull-down and brings it into view
  const openPull = (id: string) => () => {
    const d = pulls.current[id];
    if (!d) return;
    d.open = true;
    d.scrollIntoView({ block: "start", behavior: "smooth" });
  };
  const line = (id: string, label: string, value: React.ReactNode) => (
    <tr key={id} onClick={openPull(id)}>
      <th>{label}</th>
      <td>{value}</td>
      <td className="go" aria-hidden="true">›</td>
    </tr>
  );
  const pull = (id: string, label: string, body: React.ReactNode, note?: React.ReactNode) => (
    <details key={id} className="whats-new review-pull" ref={(el) => { pulls.current[id] = el; }}>
      <summary>
        {label}
        {note != null && <span className="pull-note">{note}</span>}
      </summary>
      <div className="pull-body">{body}</div>
    </details>
  );

  return (
    <section className="review">
      {review && (
        <h3>
          Review <ReviewInfo />
        </h3>
      )}
      <table className="review-lines">
        <tbody>
          {par && (
            <tr>
              <th>Par</th>
              <td>{par}</td>
              <td />
            </tr>
          )}
          {play && line("cards", watching ? "Play" : "Your play", (
            <>
              {lostOurs === 0 ? "No tricks lost" : <>Lost <span className="minus-ink">{tricks(lostOurs)}</span>{whyLost && <span className="muted"> ({whyLost})</span>}</>}
              {gifts > 0 && <>. {watching ? "The other side gave" : "Opponents gave you"} <span className="plus-ink">{gifts}</span></>}.
            </>
          ))}
          {review && line("bidding", "Bidding", offSystem.length === 0 ? "Every call matched the system." : offSystem.length === 1 ? (
            <>
              {offSystem[0].seat === me ? "Your" : `${nameOf(offSystem[0].seat)}'s`} <Call call={offSystem[0].call} /> instead of{" "}
              <Call call={offSystem[0].system_call} /> {bidTag(offSystem[0], review.odds_pending)}
              {thisTime(offSystem[0]) && <span className="muted"> {thisTime(offSystem[0])}</span>}
            </>
          ) : `${offSystem.length} calls left the system.`)}
          {(second || review?.second_pending) && line("second", "Second table", second ? (
            <>
              {impsOf(second)} <span className="muted">(level {second.level}: <SuitText text={contractResult(second.contract, second.tricks)} />)</span>
            </>
          ) : <span className="muted">Playing it again…</span>)}
        </tbody>
      </table>
      {hands}
      <div className="review-pulls">
        {auction && pull("auction", "Auction", auction)}
        {playRecord && pull("play", "Play", playRecord)}
        {play && pull("cards", "Cards that cost a trick", (
          <>
            {result.contract && (
              <p>
                With perfect play (cards face up) {SEAT_NAME[result.contract.declarer]} could take <strong>{play.dd_declarer_tricks}</strong>{" "}
                {play.dd_declarer_tricks === 1 ? "trick" : "tricks"} (took {result.declarer_tricks}).
              </p>
            )}
            <table className="lost-summary">
              <tbody>
                {(["N", "S", "E", "W"] as Seat[])
                  .filter((s) => s !== playedFor)
                  .map((s) => {
                    const mine = costly.filter((c) => c.by === s);
                    const lost = mine.reduce((a, c) => a + charged(c), 0);
                    // in tricks, like the total: "−3 tricks (2 from a mistake, 1 unlucky)"
                    const ms = mine.filter(isMistake);
                    const mt = ms.reduce((a, c) => a + charged(c), 0);
                    const ut = mine.filter((c) => c.odds && !isMistake(c)).reduce((a, c) => a + charged(c), 0);
                    const why = [
                      mt && `${mt} from ${ms.length === 1 ? "a mistake" : `${ms.length} mistakes`}`,
                      ut && `${ut} unlucky`,
                    ].filter(Boolean).join(", ");
                    const declaring = play.cards.some((c) => c.by === s && c.role === "declarer");
                    return (
                      <tr key={s} className={s === me ? "me" : ""}>
                        <td>{who(s)}</td>
                        <td>{declaring ? "declaring" : "defending"}</td>
                        <td className={lost ? "" : "muted"}>
                          {lost === 0 ? "no tricks lost" : ours(s) ? `−${tricks(lost)}` : <span className="plus-ink">gave you {tricks(lost)}</span>}
                          {why && <span className="muted"> ({why})</span>}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
            <label className="small pull-check">
              <input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} /> include bots
            </label>
            {shown.length === 0 ? (
              <p className="muted">None. Every card {everyone ? "at the table" : "your side played"} kept the most tricks possible.</p>
            ) : (
              <ul className="review-list">
                {shown.map((c, i) => (
                  <li key={i} className={c.by === me ? "me" : ""}>
                    {result.play?.length ? (
                      <button className="trick-link" onClick={() => setOpen(c)}>
                        Trick {c.trick}
                      </button>
                    ) : (
                      <span className="muted">Trick {c.trick}</span>
                    )}
                    <span className="muted">:</span> {costLine(c)}
                  </li>
                ))}
              </ul>
            )}
          </>
        ), shown.length ? shown.length : "none")}
        {review && pull("bidding", "Bidding", (
          <>
            {minor > 0 && (
              <label className="small pull-check">
                <input type="checkbox" checked={alternatives} onChange={(e) => setAlternatives(e.target.checked)} /> show {minor} sensible{" "}
                {minor === 1 ? "alternative" : "alternatives"}
              </label>
            )}
            {bids.length === 0 ? (
              <p className="muted">Every call matched the system.</p>
            ) : (
              <ul className="review-list">
                {bids.map((b) => (
                  <li key={b.index} className={b.seat === me ? "me" : ""}>
                    {who(b.seat)} bid <Call call={b.call} />
                    {b.meaning && <span className="muted"> (<SuitText text={b.meaning} />)</span>}. The system bids <Call call={b.system_call} />
                    {b.system_meaning && <span className="muted"> (<SuitText text={b.system_meaning} />)</span>}.{b.minor && <span className="muted"> A sensible alternative.</span>}
                    {after(markOf("call", b.index))}
                    <BidOutcome b={b} me={me} pending={review.odds_pending} />
                  </li>
                ))}
              </ul>
            )}
          </>
        ), offSystem.length ? `${offSystem.length} off the system` : "on the system")}
        {(second || review?.second_pending) && pull("second", "Second table", <SecondTable s={second} pending={review?.second_pending} />,
          second ? impsOf(second) : undefined)}
        {dd && pull("dd", "Tricks with all cards seen", dd)}
      </div>
      {open && <TrickPopup c={open} result={result} me={me} who={who} line={costLine(open)} onClose={() => setOpen(null)} />}
      {help && (help.hints || help.undos || help.coach) ? (
        <p className="muted small">
          You used {listed([
            help.hints ? `${help.hints} ${help.hints === 1 ? "hint" : "hints"}` : "no hints",
            help.undos ? `${help.undos} ${help.undos === 1 ? "undo" : "undos"}` : "",
            help.coach ? `the AI coach on ${help.coach} ${help.coach === 1 ? "turn" : "turns"}` : "",
          ])}{" "}
          on this board.
          {myHints.length > 0 && (
            <>
              {" "}Hints for: <SuitText text={listed(myHints)} />.
            </>
          )}
        </p>
      ) : null}
    </section>
  );
}
