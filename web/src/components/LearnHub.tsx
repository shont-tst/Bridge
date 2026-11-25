import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { Account } from "../account";
import type { ConventionInfo, LessonInfo } from "../types";
import { READY } from "../tutorial/lessons";
import { useProgress } from "../tutorial/progress";
import { CHEAT_SHEET } from "./CheatSheet";
import ConventionPage from "./ConventionPage";
import SuitText from "./SuitText";
import PuzzleIntro from "./PuzzleIntro";

// card play lessons, in the order the ☰ menu lists them (their on/off switches stay there)
const CARD_PLAY: LessonInfo[] = [
  { id: "leads", title: "Opening leads", description: "Standard leads: top of a sequence, fourth best." },
  { id: "signals", title: "Signals", description: "Defenders signal with the spot cards they play." },
];

const BackIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);
const Chevron = () => (
  <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9 5l7 7-7 7" />
  </svg>
);

const Inside = ({ title, blurb, right }: { title: string; blurb: string; right?: React.ReactNode }) => (
  <>
    <span className="t">
      <b>{title}</b>
      <span>
        <SuitText text={blurb} />
      </span>
    </span>
    {right}
    <Chevron />
  </>
);

const Row = ({ title, blurb, right, onClick, disabled }: { title: string; blurb: string; right?: React.ReactNode; onClick: () => void; disabled?: boolean }) => (
  <li>
    <button className="tut-step hub-row" onClick={onClick} disabled={disabled}>
      <Inside title={title} blurb={blurb} right={right} />
    </button>
  </li>
);

/** Learn & practice, from the home screen: Learn to play, Your mistakes, and every lesson with practice deals. */
export default function LearnHub({ account, mistakes, mistakeKinds = {}, error, onClose, onLearn, onPuzzles, onPractice }: {
  account: Account;
  mistakes: number; // Your mistakes waiting as puzzles
  mistakeKinds?: Record<string, number>; // the same by kind (PuzzleIntro)
  error?: string | null;
  onClose: () => void;
  onLearn: () => void; // Learn to play
  onPuzzles?: (kind?: string) => void; // Your mistakes (signed in only): every kind, or only one
  onPractice: (id: string) => void; // a bot table on this lesson
}) {
  const progress = useProgress(account);
  const [bidding, setBidding] = useState<LessonInfo[]>([]);
  const [lesson, setLesson] = useState<string | null>(null);
  const [intro, setIntro] = useState(false); // Your mistakes: how it works, and what to practice
  useEffect(() => {
    // bidding lessons on the base system, then the conventions that have one
    Promise.all([fetch("/api/lessons").then((r) => r.json()), fetch("/api/conventions").then((r) => r.json())])
      .then(([l, c]: [LessonInfo[], ConventionInfo[]]) => setBidding([...l, ...c.filter((x) => x.lesson && !x.core)]))
      .catch(() => {});
  }, []);
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const on = () => setWide(window.innerWidth >= 700 && window.innerHeight >= 560);
    on();
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  const done = progress.done.filter((n) => READY.includes(n)).length;
  const steps = done === READY.length ? <span className="tag">Done</span> : done ? <span className="tag">{done} of {READY.length}</span> : null;
  const open = (id: string) => setLesson(id);

  return (
    <div className={`app tut ${wide ? "wide" : ""}`}>
      <div className="topbar">
        <button className="icon tut-back" aria-label="Back" onClick={onClose}>
          <BackIcon />
        </button>
        <span className="boardinfo">Learn &amp; practice</span>
        <span style={{ width: 34 }} />
      </div>
      <div className="tut-page">
        <h2>Learn &amp; practice</h2>
        {error && <div className="error">{error}</div>}
        <ul className="tut-steps hub">
          <Row title="Learn to play" blurb="Seven short steps for beginners." right={steps} onClick={onLearn} />
          {onPuzzles && (
            <Row
              title="Your mistakes"
              blurb={mistakes ? "Hands you got wrong, as puzzles." : "Hands you get wrong come back here as puzzles."}
              right={mistakes ? <span className="hub-count">{mistakes}</span> : <span className="tag none">None now</span>}
              onClick={() => setIntro(true)}
              disabled={!mistakes}
            />
          )}
        </ul>
        <h3 className="hub-h">Bidding</h3>
        <ul className="tut-steps hub">
          <li>
            <a className="tut-step hub-row" href={CHEAT_SHEET} target="_blank" rel="noopener noreferrer">
              <Inside title="Cheat sheet" blurb="The whole bidding system on one page." />
            </a>
          </li>
          {bidding.map((t) => (
            <Row key={t.id} title={t.title} blurb={t.description} onClick={() => open(t.id)} />
          ))}
        </ul>
        <h3 className="hub-h">Card play</h3>
        <ul className="tut-steps hub">
          {CARD_PLAY.map((t) => (
            <Row key={t.id} title={t.title} blurb={t.description} onClick={() => open(t.id)} />
          ))}
        </ul>
      </div>
      {intro && onPuzzles &&
        createPortal(
          <div className="sheet-backdrop" onClick={() => setIntro(false)}>
            <div className="sheet" onClick={(e) => e.stopPropagation()}>
              <PuzzleIntro
                total={mistakes}
                kinds={mistakeKinds}
                onStart={(kind) => {
                  setIntro(false);
                  onPuzzles(kind);
                }}
                onBack={() => setIntro(false)}
              />
            </div>
          </div>,
          document.body,
        )}
      {lesson &&
        createPortal(
          <div className="sheet-backdrop" onClick={() => setLesson(null)}>
            <div className="sheet" onClick={(e) => e.stopPropagation()}>
              <ConventionPage
                id={lesson}
                home
                back="Learn & practice"
                practicing={false}
                onPractice={() => {
                  setLesson(null);
                  onPractice(lesson);
                }}
                onBack={() => setLesson(null)}
              />
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
