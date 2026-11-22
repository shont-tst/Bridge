import { useEffect, useRef, useState, type ReactNode } from "react";
import { callLabel, isRed } from "../cards";
import Suit from "./Suit";
import type { Meaning } from "../types";
import SuitText from "./SuitText";

const STRAINS = ["N", "S", "H", "D", "C"]; // left to right, so 1♣ sits on the right
const RANK: Record<string, number> = { C: 0, D: 1, H: 2, S: 3, N: 4 };
const HOLD_MS = 450;

const value = (c: string) => (Number(c[0]) - 1) * 5 + RANK[c[1]];

/**
 * One button per bid. Three rows show at a time, from the lowest level still open; ▼ opens the higher ones.
 * A tap bids; pressing and holding a bid shows what it means without making it.
 */
export default function BiddingBox({ legal, meanings, lastBid, hinted, onCall, onLook, disabled, note }: {
  legal: string[];
  meanings: Record<string, Meaning>;
  lastBid: string | null;
  hinted?: string;
  onCall: (call: string) => void;
  onLook: (call: string | null) => void; // the bid being looked at, for the points line
  disabled: boolean;
  note?: ReactNode; // shown in the note area when nothing is being looked at
}) {
  const [held, setHeld] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const pressTimer = useRef<number | undefined>(undefined);
  const longPressed = useRef(false);

  let lo = 1;
  if (lastBid) lo = Number(lastBid[0]) + (lastBid[1] === "N" ? 1 : 0);
  lo = Math.min(Math.max(lo, 1), 5);
  const rows = [lo, lo + 1, lo + 2];
  const moreRows = [4, 5, 6, 7].filter((l) => l > lo + 2);

  // a new decision (the auction moved on) starts fresh
  useEffect(() => {
    setHeld(null);
    setMore(false);
  }, [lastBid, legal.length]);

  const look = held;
  useEffect(() => onLook(look), [look, onLook]);

  const isLegal = (c: string) => legal.includes(c) && (!/^\d/.test(c) || !lastBid || value(c) > value(lastBid));
  const make = (c: string) => {
    setHeld(null);
    setMore(false);
    onCall(c);
  };
  const tap = (c: string) => {
    if (longPressed.current) {
      longPressed.current = false;
      return;
    }
    make(c);
  };
  const press = (c: string) => {
    longPressed.current = false;
    window.clearTimeout(pressTimer.current);
    pressTimer.current = window.setTimeout(() => {
      longPressed.current = true;
      setHeld(c);
    }, HOLD_MS);
  };
  const release = () => window.clearTimeout(pressTimer.current);

  const button = (c: string, label: ReactNode, cls = "") => (
    <button
      key={c}
      className={`bid ${cls} ${hinted === c ? "hinted" : ""}`}
      disabled={disabled || !isLegal(c)}
      onPointerDown={() => press(c)}
      onPointerUp={release}
      onPointerLeave={release}
      onPointerCancel={release}
      onContextMenu={(e) => e.preventDefault()}
      onClick={() => tap(c)}
    >
      {label}
    </button>
  );
  const bidButton = (c: string) =>
    button(
      c,
      <>
        {c[0]}
        <Suit s={c[1]} />
      </>,
      `s-${c[1]} ${isRed(c[1]) ? "red" : ""} ${c[1] === "N" ? "nt" : ""}`,
    );

  const meaning = look ? meanings[look] : null;
  return (
    <div className="bidding-box">
      <div className="gridwrap">
        <div className="bid-grid">{rows.flatMap((l) => STRAINS.map((s) => bidButton(`${l}${s}`)))}</div>
        {moreRows.length > 0 && (
          <button className="more-arrow" aria-expanded={more} aria-label={more ? "Hide higher bids" : "Show higher bids"} onClick={() => setMore(!more)}>
            {more ? "▲" : "▼"}
          </button>
        )}
        {more && <div className="bid-grid more">{moreRows.flatMap((l) => STRAINS.map((s) => bidButton(`${l}${s}`)))}</div>}
      </div>
      <div className="specials">
        {button("P", "Pass", "pass")}
        {button("X", "Dbl", "dbl")}
        {button("XX", "Rdbl", "rdbl")}
      </div>
      <div className="bidnote">
        {look ? (
          <>
            <span className="text">
              <strong>
                <SuitText text={callLabel(look)} />
              </strong>
              {meaning?.alert && <span className="badge">alert</span>}
              {meaning?.forcing && <span className="badge">forcing</span>} <SuitText text={meaning?.text ?? ""} />
              {meaning?.hcp && <span className="muted-on-felt"> · HCP {meaning.hcp[0]}–{meaning.hcp[1]}</span>}
            </span>
            {held && (
              <button className="chip" onClick={() => setHeld(null)}>
                OK
              </button>
            )}
          </>
        ) : (
          note
        )}
      </div>
    </div>
  );
}
