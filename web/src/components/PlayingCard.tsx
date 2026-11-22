import type { CSSProperties, ReactNode } from "react";
import { isRed, rankLabel } from "../cards";
import Suit from "./Suit";

const SUIT_NAME: Record<string, string> = { S: "spades", H: "hearts", D: "diamonds", C: "clubs" };

/** One card face (rank and suit in the corner, a big pip bottom right), or a card back when `card` is null. */
export default function PlayingCard({ card, className = "", style, onClick, children }: {
  card: string | null;
  className?: string;
  style?: CSSProperties;
  onClick?: () => void;
  children?: ReactNode;
}) {
  if (!card) return <div className={`pc back ${className}`} style={style} aria-hidden="true" />;
  const s = card[0];
  const label = `${rankLabel(card)} of ${SUIT_NAME[s]}`;
  const press = onClick
    ? {
        role: "button",
        tabIndex: 0,
        onClick,
        onKeyDown: (e: React.KeyboardEvent) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onClick();
          }
        },
      }
    : {};
  return (
    <div className={`pc s-${s} ${isRed(s) ? "red" : ""} ${card[1] === "T" ? "ten" : ""} ${className}`} style={style} aria-label={label} {...press}>
      <span className="ix">
        <b>{rankLabel(card)}</b>
        <Suit s={s} />
      </span>
      <Suit s={s} className="pip" />
      {children}
    </div>
  );
}
