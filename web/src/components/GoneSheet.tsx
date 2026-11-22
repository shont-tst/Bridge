import type { Gone, Seat } from "../types";

/** Someone at the table tapped Leave, or closed the app 3 minutes ago: play on with a bot in their seat, or wait.
 * They get their seat back when they return. */
export default function GoneSheet({ seat, gone, onBot, onWait }: {
  seat: Seat;
  gone: Gone;
  onBot: (seat: Seat) => void;
  onWait: () => void;
}) {
  return (
    <div className="sheet-backdrop">
      <div className="sheet gone-sheet" role="dialog" aria-label={`${gone.name} is away`}>
        <h2>{gone.left ? `${gone.name} left the table` : `${gone.name} is away`}</h2>
        <p>{gone.left ? "" : "Away 3 minutes. "}{gone.name} gets the seat back on returning.</p>
        <div className="result-actions">
          <button onClick={onWait}>Wait</button>
          <button className="primary" onClick={() => onBot(seat)}>
            Play on with a bot
          </button>
        </div>
      </div>
    </div>
  );
}
