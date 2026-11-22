import { SUIT_ORDER, isRed, rankLabel } from "../cards";
import Suit from "./Suit";

interface Props {
  cards: string[];
  playable?: string[];
  onPlay?: (card: string) => void;
  compact?: boolean;
  hinted?: string;
}

/** A hand as four suit rows — readable on a phone and easy to tap. */
export default function Hand({ cards, playable = [], onPlay, compact, hinted }: Props) {
  return (
    <div className={`hand ${compact ? "compact" : ""}`}>
      {SUIT_ORDER.map((s) => {
        const suitCards = cards.filter((c) => c[0] === s);
        return (
          <div key={s} className="suit-row">
            <span className={`suit s-${s} ${isRed(s) ? "red" : ""}`}>
              <Suit s={s} />
            </span>
            {suitCards.length === 0 && <span className="void">—</span>}
            {suitCards.map((c) => {
              const can = playable.includes(c);
              return (
                <button
                  key={c}
                  className={`card s-${s} ${isRed(s) ? "red" : ""} ${can ? "playable" : ""} ${hinted === c ? "hinted" : ""}`}
                  disabled={!can || !onPlay}
                  onClick={() => onPlay?.(c)}
                >
                  {rankLabel(c)}
                </button>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
