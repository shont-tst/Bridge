import type { BoardResult, ClaimOffer as Offer, Seat } from "../types";
import Hand from "./Hand";

/** A bot claims the rest of the tricks: its cards, face up as in a real claim, and Accept or Reject for the people on
 * the other side. There's no ✕: the hand waits for an answer. */
export default function ClaimOffer({ offer, nameOf, onAnswer }: {
  offer: Offer;
  nameOf: (s: Seat) => string;
  onAnswer: (accept: boolean) => void;
}) {
  const who = nameOf(offer.by);
  return (
    <div className="sheet-backdrop">
      <div className="sheet claim-offer" role="dialog" aria-label={`${who} claims`}>
        <h2>{who} claims the rest</h2>
        <p>{who}'s cards:</p>
        <Hand cards={offer.cards} compact />
        {offer.dummy_cards && (
          <>
            <p>Dummy's cards:</p>
            <Hand cards={offer.dummy_cards} compact />
          </>
        )}
        <div className="result-actions">
          <button onClick={() => onAnswer(false)}>Reject</button>
          <button className="primary" onClick={() => onAnswer(true)}>
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}

/** A claim you didn't see made, such as a bot partner's on defense with only bots to decide it, or a
 * bot's claim your partner accepted first (#164): the
 * claiming side's cards as they were, so the hand doesn't just end. Closes with ✕ or a tap outside. */
export function ClaimShown({ result, dummy, nameOf, onClose }: {
  result: BoardResult;
  dummy: Seat | null;
  nameOf: (s: Seat) => string;
  onClose: () => void;
}) {
  const who = nameOf(result.claimed!);
  const hands = Object.entries(result.claim_cards ?? {}) as [Seat, string[]][];
  // the claimer's own hand first, dummy's after
  hands.sort(([a], [b]) => Number(a === dummy) - Number(b === dummy));
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet claim-offer" role="dialog" aria-label={`${who} claimed`} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>{who} claimed the rest</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {result.claim_accepted && <p className="muted">{nameOf(result.claim_accepted)} accepted.</p>}
        {hands.map(([seat, cards]) => (
          <div key={seat}>
            <p>{seat === dummy ? "Dummy's" : `${nameOf(seat)}'s`} cards:</p>
            <Hand cards={cards} compact />
          </div>
        ))}
      </div>
    </div>
  );
}
