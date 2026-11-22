import { callLabel, isRed } from "../cards";
import type { AuctionEntry, Seat } from "../types";
import SuitText from "./SuitText";

/** One player's calls laid on the table in front of their hand, latest ringed. Tap a call to see its meaning. */
export default function BidTiles({ seat, auction, where, open, onOpen }: {
  seat: Seat;
  auction: AuctionEntry[];
  where: "top" | "left" | "right" | "bottom";
  open: number | null;
  onOpen: (index: number | null) => void;
}) {
  const last = auction.length - 1;
  const tile = (call: string) =>
    `btile ${call === "P" ? "pass" : call === "X" ? "dbl" : call === "XX" ? "rdbl" : isRed(call[1]) ? "red" : ""}`;
  return (
    <div className={`bids ${where}`}>
      {auction.map((e, i) =>
        e.seat !== seat ? null : (
          <button
            key={i}
            className={`${tile(e.call)} ${i === last ? "last" : ""} ${open === i ? "open" : ""} ${e.meaning.alert ? "alert" : ""}`}
            onClick={() => onOpen(open === i ? null : i)}
          >
            <SuitText text={callLabel(e.call)} />
          </button>
        ),
      )}
    </div>
  );
}
