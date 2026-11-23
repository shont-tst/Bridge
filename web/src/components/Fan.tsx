import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { sortFan } from "../cards";
import PlayingCard from "./PlayingCard";

interface Props {
  cards: string[] | number; // the cards, or how many card backs
  w: number; // card size in px
  h: number;
  spread?: number; // degrees from the first card to the last
  playable?: string[];
  onPlay?: (card: string) => void;
  hinted?: string;
  trump?: string; // the trump suit goes on the left once the contract is set
  className?: string;
  style?: CSSProperties;
}

// Face-down cards for a hand we only know the size of (never more than 13).
const HIDDEN: (string | null)[] = Array(13).fill(null);

/**
 * A hand held as a fan: every card turns about one point below the hand, so the corners stay readable.
 * The pivot is set from the fan's width, so 13 cards always fit the screen.
 * Cards keep a full hand's spacing and stay centered, so a short hand is a tight group in the middle.
 */
export default function Fan({ cards, w, h, spread = 50, playable, onPlay, hinted, trump, className = "", style }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(360);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const list = typeof cards === "number" ? HIDDEN.slice(0, Math.max(cards, 0)) : sortFan(cards, trump);
  const n = list.length;
  const half = ((spread / 2) * Math.PI) / 180;
  const span = Math.max(w, width - w - 8); // room for the cards' centers to travel
  const origin = Math.max(h * 1.5, span / 2 / Math.sin(half) - h); // pivot below the card's top edge
  const step = spread / 12; // the gap a full 13-card hand has
  const angle = (i: number) => (i - (n - 1) / 2) * step;
  const playing = !!playable && !!onPlay;
  return (
    <div className={`fan ${className}`} ref={ref} style={style}>
      {list.map((c, i) => {
        const ok = playing && c !== null && playable!.includes(c);
        const cls = !playing || c === null ? "" : ok ? "ok" : "dim";
        return (
          <PlayingCard
            key={c ?? i}
            card={c}
            className={`${cls} ${c && c === hinted ? "hinted" : ""}`}
            style={{ "--w": `${w}px`, "--h": `${h}px`, "--a": `${angle(i)}deg`, "--origin": `${origin}px`, zIndex: i + 1 } as CSSProperties}
            onClick={ok ? () => onPlay!(c!) : undefined}
          />
        );
      })}
    </div>
  );
}
