import { useState } from "react";
import { SEAT_NAME, callLabel, isRed } from "../cards";
import type { AuctionEntry, Seat } from "../types";
import BidWhy from "./BidWhy";
import SuitText from "./SuitText";

const COLS: Seat[] = ["W", "N", "E", "S"];

/** The auction grid; tap any call to see what it means in the system. */
export default function AuctionView({ auction, dealer, turn, room, board }: {
  auction: AuctionEntry[];
  dealer: Seat;
  turn: Seat | null;
  room: string;
  board: number;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const pad = COLS.indexOf(dealer);
  const cells: (AuctionEntry | null | "?")[] = [...Array(pad).fill(null), ...auction];
  if (turn) cells.push("?");
  const rows: (AuctionEntry | null | "?")[][] = [];
  for (let i = 0; i < cells.length; i += 4) rows.push(cells.slice(i, i + 4));
  const sel = open !== null ? auction[open] : null;

  return (
    <div className="auction">
      <table>
        <thead>
          <tr>
            {COLS.map((s) => (
              <th key={s}>{SEAT_NAME[s]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((e, j) => {
                if (e === null) return <td key={j} />;
                if (e === "?") return <td key={j} className="pending">?</td>;
                const idx = i * 4 + j - pad;
                const strain = e.call.length === 2 ? e.call[1] : "";
                return (
                  <td key={j}>
                    <button className={`call ${isRed(strain) ? "red" : ""} ${e.meaning.alert ? "alert" : ""} ${open === idx ? "selected" : ""}`} onClick={() => setOpen(open === idx && !e.why ? null : idx)}>
                      <SuitText text={callLabel(e.call)} />
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {/* a bot's call opens its pop-up straight away; anyone else's shows its meaning here */}
      {sel?.why && <BidWhy entry={sel} index={open!} room={room} board={board} onClose={() => setOpen(null)} />}
      {sel && !sel.why && (
        <div className="explanation" onClick={() => setOpen(null)}>
          <strong>
            {SEAT_NAME[sel.seat]}: <SuitText text={callLabel(sel.call)} />
          </strong>{" "}
          {sel.meaning.alert && <span className="badge">alert</span>}
          {sel.meaning.forcing && <span className="badge">forcing</span>}
          <div>
            <SuitText text={sel.meaning.text} />
          </div>
          {sel.meaning.hcp && (
            <div className="muted">
              HCP {sel.meaning.hcp[0]}–{sel.meaning.hcp[1]}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
