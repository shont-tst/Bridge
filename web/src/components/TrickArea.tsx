import { compass } from "../cards";
import type { Seat, Trick } from "../types";
import PlayingCard from "./PlayingCard";

/** The cards of one trick in the middle of the table, each in front of the seat that played it. */
export default function TrickArea({ trick, me, banner, onTap, costly, onCard, explained }: {
  trick: Trick | null;
  costly?: string; // ringed: the card a review is about
  me: Seat;
  banner?: React.ReactNode;
  onTap?: () => void;
  onCard?: (card: string, seat: Seat) => void; // tap a bot's played card: how it picked it
  explained?: Record<string, unknown>; // the cards that can be tapped
}) {
  const pos = compass(me);
  const where: Record<Seat, string> = { [pos.top]: "top", [pos.left]: "left", [pos.right]: "right", [pos.bottom]: "bottom" } as Record<Seat, string>;
  return (
    <div className="trick-area" onClick={(e) => !(e.target as Element).closest?.(".pc[role=button]") && onTap?.()}>
      {trick?.cards.map(({ seat, card }) => (
        <PlayingCard
          key={card}
          card={card}
          className={`played ${where[seat]} ${card === costly ? "costly" : ""}`}
          onClick={onCard && explained?.[card] ? () => onCard(card, seat) : undefined}
        />
      ))}
      {banner && <button className="trick-banner">{banner}</button>}
    </div>
  );
}
