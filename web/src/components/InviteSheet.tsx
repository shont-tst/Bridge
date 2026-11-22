import { useState } from "react";
import { lastSeen, type Account, type Friend, type FriendsView } from "../account";
import { APP_NAME } from "../site";

type Sent = "shown" | "notified" | "missed";

/** Invite to game: each friend has an Invite button, so invite one, then another. A friend with the app open gets a
 * banner, one who's away gets a notification on their phone, and one with notifications off gets a link from you. */
export default function InviteSheet({ account, view, room, onClose }: {
  account: Account;
  view: FriendsView | null;
  room: string;
  onClose: () => void;
}) {
  const friends = view?.friends ?? [];
  const here = (f: Friend) => f.status === "table" && f.room === room;
  const reachable = (f: Friend) => f.status !== "away" || !!f.notify;
  const [sent, setSent] = useState<Record<string, Sent>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const url = `${location.origin}/?room=${room}`;
  const text = `${account.user?.name ?? "A friend"} wants to play a game of bridge`;
  // the phone's share sheet where there is one, otherwise copy the link
  const share = () => {
    if (navigator.share) {
      navigator.share({ title: APP_NAME, text, url }).catch(() => {});
      return;
    }
    navigator.clipboard?.writeText(`${text}: ${url}`).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }, () => {});
  };

  const invite = async (id: string) => {
    setBusy(id);
    setErr(null);
    try {
      const r = await account.call<{ shown: boolean; notified: boolean }>("/api/play/invite", { friend: id, room });
      setSent((s) => ({ ...s, [id]: r.shown ? "shown" : r.notified ? "notified" : "missed" }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const status = (f: Friend) => {
    const s = sent[f.id];
    if (s === "shown") return "Invited";
    if (s === "notified") return "Notification sent";
    if (s === "missed") return "Not delivered";
    if (here(f)) return "At this table";
    if (f.status === "ready") return "Ready to play";
    if (f.status === "table") return "At another table";
    return f.notify ? lastSeen(f.last_seen) : "Notifications off";
  };

  const button = (f: Friend) => {
    if (here(f)) return null;
    const s = sent[f.id];
    if (s === "shown" || s === "notified")
      return (
        <button className="small" disabled>
          Invited
        </button>
      );
    if (!reachable(f) || s === "missed")
      return (
        <button className="small" onClick={share}>
          Send link
        </button>
      );
    return (
      <button className="small" disabled={busy === f.id} onClick={() => invite(f.id)}>
        Invite
      </button>
    );
  };

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet invite-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>Invite to game</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {friends.length > 0 && (
          <>
            <ul className="invite-list">
              {friends.map((f) => (
                <li key={f.id}>
                  <span>
                    <b>{f.name}</b>
                    <small>{status(f)}</small>
                  </span>
                  {button(f)}
                </li>
              ))}
            </ul>
            {err && <p className="small invite-error">{err}</p>}
            <h3>Anyone else</h3>
          </>
        )}
        <p className="muted">Anyone can join with a link.</p>
        <button className="share-btn" onClick={share}>
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M8 11H6v10h12V11h-2" />
          </svg>
          {copied ? "Link copied" : "Send a link"}
        </button>
      </div>
    </div>
  );
}
