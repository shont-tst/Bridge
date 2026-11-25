import { useEffect, useState } from "react";
import { SEAT_NAME, callLabel } from "../cards";
import type { ConventionPage as Page } from "../types";
import SuitText from "./SuitText";

/** One convention: how it works, example auctions with the system's meanings, and a practice button. */
export default function ConventionPage({ id, practicing, onPractice, onBack, home, back = "Settings" }: {
  id: string;
  back?: string; // where the back button goes
  home?: boolean; // opened from the home screen (its menu, or Learn & practice): Practice starts a bot table
  practicing: boolean;
  onPractice: (on: boolean) => void;
  onBack: () => void;
}) {
  const [page, setPage] = useState<Page | null>(null);
  useEffect(() => {
    fetch(`/api/conventions/${id}`).then((r) => r.json()).then(setPage).catch(() => {});
  }, [id]);

  return (
    <div className="lesson">
      <button className="small" onClick={onBack}>
        ‹ {back}
      </button>
      {!page ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <h2>{page.title}</h2>
          {page.explainer?.map((p, i) => (
            <p key={i}>
              <SuitText text={p} />
            </p>
          ))}
          {page.examples?.map((ex) => (
            <div key={ex.title} className="example">
              <h4>Example: {ex.title}</h4>
              <ol>
                {ex.calls
                  .filter((c) => c.call !== "P")
                  .map((c, i) => (
                    <li key={i}>
                      <span className="example-seat">{SEAT_NAME[c.seat]}</span>{" "}
                      <strong>
                        <SuitText text={callLabel(c.call)} />
                      </strong>
                      {c.artificial && <span className="badge">alert</span>} <span className="muted">
                        <SuitText text={c.text} />
                      </span>
                    </li>
                  ))}
              </ol>
              {ex.calls.every((c) => c.call === "P" || c.seat === "N" || c.seat === "S") && (
                <p className="muted small">Opponents pass throughout.</p>
              )}
            </div>
          ))}
          {page.situations?.map((s) => (
            <div key={s.title} className="example">
              <h4>
                Example: <SuitText text={s.title} />
              </h4>
              <p>
                <SuitText text={s.hand} />
              </p>
              {s.play ? (
                <p>
                  <SuitText text={s.play} />
                </p>
              ) : (
                <ul>
                  <li>
                    <strong>Standard:</strong> <SuitText text={s.standard ?? ""} />
                  </li>
                  <li>
                    <strong>Upside-down:</strong> <SuitText text={s.upside ?? ""} />
                  </li>
                </ul>
              )}
            </div>
          ))}
          <p className="muted small">
            {page.practice_note ?? `Practice deals put this ${page.core ? "lesson" : "convention"} in South's hands (as ${page.student}).`}{" "}
            {home ? "Starts a table with bots." : "Both players see the next boards."}
          </p>
          <button className="primary" onClick={() => onPractice(!practicing)}>
            {practicing ? "Stop practicing" : page.core ? "Practice this" : "Practice this convention"}
          </button>
        </>
      )}
    </div>
  );
}
