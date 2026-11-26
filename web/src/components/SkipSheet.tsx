/** Your partner, a person, tapped Skip hand: throw this hand in unscored and deal a new one, or keep playing it. */
export default function SkipSheet({ name, onSkip, onPlay }: {
  name: string;
  onSkip: () => void;
  onPlay: () => void;
}) {
  return (
    <div className="sheet-backdrop">
      <div className="sheet gone-sheet" role="dialog" aria-label={`${name} wants to skip this hand`}>
        <h2>{name} wants to skip this hand</h2>
        <p>It isn't scored, and a new hand is dealt.</p>
        <div className="result-actions">
          <button onClick={onPlay}>Keep playing</button>
          <button className="primary" onClick={onSkip}>
            Skip hand
          </button>
        </div>
      </div>
    </div>
  );
}
