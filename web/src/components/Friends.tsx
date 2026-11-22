import { Fragment, useState } from "react";
import { lastSeen, makeInviteLink, type Account, type Friend, type FriendsView } from "../account";
import { APP_NAME } from "../site";

/** The lobby's friends list: who's ready to play, who's at a table, requests to answer, and adding a friend. */
export default function Friends({ account, view, onPlay, onJoin }: {
  account: Account;
  view: FriendsView | null;
  onPlay: (f: Friend) => void;
  onJoin: (room: string) => void; // a friend at a table: sit down with them, or watch
}) {
  const [adding, setAdding] = useState(false);
  const [link, setLink] = useState<string | null>(null); // the invite link + Add made
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null); // the friend whose name was tapped, showing Remove

  // + Add makes an invite link, the only way to add a friend: someone new makes an account with it, and someone who
  // already plays just opens it. Either way you're friends straight away.
  const add = async () => {
    setMsg(null);
    if (adding) return setAdding(false);
    setAdding(true);
    setLink(null);
    setBusy(true);
    try {
      setLink(await makeInviteLink(account));
    } catch (e) {
      setMsg((e as Error).message);
      setAdding(false);
    } finally {
      setBusy(false);
    }
  };
  // Once the link has gone out, the next + Add makes a new one; until then + Add gives the same link back
  const sent = (url: string) => {
    const code = new URL(url).searchParams.get("invite");
    if (code) account.call("/api/me/invite/sent", { code }).catch(() => {});
  };
  const share = (url: string) =>
    navigator.share?.({ title: APP_NAME, text: `${account.user?.name} invites you to play bridge`, url }).then(() => sent(url), () => {});
  const copy = (url: string) =>
    navigator.clipboard?.writeText(url).then(() => {
      setMsg("Link copied");
      sent(url);
    }, () => {});
  const answer = (id: string, accept: boolean) => account.call("/api/friends/answer", { id, accept }).catch((e) => setMsg(e.message));
  const remove = (id: string, name: string, request: boolean) => {
    setOpen(null);
    account
      .call("/api/friends/remove", { id })
      .then(() => setMsg(request ? `Friend request to ${name} cancelled` : `${name} is no longer your friend`))
      .catch((e) => setMsg(e.message));
  };
  // Tapping a name opens a line under it to remove that friend (or cancel a request), so it can't happen by accident
  const removeLine = (id: string, name: string, request: boolean) =>
    open === id && (
      <div className="friend-remove">
        <p className="small">
          {request ? `Cancel your friend request to ${name}?` : `Remove ${name}? They won't be told.`}
        </p>
        <span className="row">
          <button className="small danger" onClick={() => remove(id, name, request)}>
            {request ? "Cancel request" : "Remove"}
          </button>
          <button className="small ghost" onClick={() => setOpen(null)}>
            Keep
          </button>
        </span>
      </div>
    );
  const toggle = (id: string) => setOpen(open === id ? null : id);

  const friends = view?.friends ?? [];
  return (
    <section className="friends">
      <div className="fhead">
        <span>Friends</span>
        <button className="link" onClick={add}>
          {adding ? "Cancel" : "+ Add"}
        </button>
      </div>
      {adding && (
        <div className="add-friend">
          {link ? (
            <>
              <p className="small">Send link, works once, for 30 days.</p>
              {/* iPhone and iPad: one Share button for the share sheet, which has Copy too. Elsewhere: the link and Copy */}
              {"share" in navigator ? (
                <button className="primary share-btn" onClick={() => share(link)}>
                  {/* the iOS share symbol, so it's clear the share sheet opens */}
                  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M8 11H6v10h12V11h-2" />
                  </svg>
                  Invite
                </button>
              ) : (
                <>
                  <code className="invite-link">{link}</code>
                  <span className="row">
                    <button className="small" onClick={() => copy(link)}>
                      Copy
                    </button>
                  </span>
                </>
              )}
            </>
          ) : (
            <p className="small muted-on-felt">{busy ? "Making a link…" : ""}</p>
          )}
        </div>
      )}
      {view?.incoming.map((r) => (
        <div className="friend" key={r.id}>
          <span className="dot in" />
          <span className="fn">
            {r.name}
            <small>Wants to be friends</small>
          </span>
          <span className="row">
            <button className="small primary" onClick={() => answer(r.id, true)}>
              Accept
            </button>
            <button className="small ghost" onClick={() => answer(r.id, false)}>
              No
            </button>
          </span>
        </div>
      ))}
      {friends.map((f) => (
        <Fragment key={f.id}>
        <div className="friend">
          <span className={`dot ${f.status}`} />
          <span className="fn tap" onClick={() => toggle(f.id)}>
            {f.name}
            <small>{f.status === "ready" ? "Ready to play" : f.status === "table" ? "At a table" : lastSeen(f.last_seen)}</small>
          </span>
          {f.status === "ready" ? (
            <button className="small primary" onClick={() => onPlay(f)}>
              Play
            </button>
          ) : f.status === "table" && f.room ? (
            <button className="small ghost" onClick={() => onJoin(f.room!)} title="Take a seat at their table, or watch">
              Join
            </button>
          ) : f.status === "away" ? (
            <button className="small ghost" onClick={() => onPlay(f)} title={f.notify ? "Sends a notification to their phone" : "Start a table and send them a link"}>
              Invite
            </button>
          ) : null}
        </div>
        {removeLine(f.id, f.name, false)}
        </Fragment>
      ))}
      {view?.outgoing.map((r) => (
        <Fragment key={r.id}>
        <div className="friend">
          <span className="dot" />
          <span className="fn tap" onClick={() => toggle(r.id)}>
            {r.name}
            <small>Friend request sent</small>
          </span>
        </div>
        {removeLine(r.id, r.name, true)}
        </Fragment>
      ))}
      {view && !friends.length && !view.incoming.length && !view.outgoing.length && !adding && (
        <p className="small muted-on-felt">No friends yet. Tap + Add to invite one.</p>
      )}
      {msg && <p className="small">{msg}</p>}
    </section>
  );
}
