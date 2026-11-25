import { useState } from "react";
import type { TableBrief } from "../types";

/** "Sam", "Sam and Pat", "Sam, Pat and Kim" */
export function names(list: string[]): string {
  return list.length < 2 ? list.join("") : `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
}

/** When you last played there: "just now", "10 min ago", "3 hr ago", "yesterday", "2 days ago". */
export function ago(t: number, now = Date.now() / 1000): string {
  const mins = (now - t) / 60;
  if (mins < 2) return "just now";
  if (mins < 60) return `${Math.round(mins)} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

const practice = (t: TableBrief) => !t.people.length;

/** The home screen's tables you still have a seat at: Play goes back to your seat, and tapping a table's name offers
 * Quit table, as tapping a friend's name offers Remove. */
export default function YourTables({ tables, onOpen, onQuit }: {
  tables: TableBrief[];
  onOpen: (t: TableBrief) => void;
  onQuit: (t: TableBrief) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (!tables.length) return null;
  const key = (t: TableBrief) => `${t.local ? "here" : t.parked ? "parked" : "server"}:${t.room}`;
  return (
    <section className="friends your-tables">
      <div className="fhead">
        <span>Your tables</span>
      </div>
      {tables.map((t) => {
        const parts = [t.board ? `Board ${t.board}` : "Not started"];
        if (t.we || t.they) parts.push(`We ${t.we ?? 0}, They ${t.they ?? 0}`);
        if (t.here.length) parts.push(`${names(t.here)} ${t.here.length > 1 ? "are" : "is"} there`);
        return (
          <div key={key(t)}>
            <div className="friend">
              <span className={`dot ${t.here.length ? "ready" : ""}`} />
              <span className="fn tap" onClick={() => setOpen(open === key(t) ? null : key(t))}>
                {practice(t) ? "Practice" : `With ${names(t.people)}`}
                <small>
                  {parts.join(" · ")} · <span className="nowrap">{ago(t.last)}</span>
                </small>
              </span>
              <button className="small primary" onClick={() => onOpen(t)}>
                Play
              </button>
            </div>
            {open === key(t) && (
              <div className="friend-remove">
                <p className="small">Quit this table? {practice(t) ? "It ends on all your devices." : "A bot takes your seat."}</p>
                <span className="row">
                  <button className="small danger" onClick={() => {
                      setOpen(null);
                      onQuit(t);
                    }}>
                    Quit table
                  </button>
                  <button className="small ghost" onClick={() => setOpen(null)}>
                    Keep
                  </button>
                </span>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
