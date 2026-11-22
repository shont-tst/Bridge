import { contractLabel, signed } from "../cards";
import type { BoardResult, RubberState, Seat } from "../types";
import RubberPad from "./RubberPad";
import SuitText from "./SuitText";

/**
 * Rubber scoring, at the end of a board: the board's result and the score pad first, with the way on from there.
 * The board that ends the rubber says who won it and shows the finished pad.
 */
export default function BoardScore({ result, rubber, me, onReview, onNext, canNext, nextLabel, onQuit }: {
  result: BoardResult;
  rubber: RubberState;
  me: Seat;
  onReview: () => void;
  onNext: () => void;
  canNext: boolean;
  nextLabel: string;
  onQuit: () => void;
}) {
  const we = me === "N" || me === "S" ? "NS" : "EW";
  const they = we === "NS" ? "EW" : "NS";
  const mine = we === "NS" ? result.score_ns : -result.score_ns;
  const c = result.contract;
  const made = c ? result.declarer_tricks - (c.level + 6) : 0;
  const ended = rubber.finished.find((f) => f.board === result.board);
  const games = ended?.games ? `${ended.games[ended.winner]} games to ${ended.games[ended.winner === "NS" ? "EW" : "NS"]}, ` : "";
  return (
    <div className="result board-score">
      <h2>{ended ? (ended.winner === we ? "You won the rubber" : "You lost the rubber") : `Board ${result.board}`}</h2>
      {ended && <p className="muted">{games}by {Math.abs(ended.NS - ended.EW)} points</p>}
      <div className="big">
        <SuitText text={contractLabel(c)} />
        {c && <span> {made === 0 ? "=" : signed(made)}</span>}
        <span className={`score ${mine >= 0 ? "plus" : "minus"}`}> {signed(mine)} for you</span>
      </div>
      {ended?.lines && ended.game_ends ? (
        <RubberPad lines={ended.lines} gameEnds={ended.game_ends} we={we} finished />
      ) : (
        <>
          <p className="muted">
            Rubber {rubber.number} · games: we {rubber.games[we]}, they {rubber.games[they]}
          </p>
          <RubberPad lines={rubber.lines} gameEnds={rubber.game_ends} we={we} />
        </>
      )}
      <div className="result-actions">
        <button onClick={onQuit}>Quit</button>
        <button onClick={onReview}>Review board</button>
        <button className="primary" onClick={onNext} disabled={!canNext}>
          {nextLabel}
        </button>
      </div>
    </div>
  );
}
