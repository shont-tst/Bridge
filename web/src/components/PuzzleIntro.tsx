/** Your mistakes, opened from Learn & practice: how the puzzles work, then all of them or one kind to practice. */

// the kinds of mistake, as the server sorts them (puzzles.py KINDS)
const KINDS: { id: string; title: string }[] = [
  { id: "bidding", title: "Bidding" },
  { id: "suit", title: "Declarer play in a suit" },
  { id: "notrump", title: "Declarer play in notrump" },
  { id: "leads", title: "Opening leads" },
  { id: "defense", title: "Defense" },
];

const Chevron = () => (
  <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9 5l7 7-7 7" />
  </svg>
);

export default function PuzzleIntro({ total, kinds, onStart, onBack }: {
  total: number; // puzzles waiting
  kinds: Record<string, number>; // the same by kind
  onStart: (kind?: string) => void; // every kind, or only this one
  onBack: () => void;
}) {
  const rows = [{ id: "", title: "All mistakes", n: total }, ...KINDS.map((k) => ({ ...k, n: kinds[k.id] ?? 0 })).filter((k) => k.n > 0)];
  return (
    <div className="lesson">
      <button className="small" onClick={onBack}>
        ‹ Learn &amp; practice
      </button>
      <h2>Your mistakes</h2>
      <p>Calls and cards that cost you come back as puzzles, with the real cards, at that moment of the hand. Make the call or play the card you think is best.</p>
      <p>Right or wrong, a puzzle comes back in 3 days. Get it right twice and it's done.</p>
      <ul className="tut-steps hub pz-list">
        {rows.map((k) => (
          <li key={k.id || "all"}>
            <button className="tut-step hub-row" onClick={() => onStart(k.id || undefined)}>
              <span className="t">
                <b>{k.title}</b>
              </span>
              <span className="hub-count">{k.n}</span>
              <Chevron />
            </button>
          </li>
        ))}
      </ul>
      <p className="muted small">Unlucky cards aren't puzzles: they were the right bet.</p>
    </div>
  );
}
