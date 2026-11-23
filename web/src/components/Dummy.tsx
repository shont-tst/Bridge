import type { CSSProperties } from "react";
import { fanOrder } from "../cards";
import PlayingCard from "./PlayingCard";

const HIGH = "AKQJT98765432";

/** How far each card in a column (or side row) sits below (or beside) the one before it. */
export const dummyStep = (w: number, side = false) => Math.round(w * (side ? 0.44 : 0.42));

/**
 * Dummy as it lies on the table, trumps first (on declarer's left).
 * "columns": a column per suit, highest card at the top, each overlapping the next (iPad).
 * "row": one straight overlapping row, suit by suit, sized to the screen's width (iPhone).
 * "side": a row per suit, for a dummy at the left or right.
 */
export default function Dummy({ cards, trump, playable = [], onPlay, hinted, w, h, layout }: {
  cards: string[];
  trump: string;
  playable?: string[];
  onPlay?: (card: string) => void;
  hinted?: string;
  w: number;
  h: number;
  layout: "columns" | "row" | "side";
}) {
  const suits = fanOrder(trump); // trumps on the left, colors alternating
  // a suit that's gone takes no room, so what's left stays together
  const shown = suits.filter((s) => cards.some((c) => c[0] === s));
  const bySuit = shown.map((s) => cards.filter((c) => c[0] === s).sort((a, b) => HIGH.indexOf(a[1]) - HIGH.indexOf(b[1])));
  const card = (c: string, style: CSSProperties) => {
    const ok = !!onPlay && playable.includes(c);
    return (
      <PlayingCard
        key={c}
        card={c}
        className={`${ok ? "ok" : onPlay && playable.length ? "dim" : ""} ${c === hinted ? "hinted" : ""}`}
        style={{ "--w": `${w}px`, "--h": `${h}px`, ...style } as CSSProperties}
        onClick={ok ? () => onPlay!(c) : undefined}
      />
    );
  };

  if (layout === "row") {
    // each card sits in a slot that shares out the width; the last slot is a whole card wide
    const all = bySuit.flat();
    return (
      <div className="dummy row" style={{ height: h, maxWidth: w + (all.length - 1) * Math.round(w * 0.62) }}>
        {all.map((c, i) => (
          <div key={c} className={`dslot ${i > 0 && all[i - 1][0] !== c[0] ? "newsuit" : ""}`} style={i === all.length - 1 ? { flex: `0 0 ${w}px` } : undefined}>
            {card(c, { zIndex: i })}
          </div>
        ))}
      </div>
    );
  }

  const side = layout === "side";
  const step = dummyStep(w, side);
  return (
    <div className={`dummy ${layout}`}>
      {bySuit.map((col, k) => {
        const size = side
          ? { width: col.length ? w + (col.length - 1) * step : w, height: h }
          : { width: w, height: col.length ? h + (col.length - 1) * step : h };
        return (
          <div key={shown[k]} className="dcol" style={size}>
            {col.map((c, i) => card(c, { [side ? "left" : "top"]: i * step, zIndex: i }))}
          </div>
        );
      })}
    </div>
  );
}
