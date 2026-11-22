import { SEAT_NAME, partnerOf } from "../cards";
import type { RoomState, Seat } from "../types";

/** Pick a seat at a table that already has people at it, or watch. The player across is your partner. */
export default function SeatPicker({ state, send, onClose, onLeave }: {
  state: RoomState;
  send: (msg: object) => void;
  onClose?: () => void; // already seated or watching: just close
  onLeave: () => void;
}) {
  const t = state.table;
  const midBoard = !!t && t.phase !== "done";
  const waitsForNext = midBoard && (state.watching || state.you !== null);
  const who = (s: Seat) =>
    s === state.you ? "You" : state.players[s] ?? (state.waiting?.[s] ? `${state.waiting[s]} (next board)` : null);
  const pick = (s: Seat) => {
    send({ type: "sit", seat: s });
    onClose?.();
  };
  const seat = (s: Seat) => {
    const name = who(s);
    const mine = s === state.you || s === state.pending;
    const taken = !!name && !mine;
    const p = who(partnerOf(s));
    return (
      <button key={s} className={`seat-btn ${s} ${mine ? "mine" : ""}`} disabled={taken || mine} onClick={() => pick(s)}>
        <b>{SEAT_NAME[s]}</b>
        <span>{name ?? (t || state.settings.solo ? "Bot · take this seat" : "Open")}</span>
        {!taken && !mine && <small>Partner: {p ?? `Bot ${SEAT_NAME[partnerOf(s)]}`}</small>}
      </button>
    );
  };
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet seat-picker" onClick={(e) => e.stopPropagation()}>
        <h2>Pick your seat</h2>
        <p className="muted">Partner sits across. Bots fill empty seats.</p>
        <div className="seat-grid">{(["N", "W", "E", "S"] as Seat[]).map(seat)}</div>
        {waitsForNext && <p className="muted small">A board is under way. You'll sit down when it ends, and watch until then.</p>}
        <div className="row">
          {!state.watching && (
            <button
              onClick={() => {
                send({ type: "watch" });
                onClose?.();
              }}
            >
              Just watch
            </button>
          )}
          {onClose && (
            <button className="primary" onClick={onClose}>
              Cancel
            </button>
          )}
          {!onClose && <button onClick={onLeave}>Leave table</button>}
        </div>
      </div>
    </div>
  );
}
