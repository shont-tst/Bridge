import { useEffect, useRef, useState } from "react";
import { notificationsPossible, turnOffNotifications, turnOnNotifications, type Account } from "../account";
import type { Prefs } from "../prefs";
import DeviceSettings from "./DeviceSettings";
import UpdateBanner from "./UpdateBanner";

/** The sheet behind the avatar at the top right: Stats, this device's settings, then your account
 * (notifications, another phone, signing out). Feedback, Privacy and What's new live on the Home Screen. A guest gets
 * this device's settings. */
export default function AccountSheet({ account, prefs, onPrefs, onStats, onAdmin, onClose, focus }: {
  account: Account;
  prefs: Prefs;
  onPrefs: (p: Partial<Prefs>) => void;
  onStats: () => void;
  onAdmin?: () => void; // the site's owner only
  onClose: () => void;
  focus?: "ai"; // opened from the table's AI coaching setting: start at the AI coach section
}) {
  const user = account.user;
  if (!user)
    return (
      <div className="sheet-backdrop" onClick={onClose}>
        <div className="sheet" onClick={(e) => e.stopPropagation()}>
          <div className="sheet-top">
            <h2>Playing as a guest</h2>
            <button className="close" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
          <UpdateBanner compact />
          <p className="muted">Sign in from the lobby to save your hands.</p>
          <DeviceSettings prefs={prefs} onPrefs={onPrefs} />
        </div>
      </div>
    );
  return <SignedIn account={account} prefs={prefs} onPrefs={onPrefs} onStats={onStats} onAdmin={onAdmin} onClose={onClose} focus={focus} />;
}

function SignedIn({ account, prefs, onPrefs, onStats, onAdmin, onClose, focus }: {
  account: Account;
  prefs: Prefs;
  onPrefs: (p: Partial<Prefs>) => void;
  onStats: () => void;
  onAdmin?: () => void;
  onClose: () => void;
  focus?: "ai";
}) {
  const aiRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focus === "ai") aiRef.current?.scrollIntoView({ block: "start" });
  }, [focus]);
  const user = account.user!;
  const [device, setDevice] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmOut, setConfirmOut] = useState(false);
  const possible = notificationsPossible();
  const on = user.notify && user.push;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const toggleNotify = () =>
    run(async () => {
      account.setUser(on ? await turnOffNotifications(account) : await turnOnNotifications(account));
    });
  const makeDeviceLink = () => run(async () => setDevice((await account.call<{ code: string }>("/api/me/device-link", {})).code));
  const signOutOthers = () =>
    run(async () => {
      const r = await account.call<{ token: string; user: typeof user }>("/api/me/sign-out-others", {});
      account.signedIn(r.token, r.user);
      setConfirmOut(false);
      setMsg("Other devices signed out.");
    });
  const [ai, setAi] = useState<{ id: string; app: string; since: number; used?: number | null }[] | null>(null);
  useEffect(() => {
    account.call<typeof ai>("/api/me/ai").then(setAi).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const disconnect = (id: string) => run(async () => setAi(await account.call<typeof ai>("/api/me/ai/remove", { id })));
  const mcpUrl = `${location.origin}/mcp`;
  const [copied, setCopied] = useState(false); // "Copied" shows next to the Copy button for a moment
  const copy = (text: string) =>
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }, () => {});

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>{user.name}</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <UpdateBanner compact />
        <div className="sheet-actions">
          <button className="small" onClick={onStats}>
            My stats
          </button>
          {onAdmin && (
            <button className="small" onClick={onAdmin}>
              Admin
            </button>
          )}
          <button
            className="small leave"
            onClick={() => {
              account.signOut();
              onClose();
            }}
          >
            Sign out
          </button>
        </div>
        <DeviceSettings prefs={prefs} onPrefs={onPrefs} />

        <h3>Your account</h3>
        <h4>Notifications</h4>
        <label className="toggle">
          <input type="checkbox" checked={!!on} disabled={busy || possible !== "yes"} onChange={toggleNotify} />
          <span>
            <strong>Invite notifications</strong>
            <br />
            <span className="muted">
              {possible === "home-screen"
                ? "Add the app to your Home Screen first: Share, then Add to Home Screen."
                : possible === "no"
                  ? "This browser can't show notifications."
                  : "When a friend invites you and the app is closed."}
            </span>
          </span>
        </label>

        <h4>Another phone or tablet</h4>
        <p className="muted">
          On your Apple account? Just tap Sign in there. Otherwise make a code here and tap <b>Add this device</b> on the new one.
        </p>
        {device ? (
          <p className="device-code">
            <span>{device}</span>
            <small className="muted">Works once, for 15 minutes</small>
          </p>
        ) : (
          <button disabled={busy} onClick={makeDeviceLink}>
            Make a code for another device
          </button>
        )}

        <h4 ref={aiRef} className="ai-coach-head">AI coach</h4>
        <p className="muted">
          Talk hands through with your own AI assistant. Add this address as a connector, sign in with Face ID and tap Allow. It reads your finished boards. Where Allow AI coaching during play is on, it sees what you see at your seat but can't change anything.
        </p>
        <p className="muted">
          <code>{mcpUrl}</code> <button className="small" onClick={() => copy(mcpUrl)}>Copy</button>
          {copied && <span className="copied"> Copied</span>}
        </p>
        <details className="whats-new ai-how">
          <summary>How to add it</summary>
          <p>
            <b>Claude:</b> on claude.ai, open Settings, then Connectors, choose Add custom connector and paste the address. Once added, it works in the Claude app on your iPhone and iPad too, including voice mode. Free accounts can add one connector.
          </p>
          <p>
            <b>ChatGPT:</b> add it in a web browser such as Safari, not the ChatGPT app. Go to chatgpt.com and open Plugins from the side menu. Tap Browse directory, then Add, then Add custom MCP server. Paste the address as the Server URL, choose OAuth for Authentication, tick I understand and want to continue, and save. Sign in here and tap Allow. After that it works in the ChatGPT app too.
          </p>
          <p>
            <b>Others:</b> Gemini and other assistants that accept MCP connectors can work too, once the site's owner adds them. Use Feedback to ask for one.
          </p>
        </details>
        {ai?.map((c) => (
          <div className="ai-row" key={c.id}>
            <span>
              <strong>{c.app}</strong> <span className="muted">connected {shortDay(c.since)} · {c.used ? `last used ${shortDay(c.used)}` : "not used yet"}</span>
            </span>
            <button className="small leave" disabled={busy} onClick={() => disconnect(c.id)}>
              Remove
            </button>
          </div>
        ))}

        <h4>Lost a phone?</h4>
        <p className="muted">Signs out your other devices and AI apps. This one stays signed in.</p>
        {confirmOut ? (
          <div className="sheet-actions">
            <button className="small leave" disabled={busy} onClick={signOutOthers}>
              Yes, sign them out
            </button>
            <button className="small" disabled={busy} onClick={() => setConfirmOut(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button disabled={busy} onClick={() => setConfirmOut(true)}>
            Sign out other phones
          </button>
        )}
        {msg && <p className="error">{msg}</p>}
      </div>
    </div>
  );
}

/** "Nov 14", in Pacific time like the rest of the app's dates. */
const shortDay = (t: number) => new Date(t * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/Los_Angeles" });
