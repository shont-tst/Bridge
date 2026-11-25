import { callLabel, cardLabel } from "../cards";
import type { PuzzleAnswer } from "../types";
import SuitText from "./SuitText";

const T = (text: string) => <SuitText text={text} />;
const tricksOf = (n: number) => `${n} ${n === 1 ? "trick" : "tricks"}`;

/** What happens to the puzzle now: it comes back in 3 days unless it has been right twice. */
function after(a: PuzzleAnswer): string {
  if (a.removed) return "Removed: it won't come back.";
  if (a.retry) return "Only your first try counts. It comes back in 3 days.";
  if (a.retired) return "Right twice: this one's done.";
  if (a.right) return "It comes back in 3 days. Get it right once more and it's done.";
  return "This one comes back in 3 days. Get it right twice and it's done.";
}

/** A card puzzle: the better bet on the odds, and what each card takes as the cards lay. */
function CardAnswer({ a, fromDummy }: { a: PuzzleAnswer; fromDummy: boolean }) {
  const better = a.better!;
  const other = a.right ? a.original! : a.card!; // the card set against the answer
  const pct = a.pct ?? {};
  const where = fromDummy ? " from dummy" : "";
  const target = a.tricks != null ? `takes ${tricksOf(a.tricks)}` : a.goal === "beat" ? "beats the contract" : "makes the contract";
  const them = a.tricks != null ? "takes them" : a.goal === "beat" ? "beats it" : "makes it";
  const dd = a.dd ?? {};
  return (
    <>
      <p>
        {a.right ? (
          <>At the table you played {T(cardLabel(a.original!))}{where}.</>
        ) : (
          <>
            <span className="tag mistake">Mistake</span> You played {T(cardLabel(a.card!))}{where}.
          </>
        )}
      </p>
      {better !== other && pct[better] != null && pct[other] != null && (
        <p>
          {T(cardLabel(better))} {target} {pct[better]}% of the time. {T(cardLabel(other))} {them} {pct[other]}% of the time.
        </p>
      )}
      {better !== other && dd[better] != null && dd[other] != null && (
        <p>
          {dd[better] === dd[other] ? (
            <>As the cards lay, both take {tricksOf(dd[better])}.</>
          ) : (
            <>
              As the cards lay, {T(cardLabel(other))} takes {tricksOf(dd[other])} and {T(cardLabel(better))} takes {dd[better]}.
            </>
          )}
        </p>
      )}
    </>
  );
}

/** A bidding puzzle: the system's call, and what the call made at the table costs. */
function CallAnswer({ a }: { a: PuzzleAnswer }) {
  const meant = (m?: string | null) => (m ? <span className="muted"> ({T(m)})</span> : null);
  const cost = a.cost != null && a.cost > 0 ? a.cost : null;
  const costs = cost && (a.average ? `costs ${cost} points on average on deals like this one` : `cost ${cost} points on this deal`);
  return (
    <>
      {a.right ? (
        <p>
          {T(callLabel(a.system_call!))}
          {meant(a.system_meaning)}.
        </p>
      ) : (
        <>
          <p>
            <span className="tag mistake">Cost</span> You bid {T(callLabel(a.call!))}
            {meant(a.meaning)}.
          </p>
          <p>
            The system bids {T(callLabel(a.system_call!))}
            {meant(a.system_meaning)}.
          </p>
        </>
      )}
      {costs && (
        <p>
          {a.right || a.call !== a.original ? (
            <>At the table you bid {T(callLabel(a.original!))}, which {costs}.</>
          ) : (
            <>{T(callLabel(a.call!))} {costs}.</>
          )}
        </p>
      )}
    </>
  );
}

/** The answer to a Your mistakes puzzle, over the table: right or the better choice, why, and what next. */
export default function PuzzleSheet({ answer, last, fromDummy, onNext, onRetry, onRemove, onPlayOn, onAgain, onBoard, onClose }: {
  answer: PuzzleAnswer;
  last: boolean; // the last puzzle waiting: Done instead of Next
  fromDummy: boolean;
  onNext: () => void;
  onRetry: () => void; // after a wrong answer: the same spot again
  onRemove: () => void; // after a wrong answer: Don't show this again (the player disagrees it was a mistake)
  onPlayOn: () => void;
  onAgain: () => void;
  onBoard?: () => void;
  onClose: () => void;
}) {
  const a = answer;
  const shown = a.kind === "card" ? cardLabel(a.right ? a.card! : a.better!) : callLabel(a.right ? a.call! : a.system_call!);
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet puzzle-sheet" role="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>
            {a.right ? "Right" : "Better"}: <SuitText text={shown} />
          </h2>
          <button className="close" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        {a.kind === "card" ? <CardAnswer a={a} fromDummy={fromDummy} /> : <CallAnswer a={a} />}
        <p className="muted">{after(a)}</p>
        <div className="puzzle-actions">
          {a.right ? (
            <button className="primary" onClick={onNext}>
              {last ? "Done" : "Next"}
            </button>
          ) : (
            <div className="row">
              <button className="primary" onClick={onRetry}>
                Try again
              </button>
              <button onClick={onNext}>{last ? "Done" : "Next"}</button>
            </div>
          )}
          <div className="puzzle-links">
            <span>
              {a.kind === "card" && (
                <button className="link" onClick={onPlayOn}>
                  Play on from here
                </button>
              )}
              <button className="link" onClick={onAgain}>
                Play this deal again
              </button>
            </span>
            <span>
              {onBoard && (
                <button className="link" onClick={onBoard}>
                  See the whole board
                </button>
              )}
              {!a.right && !a.removed && (
                <button className="link quiet" onClick={onRemove}>
                  Don't show this again
                </button>
              )}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
