import Suit from "./Suit";

const LETTER: Record<string, string> = { "♠": "S", "♥": "H", "♦": "D", "♣": "C" };

/** Text with its suit symbols drawn and colored by suit. A rank or level next to a symbol (2♥, ♦A, 10♦) stays in the
 * text color and stays on one line with it; only cards, bid buttons and bid tiles color the whole thing. */
export default function SuitText({ text }: { text: string }) {
  const parts = text.split(/((?:10|[2-9AKQJ])?[♥♦♠♣](?:10|[2-9AKQJ](?![a-z]))?)/);
  return (
    <>
      {parts.map((p, i) => {
        if (i % 2 === 0) return p;
        const sym = p.match(/[♥♦♠♣]/)![0];
        const [before, after] = p.split(sym);
        return (
          <span key={i} className="suit-word">
            {before}
            <Suit s={LETTER[sym]} />
            {after}
          </span>
        );
      })}
    </>
  );
}
