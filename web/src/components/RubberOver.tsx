import type { RubberState, Seat } from "../types";
import RubberPad from "./RubberPad";

type Finished = RubberState["finished"][number];

/** The end of a rubber: who won, the final pad, and whether to play another rubber or leave the table. */
export default function RubberOver({ rubber, me, watching, onKeepPlaying, canKeepPlaying, onQuit, onLookBack }: {
  rubber: Finished;
  me: Seat;
  watching?: boolean; // shown for North–South, with no choice to make
  onKeepPlaying?: () => void;
  canKeepPlaying?: boolean;
  onQuit: () => void;
  onLookBack: () => void; // close this and go back to the last board's review
}) {
  const we = me === "N" || me === "S" ? "NS" : "EW";
  const won = rubber.winner === we;
  const games = rubber.games ? `${rubber.games[rubber.winner]} games to ${rubber.games[rubber.winner === "NS" ? "EW" : "NS"]}` : null;
  const by = Math.abs(rubber.NS - rubber.EW);
  const title = watching
    ? `${rubber.winner === "NS" ? "North–South" : "East–West"} won the rubber`
    : won ? "You won the rubber" : "You lost the rubber";
  return (
    <div className="sheet-backdrop" onClick={onLookBack}>
      <div className="sheet scoresheet rubber-over" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        <p className="muted">
          {games ? `${games}, ` : ""}by {by} points{watching ? ` (North–South ${rubber.NS}, East–West ${rubber.EW})` : ""}
        </p>
        {rubber.lines && rubber.game_ends && <RubberPad lines={rubber.lines} gameEnds={rubber.game_ends} we={watching ? "NS" : we} finished />}
        {onKeepPlaying ? (
          <div className="result-actions">
            <button onClick={onQuit}>Quit</button>
            <button className="primary" onClick={onKeepPlaying} disabled={!canKeepPlaying}>
              Keep playing
            </button>
          </div>
        ) : null}
        <button className="link" onClick={onLookBack}>
          Back to the review
        </button>
      </div>
    </div>
  );
}
