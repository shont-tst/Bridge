import { useEffect, useState } from "react";
import type { ConventionInfo, Settings } from "../types";
import CheatSheetLink from "./CheatSheet";
import ConventionPage from "./ConventionPage";
import { BotStrengthInfo, HintsInfo } from "./Explain";
import { BotsHere } from "./DeviceSettings";
import SuitText from "./SuitText";
import { APP_NAME } from "../site";


/** The ☰ menu: at a table, that table's settings under Skip hand, Invite to game, Change seat and Leave. On the home
 * screen (no `room`), the same settings for your next new tables, and Practice starts a bot table on that practice. */
export default function SettingsPanel({ settings, onChange, onClose, onLeave, onQuit, others, onSkip, onChangeSeat, onAccount, onInvite, onPractice, room, where }: {
  settings: Settings;
  onChange: (s: Partial<Settings>) => void;
  onClose: () => void;
  onLeave?: () => void; // Leave, then Return later
  onQuit?: () => void; // Leave, then Quit table: for good
  others?: boolean; // other people at the table
  onSkip?: () => void; // mid-hand, alone or with a person as partner against bots: deal a fresh hand, this one unscored (a partner says yes first)
  onChangeSeat?: () => void; // seated: pick another seat, or watch
  onAccount?: () => void; // your account, at its AI coach section
  onInvite?: () => void; // signed in: pick friends to invite (otherwise Invite to game shares a link)
  onPractice?: (id: string) => void; // the home screen: start a bot table on this practice
  room?: string; // none on the home screen
  where?: "local" | "wifi" | "invite"; // "invite": a bot table kept on the server so a friend can join; or a table on this phone (with no internet, Invite asks a partner on this Wi-Fi), or on a partner's
}) {
  const home = !room;
  const [conventions, setConventions] = useState<ConventionInfo[]>([]);
  const [level, setLevel] = useState(settings.difficulty);
  const [lesson, setLesson] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false); // Leave asks: return later, or quit
  useEffect(() => {
    fetch("/api/conventions").then((r) => r.json()).then(setConventions).catch(() => {});
  }, []);
  const toggle = (id: string) => {
    const on = new Set(settings.conventions);
    if (on.has(id)) on.delete(id);
    else on.add(id);
    onChange({ conventions: [...on] });
  };
  const share = `${location.origin}/?room=${room}`;
  // the phone's share sheet where there is one, otherwise copy the link
  const [copied, setCopied] = useState(false);
  const invite = () => {
    if (onInvite) return onInvite();
    if (navigator.share) {
      navigator.share({ title: APP_NAME, text: `Join my bridge game, room ${room}`, url: share }).catch(() => {});
      return;
    }
    navigator.clipboard?.writeText(share).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }, () => {});
  };

  if (lesson)
    return (
      <div className="sheet-backdrop" onClick={onClose}>
        <div className="sheet" onClick={(e) => e.stopPropagation()}>
          <ConventionPage
            id={lesson}
            practicing={settings.practice === lesson}
            onPractice={(on) => {
              if (home) onPractice?.(lesson);
              else onChange({ practice: on ? lesson : null });
              onClose();
            }}
            onBack={() => setLesson(null)}
            home={home}
          />
        </div>
      </div>
    );

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>Menu</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {!home && <div className="sheet-actions">
          {onSkip && (
            <button className="small" onClick={onSkip}>
              Skip hand
            </button>
          )}
          {where !== "wifi" && (
            <button className="small" onClick={invite}>
              {copied ? "Link copied" : "Invite to game"}
            </button>
          )}
          {onChangeSeat && (
            <button className="small" onClick={onChangeSeat}>
              Change seat
            </button>
          )}
          <button className="small leave" onClick={onQuit ? () => setLeaving(!leaving) : onLeave}>
            Leave
          </button>
        </div>}
        {!home && leaving && onQuit && (
          <div className="leave-ask">
            <p className="muted">
              {!others
                ? "Return later keeps the table. Quit ends it on all your devices."
                : where === "local"
                  ? "Return later keeps the table. Quit ends it, for your partner too."
                  : "Return later keeps your seat. Quit gives it to a bot, and the game goes on for the others."}
            </p>
            <div className="sheet-actions">
              <button className="small" onClick={onLeave}>
                Return later
              </button>
              <button className="small leave" onClick={onQuit}>
                Quit table
              </button>
            </div>
          </div>
        )}
        {where !== "wifi" && (
          <BotsHere
            server={home || where === "local" ? undefined : others ? "On the server while a partner is here." : where === "invite" ? "On the server so a friend can join." : undefined}
          />
        )}
        <h3>{home ? "New tables" : "This table"}</h3>
        <p className="muted">{home ? "Your new tables start with these." : "These apply to everyone at the table."}</p>
        <label>
          Bot strength: <strong>{level}</strong>{" "}
          <BotStrengthInfo level={level} />
          <input
            type="range"
            min={1}
            max={10}
            value={level}
            onChange={(e) => setLevel(Number(e.target.value))}
            onPointerUp={() => onChange({ difficulty: level })}
            onKeyUp={() => onChange({ difficulty: level })}
          />
          <div className="range-labels">
            <span>Beginner</span>
            <span>Expert</span>
          </div>
        </label>
        <label className="toggle">
          <input type="checkbox" checked={settings.undo} onChange={(e) => onChange({ undo: e.target.checked })} />
          <span>
            <strong>Allow undo</strong>
            <br />
            <span className="muted">Take back your last call or card.</span>
          </span>
        </label>
        <label className="toggle">
          <input type="checkbox" checked={settings.hints} onChange={(e) => onChange({ hints: e.target.checked })} />
          <span>
            <strong>Allow hints</strong>{" "}
            <HintsInfo />
            <br />
            <span className="muted">Suggests a call or card.</span>
          </span>
        </label>
        <label className="toggle">
          <input type="checkbox" checked={settings.ai_coach} onChange={(e) => onChange({ ai_coach: e.target.checked })} />
          <span>
            <strong>Allow AI coaching during play</strong>
            <br />
            <span className="muted">A player's own{" "}
              {onAccount ? (
                <button
                  type="button"
                  className="text-link"
                  onClick={(e) => {
                    e.preventDefault();
                    onAccount();
                  }}
                >
                  AI assistant
                </button>
              ) : (
                "AI assistant"
              )}{" "}
              can see their seat during a board. It shows on the table and in their review.</span>
          </span>
        </label>
        <label>
          Scoring
          <select value={settings.scoring} onChange={(e) => onChange({ scoring: e.target.value as Settings["scoring"] })}>
            <option value="duplicate">Duplicate: each board by itself</option>
            <option value="rubber">Rubber: best of three games</option>
          </select>
        </label>
        <label>
          A finished trick stays on the table for
          <select value={settings.trick_pause} onChange={(e) => onChange({ trick_pause: Number(e.target.value) })}>
            {[1, 2, 3, 4].map((s) => (
              <option key={s} value={s}>
                {s === 1 ? "1 second" : `${s} seconds`}
              </option>
            ))}
          </select>
        </label>
        <h4>Bidding</h4>
        <p className="muted">
          SAYC: American style 5-card majors and strong <span style={{ whiteSpace: "nowrap" }}>1NT (15-17)</span>. Follows{" "}
          <CheatSheetLink />
          .
        </p>
        <h4>Conventions</h4>
        <ul className="conventions">
          {conventions
            .filter((c) => !c.core)
            .map((c) => (
              <li key={c.id}>
                <label>
                  <input type="checkbox" checked={settings.conventions.includes(c.id)} onChange={() => toggle(c.id)} />
                  <span>
                    <strong>{c.title}</strong>
                    <br />
                    <span className="muted">
                      <SuitText text={c.description} />
                    </span>
                  </span>
                </label>
                {c.lesson && (
                  <button className="small learn" onClick={() => setLesson(c.id)}>
                    {settings.practice === c.id ? "Practicing" : "Learn & practice"}
                  </button>
                )}
              </li>
            ))}
        </ul>
        <h4>Card play</h4>
        <ul className="conventions">
          <li>
            <label>
              <input
                type="checkbox"
                checked={settings.leads}
                onChange={(e) => onChange({ leads: e.target.checked })}
              />
              <span>
                <strong>Opening leads</strong>
                <br />
                <span className="muted">Standard leads: top of a sequence, fourth best.</span>
              </span>
            </label>
            <button className="small learn" onClick={() => setLesson("leads")}>
              {settings.practice === "leads" ? "Practicing" : "Learn & practice"}
            </button>
          </li>
          <li>
            <label>
              <input
                type="checkbox"
                checked={settings.signals !== "off"}
                onChange={(e) => onChange({ signals: e.target.checked ? "standard" : "off" })}
              />
              <span>
                <strong>Signals</strong>
                <br />
                <span className="muted">Defenders signal with the spot cards they play.</span>
              </span>
            </label>
            {settings.signals !== "off" && (
              <select
                className="indented"
                aria-label="Signals method"
                value={settings.signals}
                onChange={(e) => onChange({ signals: e.target.value as Settings["signals"] })}
              >
                <option value="standard">Standard: high encourages</option>
                <option value="upside">Upside-down: low encourages</option>
              </select>
            )}
            <button className="small learn" onClick={() => setLesson("signals")}>
              {settings.practice === "signals" ? "Practicing" : "Learn & practice"}
            </button>
          </li>
        </ul>
      </div>
    </div>
  );
}
