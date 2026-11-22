/** Learn to play steps 6 (Bidding) and 7 (Scoring), played at a real table with bots at level 2. */
import { useState, type ReactElement } from "react";
import { SUIT_SYMBOL, callLabel, contractLabel } from "../cards";
import { BIDDING_HANDS, STEPS } from "../tutorial/lessons";
import type { RoomState, RubberLine, Seat } from "../types";
import SuitText from "./SuitText";

/** The step a finished table step hands back to Learn to play, which opens its "done" page. */
export const TUTORIAL_DONE_KEY = "bridge-tutorial-done";

export function finishTableStep(step: number) {
  try {
    sessionStorage.setItem(TUTORIAL_DONE_KEY, String(step));
  } catch {
    // private browsing: the step just isn't marked done
  }
}

/** Step 6: why a call isn't the cheat sheet's, or null when it is. The player can make it anyway. */
export function callCheck(state: RoomState, call: string): string | null {
  const want = state.tutorial_call;
  if (state.settings.tutorial !== 6 || !want || want === call) return null;
  const meaning = state.table?.call_meanings?.[want]?.text;
  // an opening pass's meaning reads oddly on its own ("No reason to bid further"), so it goes without
  const opening = !state.table?.auction.some((e) => e.call !== "P");
  return `The cheat sheet says ${callLabel(want)} here${meaning && !(want === "P" && opening) ? ` (${meaning})` : ""}.`;
}

const name = (what: string) => what.replace(/^(\d)([SHDCN])(X*)/, (_, l, s, x) => `${l}${SUIT_SYMBOL[s]}${x}`);

/** What each new line on the score pad means, in plain words: one sentence per line. */
function explain(lines: RubberLine[], gameAfter: boolean, we: "NS" | "EW", vulnerable: boolean): string[] {
  const who = (side: string) => (side === we ? "You" : "They");
  const out = lines.map((l) => {
    if (l.where === "below")
      return `${who(l.side)} score ${l.points} below the line for ${name(l.what)}. Only the tricks you bid and make go below, and 100 there wins a game.`;
    if (l.what === "rubber") return `${who(l.side)} get ${l.points} for winning the rubber: ${l.points === 700 ? "two games to none" : "two games to one"}.`;
    const down = l.what.match(/^(\S+) down (\d+)$/);
    if (down)
      return `${who(l.side)} get ${l.points} above the line: ${name(down[1])} went down ${down[2]}. Points above the line don't count toward game.`;
    if (/overtrick/.test(l.what)) return `${who(l.side)} get ${l.points} above the line for ${l.what}. Extra tricks don't count toward game.`;
    if (/honors|aces/.test(l.what)) return `${who(l.side)} get ${l.points} above the line for ${l.what} in one hand.`;
    return `${who(l.side)} get ${l.points} above the line for ${name(l.what)}.`;
  });
  if (!lines.length) out.push("Nobody bid, so nothing goes on the score pad.");
  if (gameAfter) {
    const winner = lines.find((l) => l.where === "below")?.side;
    if (winner)
      out.push(
        `That's a game for ${winner === we ? "you" : "them"}. Both sides start the next game from 0 below the line, and ${winner === we ? "you're" : "they're"} now vulnerable: bonuses are bigger, and going down costs more.`,
      );
  } else if (vulnerable && lines.some((l) => /down/.test(l.what) && l.side !== we)) {
    out.push("You were vulnerable, so going down cost more.");
  }
  return out;
}

interface Quiz {
  q: string;
  options: string[];
  answer: string;
  why: string;
}

function quizFor(f: NonNullable<RoomState["rubber"]>["finished"][number], we: "NS" | "EW"): Quiz[] {
  const us = we === "NS" ? f.NS : f.EW;
  const them = we === "NS" ? f.EW : f.NS;
  const won = f.winner === we;
  const bonus = f.lines?.find((l) => l.what === "rubber")?.points ?? 700;
  const totals = [...new Set([us, us + 100, Math.max(0, us - 100)])].sort((a, b) => a - b).map(String);
  return [
    {
      q: "Who won the rubber?",
      options: ["You", "They"],
      answer: won ? "You" : "They",
      why: `${won ? "You" : "They"} won two games first.`,
    },
    {
      q: "How many points was the rubber bonus?",
      options: ["500", "700"],
      answer: String(bonus),
      why: "700 when the other side has no game, 500 when they have one.",
    },
    {
      q: "How much below the line wins a game?",
      options: ["30", "100", "150"],
      answer: "100",
      why: "100 points below the line is a game, from one hand or from part scores added up.",
    },
    {
      q: "What did your side score in all?",
      options: totals,
      answer: String(us),
      why: `Add everything above and below the line: you ${us}, they ${them}.`,
    },
  ];
}

const TIPS: string[] = [
  "Count your points: A 4, K 3, Q 2, J 1. With fewer than 12, pass.",
  "12 or more points and five ♥ or ♠: open one of that major.",
  "12 or more points and no five-card major: open your longer minor, 1♣ or 1♦.",
  "15 to 17 points and a balanced hand: open 1NT.",
  "Partner opened a major. With three of their suit, raise: to two with 6 to 9 points, to three with 10 to 12.",
];
const TITLES = ["Pass under 12", "Open a major", "Open a minor", "Open 1NT", "Raise partner's major"];

/** The blue bar, the coach line and the step's sheets, shown over the table. */
export function TutorialTable({ state, me, onStop, send }: { state: RoomState; me: Seat; onStop: () => void; send: (msg: object) => void }) {
  const step = state.settings.tutorial!;
  const t = state.table;
  const board = t?.board ?? 1;
  const hand = Math.min(BIDDING_HANDS, Math.max(1, board));
  const [playing, setPlaying] = useState<number | null>(null); // the board the player chose to play out
  const [quiz, setQuiz] = useState<{ at: number; picked: string | null; right: number } | null>(null);
  const [quizDone, setQuizDone] = useState(false);
  const we: "NS" | "EW" = me === "N" || me === "S" ? "NS" : "EW";
  const title = STEPS[step - 1].title;
  const finish = () => {
    finishTableStep(step);
    onStop();
  };

  const bar = (
    <div className="practice-bar">
      <span>
        Step {step} of {STEPS.length} · {title} · {step === 6 ? `Hand ${hand} of ${BIDDING_HANDS}` : `Board ${board}`}
      </span>
      <button className="small" onClick={onStop}>
        Stop
      </button>
    </div>
  );
  if (!t) return bar;

  let line: string | null = null;
  let sheet: ReactElement | null = null;
  const last = hand >= BIDDING_HANDS;

  if (step === 6) {
    const mine = t.auction.filter((e) => e.seat === me).length;
    if (t.phase === "bidding" && mine === 0) line = `${TITLES[hand - 1]}. ${TIPS[hand - 1]}`;
    const over = t.phase !== "bidding";
    if (over && playing !== board && !(t.phase === "done" && t.contract)) {
      sheet = (
        <div className="sheet-backdrop">
          <div className="sheet tut-again" role="dialog">
            <div className="sheet-top">
              <h2>{t.contract ? "The auction is over" : "All four passed"}</h2>
            </div>
            <p>
              <SuitText text={t.contract ? `The contract is ${contractLabel(t.contract)}.` : "Nobody opened, so the hand is thrown in."} />
            </p>
            <p className="muted">
              <SuitText text={TIPS[hand - 1]} />
            </p>
            <div className="sheet-actions tut-endbtns">
              {t.contract && t.phase === "playing" && <button onClick={() => setPlaying(board)}>Play it out</button>}
              {last ? (
                <button className="primary" onClick={finish}>
                  Finish step
                </button>
              ) : (
                <button className="primary" onClick={() => send({ type: t.phase === "done" ? "next_board" : "skip" })}>
                  Next hand
                </button>
              )}
            </div>
          </div>
        </div>
      );
    }
    if (t.phase === "done" && last && t.contract) line = "That's the last bidding hand.";
  }

  let ended: NonNullable<RoomState["rubber"]>["finished"][number] | undefined;
  if (step === 7 && state.rubber) {
    if (board === 1 && t.phase === "bidding") line = "Play one rubber: the first side to win two games wins it. After each hand, see what goes on the score pad.";
    if (t.phase === "done") {
      ended = state.rubber.finished.find((f) => f.board === board);
      const lines = (ended?.lines ?? state.rubber.lines).filter((l) => l.board === board);
      const ends = ended?.game_ends ?? state.rubber.game_ends;
      const all = ended?.lines ?? state.rubber.lines;
      const start = all.findIndex((l) => l.board === board);
      const gameAfter = start >= 0 && ends.includes(start + lines.length);
      const vul = t.vulnerability === "Both" || t.vulnerability === we;
      line = explain(lines, gameAfter, we, vul).join(" ");
    }
  }
  const finishedRubber = step === 7 && !!ended;
  const qs = ended ? quizFor(ended, we) : [];

  if (quiz && qs.length) {
    const q = qs[quiz.at];
    const pick = (o: string) => setQuiz({ ...quiz, picked: o, right: quiz.right + (o === q.answer ? 1 : 0) });
    sheet = (
      <div className="sheet-backdrop">
        <div className="sheet tut-again" role="dialog">
          <div className="sheet-top">
            <h2>
              Score pad quiz · {quiz.at + 1} of {qs.length}
            </h2>
          </div>
          <p>
            <b>{q.q}</b>
          </p>
          <div className="tut-choices">
            {q.options.map((o) => (
              <button
                key={o}
                className={`chip ${quiz.picked && o === q.answer ? "right" : quiz.picked === o ? "wrong" : ""}`}
                disabled={!!quiz.picked}
                onClick={() => pick(o)}
              >
                {o}
              </button>
            ))}
          </div>
          {quiz.picked && <p className="muted">{quiz.picked === q.answer ? "Right. " : "Not quite. "}{q.why}</p>}
          <div className="sheet-actions tut-endbtns">
            {quiz.picked &&
              (quiz.at + 1 < qs.length ? (
                <button className="primary" onClick={() => setQuiz({ at: quiz.at + 1, picked: null, right: quiz.right })}>
                  Next question
                </button>
              ) : (
                <button className="primary" onClick={() => { setQuiz(null); setQuizDone(true); }}>
                  Done
                </button>
              ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      {bar}
      {(line || finishedRubber || (step === 6 && t.phase === "done" && last)) && (
        <div className="tut-tablecoach">
          {line && <SuitText text={line} />}
          {finishedRubber && !quizDone && (
            <button className="chip" onClick={() => setQuiz({ at: 0, picked: null, right: 0 })}>
              Take the quiz
            </button>
          )}
          {((finishedRubber && quizDone) || (step === 6 && t.phase === "done" && last)) && (
            <button className="chip gold" onClick={finish}>
              Finish step
            </button>
          )}
        </div>
      )}
      {sheet}
    </>
  );
}
