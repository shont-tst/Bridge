import type { ReactNode } from "react";
import { SEAT_NAME, compass, contractLabel, isRed, parLabel, signed } from "../cards";
import Suit from "./Suit";
import type { BoardResult, Seat } from "../types";
import Hand from "./Hand";
import ReviewPanel from "./ReviewPanel";
import SuitText from "./SuitText";
import UndoIcon from "./UndoIcon";

const STRAINS = ["N", "S", "H", "D", "C"];

/** ", counting your 60 part score" and the like: what par at rubber took into account. */
function partNote(ours: number, theirs: number, watching?: boolean): string {
  const we = watching ? "North–South's" : "your";
  const they = watching ? "East–West's" : "their";
  if (ours && theirs) return `, counting the part scores (${we} ${ours}, ${they} ${theirs})`;
  if (ours) return `, counting ${we} ${ours} part score`;
  if (theirs) return `, counting ${they} ${theirs} part score`;
  return "";
}

/** How the board compares with par, counted the same way (a game worth its bonus now, as par counts it). */
function parVerdict(diff: number, watching?: boolean): string {
  if (diff === 0) return watching ? "On par." : "You made par.";
  return `${Math.abs(diff)} ${diff > 0 ? "above" : "below"} par.`;
}

export default function ResultPanel({ result, me, nameOf, onNext, canNext, nextLabel, onScore, onUndo, help, title, watching, auction, play, onReplay }: {
  result: BoardResult;
  me: Seat;
  nameOf: (s: Seat) => string;
  onNext?: () => void; // none when looking back at a saved board
  canNext?: boolean;
  nextLabel?: string; // "Waiting for Bob" once you've tapped it
  onScore?: () => void; // rubber scoring: back to the score pad
  onUndo?: () => void; // take back the last card and play the end again
  help?: { hints?: number; undos?: number; coach?: number };
  title?: string;
  watching?: boolean; // the score is shown for North–South
  auction?: ReactNode; // at the table: the auction, where a bot's call can be tapped for why it bid that
  play?: ReactNode; // at the table: the play, where a bot's card can be tapped for how it picked it
  onReplay?: (from: number) => void; // play the deal again, after this many calls and cards (0: from the start)
}) {
  const mine = me === "N" || me === "S" ? result.score_ns : -result.score_ns;
  const c = result.contract;
  const made = c ? result.declarer_tricks - (c.level + 6) : 0;
  const dd = result.dd;
  const sign = me === "N" || me === "S" ? 1 : -1;
  const rubber = dd?.rubber; // rubber scoring: par counts the part scores below the line
  const parMine = sign * (rubber ? rubber.par_score_ns : dd?.par_score_ns ?? 0);
  const parCodes = rubber ? rubber.par_contracts : dd?.par_contracts;
  const ours = rubber ? (sign > 0 ? rubber.below.NS : rubber.below.EW) : 0;
  const theirs = rubber ? (sign > 0 ? rubber.below.EW : rubber.below.NS) : 0;
  const whose = watching ? `for ${me === "N" || me === "S" ? "North–South" : "East–West"}` : "for you";
  const at = compass(me); // the hands laid out as at the table, with you at the bottom
  return (
    <div className="result">
      <h2>{title ?? `Board ${result.board}`}</h2>
      <div className="big">
        <SuitText text={contractLabel(c)} />
        {c && <span> {made === 0 ? "=" : signed(made)}</span>}
      </div>
      <div className={`score ${mine >= 0 ? "plus" : "minus"}`}>
        {signed(mine)} {watching ? `for ${me === "N" || me === "S" ? "North–South" : "East–West"}` : "for you"}
      </div>
      {result.claimed && (
        <div className="muted">
          {nameOf(result.claimed)} claimed{" "}
          {result.claimed_tricks === 1 ? "the last trick." : result.claimed_tricks ? `the last ${result.claimed_tricks} tricks.` : "the rest of the tricks."}
        </div>
      )}
      <ReviewPanel
        result={result}
        me={me}
        nameOf={nameOf}
        help={help}
        watching={watching}
        par={rubber ? (
          // rubber: par in words, with how this board compares, both counting a game as par does and the part
          // scores below the line towards it
          <>
            {parCodes?.length ? <SuitText text={parLabel(parCodes)} /> : "Pass it out"}
            {partNote(ours, theirs, watching)}. <b>{parVerdict(sign * rubber.score_ns - parMine, watching)}</b>
          </>
        ) : dd?.par_score_ns !== undefined ? (
          <>
            {signed(parMine)} {whose}
            {parCodes?.length ? <SuitText text={` (${parLabel(parCodes)})`} /> : ""}
          </>
        ) : undefined}
        hands={
          <div className="all-hands">
            {(["top", "left", "right", "bottom"] as const).map((where) => at[where]).map((s, i) => (
              <div key={s} className={`at-${["top", "left", "right", "bottom"][i]}`}>
                <div className="seat-label">{SEAT_NAME[s]}</div>
                <Hand cards={result.hands[s].split(".").flatMap((p, i) => [...p].map((r) => "SHDC"[i] + r))} compact />
              </div>
            ))}
          </div>
        }
        auction={auction}
        play={play}
        onReplay={watching ? undefined : onReplay}
        dd={dd?.tricks && (
          <>
            <p className="muted small dd-help">
              How many tricks each player would take as declarer in each suit, if everyone played perfectly with all the cards face up.
              {c && <SuitText text={` The contract played, ${contractLabel(c).replace(/ by .*/, "")} by ${SEAT_NAME[c.declarer]}, is ringed: it needed ${c.level + 6}.`} />}
            </p>
            <table className="dd">
              <thead>
                <tr>
                  <th>Declarer</th>
                  {STRAINS.map((s) => (
                    <th key={s} className={`s-${s} ${isRed(s) ? "red" : ""}`}>
                      <Suit s={s} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(["N", "S", "E", "W"] as Seat[]).map((seat) => (
                  <tr key={seat}>
                    <td>{SEAT_NAME[seat]}</td>
                    {STRAINS.map((s) => (
                      <td key={s} className={c && c.declarer === seat && c.strain === s ? "played" : ""}>
                        {dd.tricks![s][seat]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      />
      {onNext && <div className="result-actions">
        {onScore && <button onClick={onScore}>Score</button>}
        <button className="primary" onClick={onNext} disabled={!canNext}>
          {nextLabel ?? "Next board"}
        </button>
        {onUndo && (
          <button className="undo" onClick={onUndo} aria-label="Undo the last card" title="Undo">
            <UndoIcon />
            Undo
          </button>
        )}
      </div>}
    </div>
  );
}
