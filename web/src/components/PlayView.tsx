import { useState } from "react";
import { SEAT_NAME, cardLabel, isRed } from "../cards";
import type { CardWhy as Why, Contract, Seat } from "../types";
import CardWhy from "./CardWhy";
import SuitText from "./SuitText";

const COLS: Seat[] = ["W", "N", "E", "S"];

/** The play, trick by trick, after the board: tap a bot's card and its pop-up opens, saying how it picked it. The card that led each trick
 * is underlined. */
export default function PlayView({ play, whys, dummy, contract, room, board }: {
  play: [Seat, string][];
  whys: Record<string, Why>;
  dummy?: Seat;
  contract: Contract | null;
  room: string;
  board: number;
}) {
  const [open, setOpen] = useState<{ card: string; seat: Seat } | null>(null);
  const tricks: [Seat, string][][] = [];
  for (let i = 0; i < play.length; i += 4) tricks.push(play.slice(i, i + 4));
  const why = open ? whys[open.card] : undefined;
  return (
    <div className="auction play-view">
      <table>
        <thead>
          <tr>
            <th />
            {COLS.map((s) => (
              <th key={s}>{SEAT_NAME[s]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tricks.map((t, i) => (
            <tr key={i}>
              <td className="trick-no">{i + 1}</td>
              {COLS.map((s) => {
                const at = t.findIndex(([seat]) => seat === s);
                if (at < 0) return <td key={s} />;
                const card = t[at][1];
                return (
                  <td key={s}>
                    <button
                      className={`call ${isRed(card[0]) ? "red" : ""} ${at === 0 ? "lead" : ""} ${open?.card === card ? "selected" : ""}`}
                      disabled={!whys[card]}
                      onClick={() => setOpen({ card, seat: s })}
                    >
                      <SuitText text={cardLabel(card)} />
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {open && why && (
        <CardWhy card={open.card} seat={open.seat} why={why} dummy={dummy} contract={contract} room={room} board={board} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}
