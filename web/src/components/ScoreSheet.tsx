import { SUIT_SYMBOL, signed } from "../cards";
import type { RoomState, Seat } from "../types";
import RubberPad from "./RubberPad";
import SuitText from "./SuitText";


/**
 * The score so far. Duplicate: one row per board with a running total.
 * Rubber: the We/They score pad for this rubber, and the totals of earlier ones.
 */
export default function ScoreSheet({ state, me, onClose }: { state: RoomState; me: Seat; onClose: () => void }) {
  const we = me === "N" || me === "S" ? "NS" : "EW";
  const they = we === "NS" ? "EW" : "NS";
  const r = state.rubber;

  let running = 0;
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet scoresheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>Score</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {r ? (
          <>
            <p className="muted">
              Rubber {r.number} · games: we {r.games[we]}, they {r.games[they]}
              {r.vulnerability !== "None" && ` · vulnerable: ${r.vulnerability === "Both" ? "both sides" : r.vulnerability === we ? "your side" : "their side"}`}
            </p>
            <RubberPad lines={r.lines} gameEnds={r.game_ends} we={we} />
            {r.finished.length > 0 && (
              <>
                <h3>Earlier rubbers</h3>
                <ul className="rubbers">
                  {r.finished.map((f) => (
                    <li key={f.number}>
                      Rubber {f.number}: we {f[we]}, they {f[they]} · <b>{f.winner === we ? `we won by ${f[we] - f[they]}` : `they won by ${f[they] - f[we]}`}</b>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : (
          <table className="boards">
            <thead>
              <tr>
                <th>Board</th>
                <th>Contract</th>
                <th>Tricks</th>
                <th>You</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {state.history.map((h) => {
                const mine = (we === "NS" ? 1 : -1) * h.score_ns;
                running += mine;
                return (
                  <tr key={h.board}>
                    <td>{h.board}</td>
                    <td>
                      <SuitText text={h.contract ? `${h.contract.level}${SUIT_SYMBOL[h.contract.strain]}${"X".repeat(Math.min(Math.max(h.contract.doubled, 0), 2))} ${h.contract.declarer}` : "Passed"} />
                    </td>
                    <td>{h.contract ? h.tricks : "–"}</td>
                    <td className={mine < 0 ? "minus-ink" : ""}>{signed(mine)}</td>
                    <td>{signed(running)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="muted small">
          {r
            ? "Below the line counts toward game (100). Two games win the rubber."
            : "Each board is scored by itself. Change it in the Menu."}
        </p>
      </div>
    </div>
  );
}
