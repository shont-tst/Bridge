/** A thick back arrow for the Undo buttons, drawn so it reads clearly at any size. */
export default function UndoIcon() {
  return (
    <svg className="undo-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11" fill="none" stroke="currentColor" strokeWidth="3"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
