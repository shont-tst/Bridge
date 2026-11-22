import { useEffect, useMemo, useRef, useState } from "react";
import type { Account } from "../account";
import { SUIT_SYMBOL, rankLabel } from "../cards";
import type { Seat } from "../types";
import {
  BASICS, COMPARE, GAMES, READY, STEPS, TIPS, knownSteps, type DealHand, type MiniHand, type Rule, type SetHand, type Step, type TipWhen,
} from "../tutorial/lessons";
import {
  RANKS, SEAT_NAMES, SUIT_ONE, beats, botCard, dealWhere, hcp, legal, next, partner, pickTrump, rank, sameSide,
  sideHasIt, suitOf, target, topTricks, winning, wins, type Hands, type TrickT, type View,
} from "../tutorial/play";
import { useProgress } from "../tutorial/progress";
import { TUTORIAL_DONE_KEY } from "./TutorialTable";
import { HAND_SPREAD, SIZES } from "./TableView";
import Dummy from "./Dummy";
import Fan from "./Fan";
import PlayingCard from "./PlayingCard";
import SuitText from "./SuitText";
import TrickArea from "./TrickArea";
import UndoIcon from "./UndoIcon";

const cardText = (c: string) => `${SUIT_SYMBOL[c[0]]}${rankLabel(c)}`;
const sym = (s: string) => SUIT_SYMBOL[s];
const BOT_DELAY = Number(new URLSearchParams(location.search).get("botDelay") ?? 900);
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

function useSize() {
  const get = () => ({ w: window.innerWidth, h: window.innerHeight });
  const [s, setS] = useState(get);
  useEffect(() => {
    const on = () => setS(get());
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  const wide = s.w >= 700 && s.h >= 560;
  const tiny = !wide && s.h < 700;
  return { wide, tiny, short: wide && s.h < 900 };
}

const BackIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);
const Tick = ({ size = 16 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
);

type Screen = { kind: "games" } | { kind: "intro" } | { kind: "steps" } | { kind: "play"; step: number; hand: number; won: number; of: number } | { kind: "done"; step: number; won: number; of: number };

/** Learn to play: a short course for beginners, played here in the app against simple bots. */
export default function Tutorial({ account, onClose, onTable }: { account: Account; onClose: () => void; onTable: (step: number) => void }) {
  const progress = useProgress(account);
  // back from a table step (6 or 7) that was finished there: show its "done" page
  const [backFrom] = useState(() => {
    try {
      const n = Number(sessionStorage.getItem(TUTORIAL_DONE_KEY));
      sessionStorage.removeItem(TUTORIAL_DONE_KEY);
      return n || null;
    } catch {
      return null;
    }
  });
  const [screen, setScreen] = useState<Screen>(() =>
    backFrom ? { kind: "done", step: backFrom, won: 0, of: 0 } : progress.games === null ? { kind: "games" } : { kind: "steps" },
  );
  useEffect(() => {
    if (backFrom) progress.finish(backFrom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // a step at a real table opens it; the others play here
  const open = (n: number) => (STEPS[n - 1].table ? onTable(n) : setScreen({ kind: "play", step: n, hand: 0, won: 0, of: 0 }));
  const { wide } = useSize();
  const known = knownSteps(progress.games ?? []);
  const nextStep = READY.find((n) => !progress.done.includes(n) && !known.includes(n)) ?? READY.find((n) => !progress.done.includes(n)) ?? null;
  const tipFor = (when: TipWhen) => {
    const t = TIPS.find((t) => t.when === when && (progress.games ?? []).includes(t.game) && !progress.tips.includes(t.text));
    return t?.text ?? null;
  };

  const top = (title = "Learn to play") => (
    <div className="topbar">
      <button className="icon tut-back" aria-label="Back" onClick={screen.kind === "steps" || screen.kind === "games" && progress.games === null ? onClose : () => setScreen({ kind: "steps" })}>
        <BackIcon />
      </button>
      <span className="boardinfo">{title}</span>
      <span style={{ width: 34 }} />
    </div>
  );

  if (screen.kind === "games")
    return (
      <div className={`app tut ${wide ? "wide" : ""}`}>
        {top()}
        <GamesPage
          first={progress.games === null}
          chosen={progress.games ?? []}
          onDone={(g) => {
            const first = progress.games === null;
            progress.setGames(g);
            setScreen({ kind: first ? "intro" : "steps" }); // the first time, how bridge works comes before the steps
          }}
        />
      </div>
    );

  if (screen.kind === "intro") {
    const mine = (progress.games ?? []).filter((g) => COMPARE[g]);
    return (
      <div className={`app tut ${wide ? "wide" : ""}`}>
        {top()}
        <div className="tut-page tut-intro">
          <h2>How bridge works</h2>
          <dl>
            {BASICS.map((b) => (
              <div key={b.head}>
                <dt>{b.head}</dt>
                <dd>{b.text}</dd>
              </div>
            ))}
          </dl>
          {mine.length > 0 && (
            <>
              <h3>From the games you know</h3>
              <ul className="tut-compare">
                {mine.map((g) => (
                  <li key={g}>
                    <SuitText text={COMPARE[g]} />
                  </li>
                ))}
              </ul>
            </>
          )}
          <button className="primary wide-btn" onClick={() => setScreen({ kind: "steps" })}>
            See the steps
          </button>
        </div>
      </div>
    );
  }

  if (screen.kind === "steps")
    return (
      <div className={`app tut ${wide ? "wide" : ""}`}>
        {top()}
        <div className="tut-page">
          <h2>Learn to play</h2>
          {known.length > 0 && (
            <p className="muted">
              You've played {listWords(progress.games ?? [])}, so {known.length === 1 ? `step ${known[0]} is` : `steps ${known.join(" and ")} are`} marked as known.
            </p>
          )}
          <ol className="tut-steps">
            {STEPS.map((s) => {
              const ready = READY.includes(s.n);
              const done = progress.done.includes(s.n);
              const knows = known.includes(s.n);
              const cls = done ? "done" : s.n === nextStep ? "now" : ready ? "" : "later";
              return (
                <li key={s.n} className={cls}>
                  <button className="tut-step" disabled={!ready} onClick={() => open(s.n)}>
                    <span className="n">{done ? <Tick /> : s.n}</span>
                    <span className="t">
                      <b>{s.title}</b>
                      <span>{s.blurb}</span>
                    </span>
                    {!ready ? <span className="tag soon">Coming soon</span> : knows && !done ? <span className="tag">You know this</span> : null}
                  </button>
                </li>
              );
            })}
          </ol>
          {nextStep !== null ? (
            <button className="primary wide-btn" onClick={() => open(nextStep)}>
              {progress.done.length ? "Continue" : "Start"}: {STEPS[nextStep - 1].title}
            </button>
          ) : (
            <p className="muted center-text">You've finished every step. Tap one to play it again.</p>
          )}
          <p className="center-text">
            <button className="link" onClick={() => setScreen({ kind: "intro" })}>
              How bridge works
            </button>
          </p>
          <p className="center-text">
            <button className="link" onClick={() => setScreen({ kind: "games" })}>
              Change the games I've played
            </button>
          </p>
        </div>
      </div>
    );

  const step = STEPS[screen.step - 1];
  if (screen.kind === "done") {
    const following = READY.find((n) => n > step.n && !progress.done.includes(n));
    return (
      <div className={`app tut ${wide ? "wide" : ""}`}>
        {top()}
        <div className="practice-bar">
          <span>
            Step {step.n} of {STEPS.length} · {step.title}
          </span>
        </div>
        <div className="tut-page center-text">
          <div className="tut-badge">
            <Tick size={34} />
          </div>
          <h2>{step.title}: done</h2>
          {screen.of > 0 && <p>You won {screen.won} of {plural(screen.of, "trick")}.</p>}
          <p className="tut-remember">
            <b>One thing to remember:</b> <SuitText text={step.remember} />
          </p>
          {following ? (
            <button className="primary wide-btn" onClick={() => open(following)}>
              Next: {STEPS[following - 1].title}
            </button>
          ) : (
            <>
              {READY.length < STEPS.length && <p className="muted">Steps {READY.length + 1} to {STEPS.length} are coming soon.</p>}
              <button className="primary wide-btn" onClick={() => setScreen({ kind: "steps" })}>
                Back to Learn to play
              </button>
            </>
          )}
          <p>
            <button className="link" onClick={() => open(step.n)}>
              {step.table ? "Play this step again" : "Play these hands again"}
            </button>
          </p>
        </div>
      </div>
    );
  }

  const hands = step.set ?? step.mini ?? step.deal ?? [];
  return (
    <HandPlay
      key={`${step.n}-${screen.hand}-${screen.of}`}
      step={step}
      index={screen.hand}
      tipFor={tipFor}
      sawTip={progress.sawTip}
      onStop={() => setScreen({ kind: "steps" })}
      onNext={(won, of) => {
        const total = { won: screen.won + won, of: screen.of + of };
        if (screen.hand + 1 < hands.length) setScreen({ kind: "play", step: step.n, hand: screen.hand + 1, ...total });
        else {
          progress.finish(step.n);
          setScreen({ kind: "done", step: step.n, ...total });
        }
      }}
    />
  );
}

function listWords(items: string[]): string {
  return items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function GamesPage({ first, chosen, onDone }: { first: boolean; chosen: string[]; onDone: (games: string[]) => void }) {
  const [games, setGames] = useState<string[]>(chosen);
  const [none, setNone] = useState(!first && chosen.length === 0);
  const toggle = (g: string) => {
    setNone(false);
    setGames((old) => (old.includes(g) ? old.filter((x) => x !== g) : [...old, g]));
  };
  return (
    <div className="tut-page">
      {first && (
        <>
          <div className="tut-crest" aria-hidden="true">
            <PlayingCard card="SA" style={{ transform: "rotate(-8deg)" }} />
            <PlayingCard card="HK" style={{ transform: "rotate(8deg)", marginLeft: -10 }} />
          </div>
          <h2>Learn to play bridge</h2>
          <p>Short steps, about 5 minutes each. You'll be playing real hands by step 3.</p>
        </>
      )}
      <p className="tut-ask">
        <b>Which of these have you played?</b>
        <br />
        <span className="muted">Tap all that apply. We'll skip what you already know.</span>
      </p>
      <div className="tut-games">
        {GAMES.map((g) => (
          <button key={g} className={games.includes(g) ? "on" : ""} aria-pressed={games.includes(g)} onClick={() => toggle(g)}>
            {games.includes(g) && <Tick />}
            {g}
          </button>
        ))}
        <button className={none ? "on" : ""} aria-pressed={none} onClick={() => {
            setNone(true);
            setGames([]);
          }}>
          {none && <Tick />}
          None of these
        </button>
      </div>
      <button className="primary wide-btn" onClick={() => onDone(GAMES.filter((g) => games.includes(g)))}>
        {first ? "Start" : "Save"}
      </button>
      {first && <p className="muted center-text small">No account needed. Sign in to keep your progress on all your devices.</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Playing one hand

interface Game {
  hands: Hands;
  trump: string; // "N": no trumps
  declarer: Seat | null; // null on the face-up steps: there's no contract, just tricks
  faceUp: boolean;
  dummyDown: boolean;
  trick: TrickT;
  turn: Seat;
  played: string[];
  ns: number;
  ew: number;
  needed: number | null; // tricks the declaring side needs
  script: Partial<Record<Seat, string[]>>;
  firstMove: boolean; // nobody has played a card yet
  rules: Rule[]; // the lesson's ideas the coach checks for
  southLed: boolean; // South has led to a trick
}

type Phase = "count" | "totals" | "trumps" | "winners" | "play" | "end";

const dummyOf = (g: Game): Seat | null => (g.declarer ? partner(g.declarer) : null);

/** Seats the player plays: South, and dummy too when South is declarer. As dummy, the player plays nothing. */
function controls(g: Game, seat: Seat): boolean {
  if (g.declarer === "N") return false;
  return seat === "S" || (seat === "N" && g.declarer === "S");
}

function viewFor(g: Game, seat: Seat): View {
  const d = dummyOf(g);
  const visible = d && g.dummyDown && d !== seat ? { seat: d, cards: g.hands[d] } : null;
  // declarer and dummy are played as one hand, from declarer's seat of view
  return { seat, hand: g.hands[seat], dummy: visible, played: new Set(g.played), trick: g.trick, trump: g.trump, declarer: g.declarer };
}

function play(g: Game, seat: Seat, card: string): Game {
  const hands = { ...g.hands, [seat]: g.hands[seat].filter((c) => c !== card) };
  const cards = [...g.trick.cards, { seat, card }];
  const trick: TrickT = { leader: g.trick.leader, cards };
  const script = { ...g.script, [seat]: (g.script[seat] ?? []).filter((c) => c !== card) };
  let { ns, ew } = g;
  if (cards.length === 4) {
    trick.winner = winning(cards, g.trump).seat;
    if (trick.winner === "N" || trick.winner === "S") ns++;
    else ew++;
  }
  return {
    ...g, hands, trick, script, ns, ew, played: [...g.played, card], firstMove: false,
    southLed: g.southLed || (seat === "S" && g.trick.cards.length === 0),
    dummyDown: g.dummyDown || (g.declarer !== null && g.played.length === 0), // dummy goes down after the opening lead
    turn: cards.length === 4 ? g.turn : next(seat),
  };
}

function botPlay(g: Game, seat: Seat): string {
  const opts = legal(g.hands[seat], g.trick);
  const scripted = (g.script[seat] ?? []).find((c) => opts.includes(c));
  if (scripted) return scripted;
  // dummy's cards are chosen by declarer, who sees them both
  const who = g.declarer && seat === dummyOf(g) ? g.declarer : seat;
  const v = viewFor(g, who);
  return botCard({ ...v, seat, hand: g.hands[seat], dummy: who !== seat ? { seat: who, cards: g.hands[who] } : v.dummy });
}

/** What a player needs to hear before choosing a card: one short line. */
function coach(g: Game, seat: Seat, step: number): string {
  const spot = lessonSpot(g, seat);
  if (spot) return spot.say;
  const fromDummy = seat === "N" && g.declarer === "S";
  const tr = g.trump;
  if (!g.trick.cards.length) {
    if (fromDummy) return "Lead from dummy this time.";
    if (g.declarer && !sameSide(g.declarer, seat) && g.played.length === 0) return "Your lead. Lead from your longest suit.";
    if (g.declarer && sameSide(g.declarer, seat) && g.played.length <= 4) {
      const have = topTricks(g.hands.S, g.hands.N);
      return `Count your sure winners: you have ${have}, and you need ${g.needed}.`;
    }
    if (g.faceUp && tr !== "N" && step === 2) {
      const theirs = suitOf([...g.hands.E, ...g.hands.W], tr).length;
      const ours = suitOf(g.hands.S, tr).length;
      if (theirs && ours) return `The other side still has ${plural(theirs, "trump")}. Lead trumps to draw ${theirs === 1 ? "it" : "them"}.`;
      if (!theirs) return "The other side has no trumps left, so your winners are safe.";
    }
    return "Your lead. Any card can go first.";
  }
  const led = g.trick.cards[0].card[0];
  const who = SEAT_NAMES[g.trick.cards[0].seat];
  const hand = g.hands[seat];
  if (suitOf(hand, led).length) {
    if (fromDummy) return `Play a ${sym(led)} from dummy.`;
    return `${who} led a ${sym(led)}. You must follow suit.`;
  }
  if (tr !== "N" && suitOf(hand, tr).length)
    return `${fromDummy ? "Dummy has" : "You have"} no ${sym(led)}, so ${fromDummy ? "dummy" : "you"} can ruff with a ${sym(tr)}, or throw away another card.`;
  return `${fromDummy ? "Dummy has" : "You have"} no ${sym(led)}, so play any card. It can't win this trick.`;
}

/** Why a card misses the point of the step, or null when it's fine. The player can play it anyway. */
function tryAgain(g: Game, seat: Seat, card: string): string | null {
  const opts = legal(g.hands[seat], g.trick);
  if (opts.length === 1) return null;
  const spot = lessonSpot(g, seat);
  if (spot) return spot.ok(card) ? null : spot.why(card);
  const t = g.trick;
  const me = seat === "N" && g.declarer === "S" ? "Dummy's" : "Your";
  // opening lead as a defender: from the longest suit
  if (!t.cards.length && g.declarer && !sameSide(g.declarer, seat) && g.played.length === 0) {
    const suits = "SHDC".split("").filter((s) => s !== g.trump);
    const most = Math.max(...suits.map((s) => suitOf(opts, s).length));
    if (g.trump !== card[0] && suitOf(opts, card[0]).length === most) return null;
    const best = suits.find((s) => suitOf(opts, s).length === most)!;
    return `Lead from your longest suit: your ${sym(best)}, with ${most} cards. Its small cards can win tricks later.`;
  }
  if (!t.cards.length) {
    // drawing trumps: don't lead a winner the other side can ruff
    if (!g.faceUp || g.trump === "N" || card[0] === g.trump || !suitOf(g.hands[seat], g.trump).length) return null;
    for (const opp of ["E", "W"] as Seat[]) {
      if (!suitOf(g.hands[opp], card[0]).length && suitOf(g.hands[opp], g.trump).length)
        return `${SEAT_NAMES[opp]} has no ${sym(card[0])} and still has a trump, so ${SEAT_NAMES[opp]} would ruff your ${cardText(card)}. Lead your trumps first.`;
    }
    return null;
  }
  const led = t.cards[0].card[0];
  const best = winning(t.cards, g.trump);
  const last = t.cards.length === 3;
  if (g.faceUp || last) {
    const ours = g.faceUp ? sideHasIt(seat, t, g.hands, g.trump) : last && sameSide(best.seat, seat);
    if (ours) {
      // partner's card already wins: don't throw a winner on it
      const over = beats(card, best.card, led, g.trump) || (card[0] === best.card[0] && rank(card) > rank(best.card));
      const under = opts.filter((c) => !beats(c, best.card, led, g.trump));
      if (over && under.length && rank(card) > Math.min(...under.map(rank)))
        return `${SEAT_NAMES[best.seat]}'s ${cardText(best.card)} already wins this trick for your side. Save your ${cardText(card)} and play a low card.`;
      return null;
    }
    const sure = (c: string) => (g.faceUp ? wins(c, seat, t, g.hands, g.trump) : beats(c, best.card, led, g.trump));
    if (sure(card)) return null;
    const winners = opts.filter(sure).sort((a, b) => (a[0] === g.trump ? 1 : 0) - (b[0] === g.trump ? 1 : 0) || rank(a) - rank(b));
    if (!winners.length) return null;
    const w = winners[0];
    const lost = beats(card, best.card, led, g.trump) ? "Someone still to play can beat that." : `That loses to ${SEAT_NAMES[best.seat]}'s ${cardText(best.card)}.`;
    const why = w[0] === g.trump && led !== g.trump ? `${SUIT_NAMES_CAP[g.trump]} are trumps, so ${me.toLowerCase()} ${cardText(w)} wins.` : `${me} ${cardText(w)} would win${last ? ": you're last to play" : ""}.`;
    return `${lost} ${why}`;
  }
  return null;
}
const SUIT_NAMES_CAP: Record<string, string> = { S: "Spades", H: "Hearts", D: "Diamonds", C: "Clubs" };

function setGame(h: SetHand): Game {
  return {
    hands: { N: [...h.hands.N], E: [...h.hands.E], S: [...h.hands.S], W: [...h.hands.W] },
    trump: h.trump, declarer: null, faceUp: true, dummyDown: false, trick: { leader: h.leader, cards: [] }, turn: h.leader,
    played: [], ns: 0, ew: 0, needed: null, script: h.script ?? {}, firstMove: true, rules: [], southLed: false,
  };
}

function miniGame(m: MiniHand): Game {
  const hands = dealWhere(m.test);
  const nsPts = hcp(hands.N) + hcp(hands.S);
  const declarer: Seat = nsPts > 20 ? (hcp(hands.N) > hcp(hands.S) ? "N" : "S") : hcp(hands.E) > hcp(hands.W) ? "E" : "W";
  return {
    hands, trump: "N", declarer, faceUp: false, dummyDown: false, trick: { leader: next(declarer), cards: [] }, turn: next(declarer),
    played: [], ns: 0, ew: 0, needed: null, script: {}, firstMove: true, rules: [], southLed: false,
  };
}

/** Tricks each card takes from here, with all four hands known, or null when the server can't say. */
async function solverHint(g: Game): Promise<Record<string, number> | null> {
  try {
    const res = await fetch("/api/tutorial/hint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hands: g.hands, trump: g.trump, leader: g.trick.leader, trick: g.trick.cards.map((p) => p.card) }),
    });
    if (!res.ok) return null;
    return (await res.json()).tricks as Record<string, number>;
  } catch {
    return null;
  }
}

/** A lesson on one of its solver-checked deals, picked at random. */
function dealGame(d: DealHand): Game {
  const f = d.deals[Math.floor(Math.random() * d.deals.length)];
  const hands = { N: f.hands.N.split(" "), E: f.hands.E.split(" "), S: f.hands.S.split(" "), W: f.hands.W.split(" ") };
  const leader = next(f.declarer);
  const script: Partial<Record<Seat, string[]>> = {};
  if (d.rules.includes("third") && leader === "N") {
    // North leads low from a long suit where South has an honor, so South can play third hand high
    const s = "SHDC".split("").find((s) => s !== f.trump && suitOf(hands.N, s).length >= 4 && suitOf(hands.S, s).some((c) => "AKQ".includes(c[1])));
    if (s) script.N = [lowest(suitOf(hands.N, s))];
  }
  return {
    hands, trump: f.trump, declarer: f.declarer, faceUp: false, dummyDown: !!d.quiz, trick: { leader, cards: [] }, turn: leader,
    played: [], ns: 0, ew: 0, needed: f.needed, script, firstMove: true, rules: d.rules, southLed: false,
  };
}

const lowest = (cs: string[]) => [...cs].sort((a, b) => rank(a) - rank(b))[0];
const highest = (cs: string[]) => [...cs].sort((a, b) => rank(b) - rank(a))[0];

/** Top cards North and South hold in a suit, counting the cards already played as gone. */
function sureIn(g: Game, s: string): number {
  let n = 0;
  for (let r = RANKS.length - 1; r >= 0; r--) {
    const c = s + RANKS[r];
    if (g.played.includes(c)) continue;
    if (!g.hands.N.includes(c) && !g.hands.S.includes(c)) break;
    n++;
  }
  return n;
}

interface Spot {
  say: string; // the coach line
  ok: (card: string) => boolean;
  why: (card: string) => string; // shown on Not this time
  best?: string; // the card Hint shows
}

/** Where the lesson's idea comes up on this play: what to say, and which cards fit it. */
function lessonSpot(g: Game, seat: Seat): Spot | null {
  const opts = legal(g.hands[seat], g.trick);
  if (opts.length < 2 || !g.declarer) return null;
  const t = g.trick;
  const tr = g.trump;
  const lead = !t.cards.length;
  const led = t.cards[0]?.card[0];
  const ours = sameSide(g.declarer, seat);
  const has = (s: Seat, c: string) => g.hands[s].includes(c);
  for (const rule of g.rules) {
    if (rule === "finesse" && ours) {
      for (const s of "SHDC") {
        if (s === tr || !has("S", s + "A") || !has("S", s + "Q") || has("S", s + "K") || has("N", s + "K") || g.played.includes(s + "K")) continue;
        const north = suitOf(g.hands.N, s);
        if (!north.length) continue;
        const aq = `${sym(s)}A Q`;
        if (lead && seat === "N")
          return {
            say: `Lead a small ${sym(s)} from dummy toward your ${aq}.`,
            ok: (c) => c[0] === s,
            why: () => `Lead a small ${sym(s)} from dummy toward your ${aq}. If East has the ${sym(s)}K, your ${sym(s)}Q will win.`,
            best: lowest(north),
          };
        if (lead && seat === "S")
          return {
            say: `Leave your ${aq} for later: lead toward ${north.length > 1 ? "them" : "it"} from dummy.`,
            ok: (c) => c[0] !== s,
            why: () => `Don't lead ${sym(s)} from your hand. Get to dummy and lead a small ${sym(s)} toward your ${aq}.`,
          };
        if (seat === "S" && t.cards.length === 2 && t.cards[0].seat === "N" && led === s && t.cards[1].card !== s + "K")
          return {
            say: `East played low. Play your ${sym(s)}Q: if East has the ${sym(s)}K, it wins.`,
            ok: (c) => c === s + "Q",
            why: () => `Play the ${sym(s)}Q. If East has the ${sym(s)}K, your ${sym(s)}Q wins, and you still have the ${sym(s)}A.`,
            best: s + "Q",
          };
      }
    }
    if (rule === "ruff" && ours && tr !== "N" && suitOf(g.hands.N, tr).length) {
      if (seat === "N" && led && led !== tr && !suitOf(g.hands.N, led).length && !sameSide(winning(t.cards, tr).seat, "N")) {
        const best = winning(t.cards, tr).card;
        const ruffs = suitOf(opts, tr).filter((c) => beats(c, best, led, tr));
        if (ruffs.length)
          return {
            say: `Dummy has no ${sym(led)}. Ruff it with a ${sym(tr)}.`,
            ok: (c) => ruffs.includes(c),
            why: () => `Dummy has no ${sym(led)}, so ruff with a ${sym(tr)}. That's a loser of yours turned into a trick.`,
            best: lowest(ruffs),
          };
      }
      if (lead && seat === "S") {
        const x = "SHDC".split("").find((s) => {
          const mine = suitOf(g.hands.S, s).length;
          const losers = mine - Math.min(sureIn(g, s), mine);
          return s !== tr && losers > 0 && suitOf(g.hands.N, s).length < mine && losers > suitOf(g.hands.N, s).length;
        });
        if (x && suitOf(g.hands.S, tr).length)
          return {
            say: `Dummy is short in ${sym(x)}. Lead a ${sym(x)} so dummy can ruff your losers.`,
            ok: (c) => c[0] !== tr,
            why: () => `Ruff your ${sym(x)} losers in dummy first. If you lead trumps now, dummy's trumps go too.`,
            best: lowest(suitOf(g.hands.S, x)),
          };
      }
    }
    if (ours || seat !== "S") continue;
    if (rule === "sequence" && lead && g.played.length === 0) {
      for (const s of "SHDC") {
        if (s === tr) continue;
        const rs = suitOf(g.hands.S, s).map((c) => c[1]);
        const top = (["KQJA", "QJTK"] as const).find((q) => rs.includes(q[0]) && rs.includes(q[1]) && rs.includes(q[2]) && !rs.includes(q[3]));
        if (!top) continue;
        const c = s + top[0];
        const honors = `${sym(s)}${rankLabel(s + top[0])} ${rankLabel(s + top[1])} ${rankLabel(s + top[2])}`;
        return {
          say: `Your lead. You have ${honors}: lead the top one.`,
          ok: (x) => x === c,
          why: () => `Lead the ${cardText(c)}, the top of your ${honors}. It pushes out their high cards and keeps the rest of yours safe.`,
          best: c,
        };
      }
    }
    if (rule === "second" && t.cards.length === 1 && sameSide(t.cards[0].seat, g.declarer) && rank(t.cards[0].card) < rank("XJ")) {
      const mine = suitOf(opts, led!);
      if (mine.length >= 2 && mine.some((c) => rank(c) >= rank("XT"))) {
        const low = lowest(mine);
        return {
          say: `${t.cards[0].seat === dummyOf(g) ? "Dummy" : "Declarer"} led a small card, and you play second. Play low.`,
          ok: (c) => c === low || rank(c) < rank("XT"),
          why: (c) => `Second hand low: play a small ${sym(led!)}. Save your ${cardText(c)} to beat one of their high cards.`,
          best: low,
        };
      }
    }
    if (rule === "third" && t.cards.length === 2 && t.cards[0].seat === "N") {
      const mine = suitOf(opts, led!);
      const best = winning(t.cards, tr);
      const top = mine.length >= 2 ? highest(mine) : null;
      const partnerHigh = best.seat === "N" && rank(best.card) >= rank("XT");
      if (top && beats(top, best.card, led!, tr) && !partnerHigh) {
        // touching cards are all the same: play the lowest of them
        const group = [top];
        for (let r = rank(top) - 1; r >= 0; r--) {
          const c = led! + RANKS[r];
          if (mine.includes(c)) group.push(c);
          else if (!g.played.includes(c)) break;
        }
        const play = lowest(group);
        return {
          say: `Partner led, and you play third. Play high: your ${cardText(play)}.`,
          ok: (c) => group.includes(c),
          why: () => `Third hand high: play your ${cardText(play)}. It wins the trick, or makes declarer use a higher card.`,
          best: play,
        };
      }
    }
    if (rule === "return" && lead && !g.southLed && g.trick.leader === "S") {
      const x = g.played[0]?.[0];
      const back = x ? suitOf(opts, x) : [];
      if (back.length && x !== tr)
        return {
          say: `North led ${sym(x)} at the start. Lead one back.`,
          ok: (c) => c[0] === x,
          why: () => `Lead back partner's ${sym(x)}. North led it for a reason.`,
          best: back.length === 2 ? highest(back) : lowest(back),
        };
    }
  }
  return null;
}

function HandPlay({ step, index, onNext, onStop, tipFor, sawTip }: {
  step: Step;
  index: number;
  onNext: (won: number, of: number) => void;
  onStop: () => void;
  tipFor: (when: TipWhen) => string | null;
  sawTip: (text: string) => void;
}) {
  const set = step.set?.[index];
  const mini = step.mini?.[index];
  const dl = step.deal?.[index];
  const lesson = (set ?? mini ?? dl)!;
  const total = (step.set ?? step.mini ?? step.deal ?? []).length;
  const [g, setG] = useState<Game>(() => (set ? setGame(set) : dl ? dealGame(dl) : miniGame(mini!)));
  const [phase, setPhase] = useState<Phase>(set ? "play" : dl ? (dl.quiz ? "winners" : "play") : "count");
  const [winnersOk, setWinnersOk] = useState(false);
  const [history, setHistory] = useState<Game[]>([]);
  const [pending, setPending] = useState<{ seat: Seat; card: string; why: string } | null>(null);
  const [hinted, setHinted] = useState<string | undefined>();
  const [tip, setTip] = useState<string | null>(null);
  const [wrongCount, setWrongCount] = useState<number | null>(null);
  const { wide, tiny, short } = useSize();
  const startedRef = useRef(false);

  const showTip = (when: TipWhen) => {
    const t = tipFor(when);
    if (t) {
      setTip(t);
      sawTip(t);
    }
  };
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    if (index === 0) showTip(step.n === 2 ? "trumps" : "start");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handOver = phase === "play" && g.played.length > 0 && Object.values(g.hands).every((h) => !h.length) && !g.trick.winner;
  useEffect(() => {
    if (handOver) setPhase("end");
  }, [handOver]);

  // bots play, and a finished trick is gathered after a moment
  useEffect(() => {
    if (phase !== "play" || pending) return;
    if (g.trick.winner) {
      const t = setTimeout(() => {
        setG((old) => ({ ...old, trick: { leader: old.trick.winner!, cards: [] }, turn: old.trick.winner! }));
      }, Math.max(BOT_DELAY * 1.6, 60));
      return () => clearTimeout(t);
    }
    if (!g.hands[g.turn].length || controls(g, g.turn)) return;
    const t = setTimeout(() => setG((old) => (old.turn === g.turn && !old.trick.winner ? play(old, old.turn, botPlay(old, old.turn)) : old)), g.firstMove ? BOT_DELAY * 2 : BOT_DELAY);
    return () => clearTimeout(t);
  }, [g, phase, pending]);

  const yourTurn = phase === "play" && !g.trick.winner && controls(g, g.turn) && g.hands[g.turn].length > 0;
  const playable = yourTurn ? legal(g.hands[g.turn], g.trick) : [];

  const commit = (seat: Seat, card: string) => {
    setHistory((h) => [...h, g]);
    setHinted(undefined);
    if (tip) setTip(null);
    if (g.trick.cards.length && card[0] === g.trick.cards[0].card[0] && step.n >= 2) showTip("follow");
    setG(play(g, seat, card));
  };
  const choose = (card: string) => {
    if (!yourTurn) return;
    const why = tryAgain(g, g.turn, card);
    if (why) setPending({ seat: g.turn, card, why });
    else commit(g.turn, card);
  };
  const undo = () => {
    const prev = history[history.length - 1];
    if (!prev) return;
    setHistory((h) => h.slice(0, -1));
    setG(prev);
    setHinted(undefined);
  };
  const hint = async () => {
    if (!yourTurn) return;
    const seat = g.turn;
    let card: string | undefined = lessonSpot(g, seat)?.best;
    if (!card && dl) {
      // a full deal: ask the solver, and of its best cards take the one the bots would, or the lowest
      const tricks = await solverHint(g);
      if (tricks) {
        // the best of the cards the step is happy with
        const fine = playable.filter((c) => c in tricks && !tryAgain(g, seat, c));
        const from = fine.length ? fine : playable.filter((c) => c in tricks);
        const top = Math.max(...from.map((c) => tricks[c]));
        const pool = from.filter((c) => tricks[c] === top).sort((a, b) => rank(a) - rank(b));
        const fromDummy = seat === "N" && g.declarer === "S";
        const v = viewFor(g, fromDummy ? "S" : seat);
        const bot = botCard({ ...v, seat, hand: g.hands[seat], dummy: fromDummy ? { seat: "S", cards: g.hands.S } : v.dummy });
        if (pool.length) card = pool.includes(bot) ? bot : pool[0];
      }
    }
    if (!card && g.faceUp) {
      // the card the step wants: no try-again, the cheapest that does the job
      card = [...playable].sort((a, b) => rank(a) - rank(b)).find((c) => !tryAgain(g, seat, c) && wins(c, seat, g.trick, g.hands, g.trump));
      if (!g.trick.cards.length && g.trump !== "N" && step.n === 2) {
        const tr = suitOf(playable, g.trump).sort((a, b) => rank(b) - rank(a));
        const theirs = suitOf([...g.hands.E, ...g.hands.W], g.trump).length;
        if (tr.length && theirs) card = tr[0];
      }
      card = card ?? [...playable].sort((a, b) => rank(a) - rank(b)).find((c) => !tryAgain(g, seat, c));
    }
    if (!card) {
      const fromDummy = seat === "N" && g.declarer === "S";
      const v = viewFor(g, fromDummy ? "S" : seat);
      card = botCard({ ...v, seat, hand: g.hands[seat], dummy: fromDummy ? { seat: "S", cards: g.hands.S } : v.dummy });
      if (tryAgain(g, seat, card)) card = playable.find((c) => !tryAgain(g, seat, c)) ?? card;
    }
    setHinted(card);
  };

  // minibridge: count, see who plays it, pick trumps
  const points = { N: hcp(g.hands.N), E: hcp(g.hands.E), S: hcp(g.hands.S), W: hcp(g.hands.W) };
  const winners = topTricks(g.hands.S, g.hands.N);
  const winnerChoices = useMemo(() => [...new Set([Math.max(0, winners - 1), winners, winners + 1, winners + 2])].slice(0, 3), [winners]);
  const countChoices = useMemo(() => {
    const p = points.S;
    const set = new Set([p, p + (p % 2 ? 2 : 3), Math.max(0, p - 2)]);
    return [...set].sort((a, b) => a - b);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const begin = (trump: string) => {
    const decl = g.declarer!;
    const pts = sameSide(decl, "N") ? points.N + points.S : points.E + points.W;
    setG((old) => ({ ...old, trump, needed: target(trump, pts) }));
    setPhase("play");
    if (trump === "N") showTip("nt");
  };
  const afterTotals = () => {
    if (g.declarer === "S") setPhase("trumps");
    else begin(pickTrump(g.hands[g.declarer!], g.hands[partner(g.declarer!)]));
  };

  // sizes
  // the table's sizes; only the face-up steps, with all four hands showing, use smaller cards for the others
  const table = wide ? (short ? SIZES.wideShort : SIZES.wide) : SIZES.phone;
  const wh = ([w, h]: number[]) => ({ w, h });
  const mine = wh(table.hand);
  const other = g.faceUp ? (wide ? (short ? { w: 48, h: 67 } : { w: 58, h: 82 }) : tiny ? { w: 30, h: 42 } : { w: 38, h: 54 }) : wh(table.dummy);
  const side = g.faceUp ? (wide ? { w: 46, h: 64 } : tiny ? { w: 24, h: 34 } : { w: 30, h: 42 }) : wh(table.sideDummy);

  const dummy = dummyOf(g);
  const shown = (s: Seat) => g.faceUp || (g.dummyDown && s === dummy) || (s === "S" && g.declarer !== "N") || ((phase === "trumps" || phase === "winners") && s === "N") || (s === "S");
  const playFrom = (s: Seat) => (yourTurn && g.turn === s ? { playable, onPlay: choose, hinted } : {});
  const trumpFor = g.trump === "N" ? "" : g.trump;
  const known = phase !== "count" && phase !== "totals"; // who declares is news until the points are counted
  const label = (s: Seat) => {
    const role = s === "N" ? (dummy === "N" && known ? "Dummy" : "Partner") : s === "S" ? (dummy === "S" && known ? "Dummy" : "") : dummy === s && known ? "Dummy" : "";
    const turn = phase === "play" && g.turn === s && !g.trick.winner ? "turn" : "";
    return (
      <div className={`tut-name ${turn}`}>
        {role && <span className="role">{role}</span>}
        {s === "S" ? "You" : SEAT_NAMES[s]}
        {g.declarer === s && known && <span className="tut-decl">Declarer</span>}
      </div>
    );
  };
  const sideHand = (s: Seat) => (
    <div className={`tut-side ${s === "W" ? "left" : "right"} ${shown(s) ? "" : "away"}`}>
      {label(s)}
      {shown(s) && <Dummy cards={g.hands[s]} trump={trumpFor} w={side.w} h={side.h} layout="side" />}
    </div>
  );
  // hidden hands: backs fanned at the edge of the felt, as at the table
  const edgeFan = (s: Seat, where: "top" | "left" | "right") =>
    !shown(s) && g.hands[s].length > 0 && (
      <div className={`seatfan ${where}`}>
        <Fan cards={g.hands[s].length} w={table.back[0]} h={table.back[1]} spread={30} />
      </div>
    );

  const waitingOn = phase === "play" && !yourTurn && !g.trick.winner && g.hands[g.turn].length ? `${g.declarer && g.turn === dummy ? "Dummy" : SEAT_NAMES[g.turn]} to play.` : null;
  let line: string | null = null;
  if (phase === "play") {
    if (g.firstMove && (set || dl)) line = lesson.intro;
    else if (dl && !yourTurn && g.played.length < 4) line = lesson.intro;
    else if (g.firstMove && !yourTurn) line = g.declarer === "N" ? lesson.intro : null;
    if (!line && yourTurn) line = coach(g, g.turn, step.n);
    if (!line && g.declarer === "N") line = "North is declarer. Watch how North plays your cards.";
  }

  const result = (() => {
    if (phase !== "end") return null;
    if (!g.declarer) return { head: `You won ${g.ns} of ${plural(g.ns + g.ew, "trick")}.`, good: g.ns >= g.ew };
    const ours = sameSide(g.declarer, "S");
    const got = ours ? g.ns : g.ew;
    const short = g.needed! - got;
    if (ours) {
      if (short <= 0) return { head: `Made it: ${got} tricks, you needed ${g.needed}.`, good: true, over: got > g.needed! };
      return { head: `${short === 1 ? "One" : short === 2 ? "Two" : short} short: ${got} tricks, you needed ${g.needed}.`, good: false };
    }
    if (short > 0) return { head: `You beat it: they took ${got} tricks and needed ${g.needed}.`, good: true };
    return { head: `They made it: ${got} tricks, they needed ${g.needed}.`, good: false };
  })();
  useEffect(() => {
    if (result && "over" in result && result.over) showTip("over");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const contract = g.declarer && phase !== "count" && phase !== "totals" && phase !== "trumps" && phase !== "winners"
    ? `${g.trump === "N" ? "No trumps" : `Trumps: ${sym(g.trump)}`} · ${g.declarer === "S" ? "You need" : `${SEAT_NAMES[g.declarer]} needs`} ${g.needed}`
    : g.faceUp
      ? g.trump === "N" ? "No trumps" : `Trumps: ${sym(g.trump)}`
      : null;

  return (
    <div className={`app tut ${wide ? "wide" : ""} ${tiny ? "tiny" : ""}`}>
      <div className="practice-bar tut-bar">
        <span>
          Step {step.n} of {STEPS.length} · {step.title} · Hand {index + 1} of {total}
        </span>
        <button className="small" onClick={onStop}>
          Stop
        </button>
      </div>
      <div className="tut-felt">
        <div className="tut-top">
          {!shown("N") && <div className="tut-topfan">{edgeFan("N", "top")}</div>}
          {label("N")}
          {shown("N") && <Dummy cards={g.hands.N} trump={trumpFor} w={other.w} h={other.h} layout={wide && !g.faceUp ? "columns" : "row"} {...playFrom("N")} />}
        </div>
        <div className="tut-mid">
          {edgeFan("W", "left")}
          {edgeFan("E", "right")}
          {sideHand("W")}
          <div className="tut-trick">
            <TrickArea trick={g.trick.cards.length ? g.trick : null} me="S" />
          </div>
          {sideHand("E")}
        </div>
        {contract && (
          <div className="tut-contract">
            <SuitText text={contract} />
            {g.played.length > 0 && <span className="tut-tricks">You {g.ns} · They {g.ew}</span>}
          </div>
        )}
        {phase === "count" && (
          <div className="tut-coach">
            <div>
              <SuitText text={mini!.intro} />
              <div className="tut-q">How many points do you have?</div>
              <div className="tut-choices">
                {countChoices.map((n) => (
                  <button key={n} className="chip" onClick={() => (n === points.S ? (setWrongCount(null), setPhase("totals")) : setWrongCount(n))}>
                    {n}
                  </button>
                ))}
              </div>
              {wrongCount !== null && <div className="tut-tip">Not {wrongCount}. Add 4 for each ace, 3 for each king, 2 for each queen and 1 for each jack.</div>}
            </div>
          </div>
        )}
        {phase === "totals" && (
          <div className="tut-coach">
            <div>
              <div className="tut-points">
                {(["N", "E", "S", "W"] as Seat[]).map((s) => (
                  <span key={s} className={sameSide(s, g.declarer!) ? "ours" : ""}>
                    {s === "S" ? "You" : SEAT_NAMES[s]} <b>{points[s]}</b>
                  </span>
                ))}
              </div>
              <div>
                {sameSide(g.declarer!, "S")
                  ? `Your side has ${points.N + points.S} points, so you play the hand. ${g.declarer === "S" ? "You have more than North, so you're declarer and North is dummy." : "North has more, so North is declarer and you're dummy."}`
                  : `East and West have ${points.E + points.W} points, so they play the hand. ${SEAT_NAMES[g.declarer!]} is declarer. You defend with North.`}
              </div>
              <button className="primary tut-go" onClick={afterTotals}>
                {g.declarer === "S" ? "See dummy" : "Play"}
              </button>
            </div>
          </div>
        )}
        {phase === "winners" && (
          <div className="tut-coach">
            {!winnersOk ? (
              <div>
                <SuitText text={`${g.trump === "N" ? "No trumps" : `Trumps: ${sym(g.trump)}`}, and you need ${g.needed} tricks. ${lesson.intro}`} />
                <div className="tut-q">How many sure winners do you and dummy have?</div>
                <div className="tut-choices">
                  {winnerChoices.map((n) => (
                    <button key={n} className="chip" onClick={() => (n === winners ? (setWrongCount(null), setWinnersOk(true)) : setWrongCount(n))}>
                      {n}
                    </button>
                  ))}
                </div>
                {wrongCount !== null && (
                  <div className="tut-tip">Not {wrongCount}. In each suit, count the top cards you hold in a row from the ace, but no more than the longer hand has cards.</div>
                )}
              </div>
            ) : (
              <div>
                <div>
                  <b className="your-turn">Right: {winners}. </b>
                  {winners >= g.needed! ? `You need ${g.needed}, so take them as soon as you can.` : `You need ${g.needed}, so you have to find ${plural(g.needed! - winners, "more trick")}.`}
                </div>
                <button className="primary tut-go" onClick={() => {
                    setWrongCount(null);
                    setPhase("play");
                  }}>
                  Play
                </button>
              </div>
            )}
          </div>
        )}
        {phase === "trumps" && (
          <div className="tut-coach">
            <div>
              <SuitText text={trumpAdvice(g)} />
              <div className="tut-choices">
                {["S", "H", "D", "C", "N"].map((s) => (
                  <button key={s} className="chip" onClick={() => begin(s)}>
                    <SuitText text={s === "N" ? "No trumps" : sym(s)} />
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        {phase === "play" && (
          <div className={`tut-coach ${line ? "" : "quiet"}`}>
            <div>
              {line && (
                <>
                  {yourTurn && !g.firstMove && <b className="your-turn">Your turn. </b>}
                  <SuitText text={line} />
                </>
              )}
              {!line && waitingOn}
              {tip && <span className="tut-tip">{tip}</span>}
            </div>
          </div>
        )}
        {phase === "end" && result && (
          <div className="tut-coach end">
            <div>
              <b className={result.good ? "your-turn" : ""}>{result.head}</b>
              <div className="tut-tip">
                <SuitText text={lesson.remember} />
              </div>
              {tip && <span className="tut-tip">{tip}</span>}
              <div className="tut-endbtns">
                <button className="primary" onClick={() => onNext(g.ns, g.ns + g.ew)}>
                  {index + 1 < total ? "Next hand" : "Finish step"}
                </button>
              </div>
            </div>
          </div>
        )}
        {phase === "play" && (
          <div className="tut-chips">
            <button className="chip" disabled={!yourTurn} onClick={hint}>
              Hint
            </button>
            <button className="chip" disabled={!history.length} onClick={undo} aria-label="Undo">
              <UndoIcon /> Undo
            </button>
          </div>
        )}
        <div className="tut-me">
          {g.declarer === "N" || !shown("S") ? (
            <Dummy cards={g.hands.S} trump={trumpFor} w={other.w} h={other.h} layout={wide ? "columns" : "row"} />
          ) : (
            <Fan cards={g.hands.S} w={mine.w} h={mine.h} trump={trumpFor} className="myfan" spread={HAND_SPREAD} {...playFrom("S")} />
          )}
          {label("S")}
        </div>
      </div>
      {pending && (
        <div className="sheet-backdrop" onClick={() => setPending(null)}>
          <div className="sheet tut-again" role="dialog" onClick={(e) => e.stopPropagation()}>
            <div className="sheet-top">
              <h2>Not this time</h2>
              <button className="close" aria-label="Close" onClick={() => setPending(null)}>
                ✕
              </button>
            </div>
            <p>
              <SuitText text={pending.why} />
            </p>
            <div className="sheet-actions tut-endbtns">
              <button onClick={() => {
                  const p = pending;
                  setPending(null);
                  commit(p.seat, p.card);
                }}>
                Play it anyway
              </button>
              <button className="primary" onClick={() => setPending(null)}>
                Try again
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function trumpAdvice(g: Game): string {
  const best = pickTrump(g.hands.S, g.hands.N);
  if (best === "N") return "You and dummy have no suit with 8 cards together. Pick no trumps.";
  const n = suitOf(g.hands.S, best).length + suitOf(g.hands.N, best).length;
  return `You and dummy have ${n} ${SUIT_ONE[best]}s together (${sym(best)}). Pick a trump suit, or no trumps.`;
}
