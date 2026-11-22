import { useEffect, useState } from "react";
import { api, cancelled, passkeyName, type Account } from "../account";
import PlayingCard from "./PlayingCard";

/** The Allow page an AI assistant (Claude, ChatGPT, ...) sends you to when you add this app as a connector: sign in with
 * your passkey, then let it read your finished boards. The server picked the app's name from where it sends you
 * back, so a look-alike can't call itself Claude. */
export default function ConnectAI({ request, account }: { request: string; account: Account }) {
  const [app, setApp] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const user = account.user;

  useEffect(() => {
    api<{ app: string }>(`/api/connect/${encodeURIComponent(request)}`)
      .then((r) => setApp(r.app))
      .catch((e: Error) => setErr(e.message));
  }, [request]);

  const answer = async (allow: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await account.call<{ redirect: string }>("/api/connect/approve", { request, allow });
      location.href = r.redirect;
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };
  const signIn = async () => {
    setBusy(true);
    setErr(null);
    try {
      await account.signIn();
    } catch (e) {
      if (!cancelled(e)) setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="lobby connect-ai">
      <div className="crest" aria-hidden="true">
        {["SA", "HA", "CA", "DA"].map((c, i) => (
          <PlayingCard key={c} card={c} style={{ transform: `rotate(${-21 + i * 14}deg)`, zIndex: i }} />
        ))}
      </div>
      <h1>Connect {app ?? "your AI assistant"}</h1>
      {app && (
        <>
          <p className="tag">
            {app} will be able to read your finished boards, so you can talk a hand through with it, by text or by voice.
          </p>
          <ul className="muted connect-list">
            <li>The hands, bidding and play of each board you finish while signed in, and the app's review of it</li>
            <li>Your stats and hand history</li>
            <li>A board you're playing only at tables that allow AI coaching, and only what your seat sees. It can't play, bid or change anything</li>
          </ul>
          {!user ? (
            <button className="primary" disabled={busy || account.checking} onClick={signIn}>
              Sign in with {passkeyName()}
            </button>
          ) : (
            <>
              <p className="muted">Signed in as {user.name}. Remove it any time in your account.</p>
              <button className="primary" disabled={busy} onClick={() => answer(true)}>
                Allow
              </button>
              <button className="ghost" disabled={busy} onClick={() => answer(false)}>
                Don't allow
              </button>
            </>
          )}
        </>
      )}
      {err && <div className="error">{err}</div>}
    </div>
  );
}
