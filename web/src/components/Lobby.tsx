import { lazy, Suspense, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { REMEMBERED, usePrefs } from "../prefs";
import type { Settings, TableBrief } from "../types";
import { cancelled, passkeyName, type Account, type Friend, type FriendsView } from "../account";
import type { Session } from "../connection";
import { botsHere, forgetTable, keptBrief, keptTableClosed, offlineReady, serverAnswers, warmEngine } from "../offline";
import Friends from "./Friends";
import LearnHub from "./LearnHub";
import YourTables from "./YourTables";
import PlayingCard from "./PlayingCard";
import Feedback from "./Feedback";
import Privacy from "./Privacy";
import SettingsPanel from "./SettingsPanel";
import UpdateBanner from "./UpdateBanner";
import WhatsNew from "./WhatsNew";
import { APP_NAME } from "../site";

const WifiJoin = lazy(() => import("./WifiPair").then((m) => ({ default: m.WifiJoin }))); // its QR reader is large

type Mode = "start" | "signup" | "device";

export default function Lobby({ onJoin, notice, account, friends, onAccount, onLearn, onPuzzles, hub, onHub, onStats }: {
  onJoin: (s: Session, invite?: boolean) => void; // invite: open Invite to game at the new table
  notice?: string | null;

  account: Account;
  friends: FriendsView | null;
  onAccount: () => void;
  onLearn: () => void; // Learn to play
  onPuzzles?: (kind?: string) => void; // Your mistakes, every kind or only one (PuzzleIntro's KINDS)
  hub: boolean; // Learn & practice is open
  onHub: (open: boolean) => void;
  onStats?: () => void; // My stats (signed in only)
}) {
  const params = new URLSearchParams(location.search);
  const urlRoom = params.get("room")?.toUpperCase() ?? "";
  const urlInvite = params.get("invite") ?? "";
  const [name, setName] = useState(() => localStorage.getItem("bridge-name") ?? "");
  const [code, setCode] = useState(urlRoom);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(notice ? `${notice}. Start a new table, or join your partner's.` : null);
  const [mode, setMode] = useState<Mode>(urlInvite ? "signup" : "start");
  // a friend's invite link opened by someone who already plays: used once they're signed in (not after making an
  // account with it, which uses it up and makes the friends already)
  const [pendingInvite, setPendingInvite] = useState(urlInvite);
  const [friendNote, setFriendNote] = useState<string | null>(null);
  const [deviceCode, setDeviceCode] = useState("");
  const [guest, setGuest] = useState(false);
  const user = account.user;
  // Your mistakes: how many of your past mistakes are waiting as puzzles (signed in only)
  const [puzzles, setPuzzles] = useState(0);
  const [puzzleKinds, setPuzzleKinds] = useState<Record<string, number>>({}); // the same by kind of mistake
  const call = account.call;
  useEffect(() => {
    if (!user) return setPuzzles(0);
    let off = false;
    call<{ waiting: number; kinds?: Record<string, number> }>("/api/me/puzzles").then((p) => {
      if (off) return;
      setPuzzles(p.waiting);
      setPuzzleKinds(p.kinds ?? {});
    }, () => {});
    return () => {
      off = true;
    };
  }, [call, user?.id]);
  const [prefs, setPrefs] = usePrefs();
  const [defaults, setDefaults] = useState<Settings | null>(null); // the ☰ menu, open: what new tables start with
  const accounts = account.config?.accounts;
  const faceId = passkeyName();
  // the site owner's notice (set on the Admin page), until this phone hides it
  const siteNotice = account.config?.notice;
  const [hidNotice, setHidNotice] = useState<number | null>(() => {
    try {
      return Number(localStorage.getItem("bridge-notice-hidden")) || null;
    } catch {
      return null;
    }
  });
  const hideNotice = () => {
    if (!siteNotice) return;
    setHidNotice(siteNotice.at);
    try {
      localStorage.setItem("bridge-notice-hidden", String(siteNotice.at));
    } catch {
      /* private mode: hidden until the app is reopened */
    }
  };

  useEffect(() => {
    if (!user || !pendingInvite) return;
    setPendingInvite("");
    history.replaceState(null, "", "/");
    account
      .call<{ name: string }>("/api/friends/invite", { code: pendingInvite })
      .then((r) => setFriendNote(`You and ${r.name} are now friends`))
      .catch((e) => setErr((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, pendingInvite]);

  const remember = () => localStorage.setItem("bridge-name", name.trim());
  // practice from Learn & practice, which has no name field: "You", as in Learn to play
  const who = () => (user ? user.name : name.trim() || (hub ? "You" : ""));

  const headers = { "Content-Type": "application/json", ...(account.token ? { Authorization: `Bearer ${account.token}` } : {}) };
  const newRoom = async (practice?: string): Promise<string> => {
    // starts with the table settings last chosen: the account's when signed in, otherwise this phone's
    const res = await fetch("/api/rooms", { method: "POST", headers, body: JSON.stringify({ settings: prefs.table, practice }) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || "Can't reach the server"); // e.g. every table is in use
    return body.code;
  };

  const sit = (room: string, solo = false, invite = false) => {
    if (!user) remember();
    history.replaceState(null, "", `/?room=${room}`);
    onJoin({ room, name: who(), solo, auth: account.token ?? undefined }, invite);
  };

  // a table with the bots on this phone (offline.ts): with no internet, when the server is full, or when this device
  // is set to play the bots here
  const here = (practice?: string) => {
    if (!user) remember();
    history.replaceState(null, "", "/");
    onJoin({
      room: "HOME", name: who(), solo: true, local: true, fresh: { settings: prefs.table, practice },
      auth: account.token ?? undefined, user: user ? { id: user.id, name: user.name } : undefined,
    });
  };
  const [closed, setClosed] = useState(false); // the table kept here was closed on the Admin page
  useEffect(() => {
    let off = false;
    void keptTableClosed().then((yes) => !off && yes && setClosed(true));
    return () => {
      off = true;
    };
  }, []);
  // Your tables: the one kept on this phone, and (signed in) every table on the server you still have a seat at
  const [kept, setKept] = useState(() => keptBrief(user?.id));
  const local = closed ? null : kept;
  const [onServer, setOnServer] = useState<TableBrief[]>([]);
  const lookUp = () => {
    if (!account.token) return setOnServer([]);
    account
      .call<{ tables: TableBrief[] }>("/api/me/tables")
      .then((r) => setOnServer(r.tables))
      .catch(() => {}); // no internet: the table on this phone is still listed
  };
  useEffect(() => {
    lookUp();
    const onShow = () => document.visibilityState === "visible" && lookUp();
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account.token]);
  // the table on this phone sends a copy to the server (parked): it's listed once, as this phone's
  const yours = [...(local ? [local] : []), ...onServer.filter((t) => !local || (!t.parked && t.room !== local.room))]
    .sort((a, b) => b.last - a.last);
  const goBack = async (t: TableBrief) => {
    if (t.local) {
      if (!user) remember();
      history.replaceState(null, "", "/");
      return onJoin({ room: t.room, name: who() || "You", solo: true, local: true, auth: account.token ?? undefined,
        user: user ? { id: user.id, name: user.name } : undefined });
    }
    if (!t.parked) return sit(t.room);
    try { // your bot table on your other phone comes to the server, and that phone follows it
      sit((await account.call<{ room: string }>("/api/me/tables/claim", {})).room);
    } catch (e) {
      setErr((e as Error).message);
      lookUp();
    }
  };
  const quit = async (t: TableBrief & { token?: string }, quiet = false) => {
    setErr(null);
    if (t.local) { // as Leave, then Quit table, at the table: it ends here and on your other devices
      forgetTable();
      setKept(null);
      setOnServer((all) => all.filter((s) => !s.parked)); // its copy on the server ends with it
      if (t.token)
        await fetch("/api/rooms/quit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: t.room, token: t.token }) }).catch(() => {});
      return quiet || lookUp();
    }
    try {
      await account.call("/api/me/tables/quit", { room: t.parked ? `parked:${t.room}` : t.room });
    } catch (e) {
      if (!quiet) setErr((e as Error).message);
    }
    if (!quiet) lookUp();
  };
  // bot tables play on this phone, unless the menu's switch says otherwise
  const atHome = () => botsHere() && offlineReady();

  // partners on a Wi-Fi with no internet (wifi.ts): offered when the server doesn't answer
  const [noServer, setNoServer] = useState(false);
  const [wifi, setWifi] = useState(false);
  useEffect(() => {
    if (botsHere()) warmEngine(); // a bot table starts in a moment, not a few seconds
    if (typeof RTCPeerConnection === "undefined") return;
    let off = false;
    void serverAnswers().then((yes) => !off && setNoServer(!yes));
    return () => {
      off = true;
    };
  }, []);
  const wifiJoin = noServer && !urlRoom && (
    <>
      <button onClick={() => (who() ? setWifi(true) : setErr("Enter your name"))}>Join on Wi-Fi</button>
      {wifi && (
        <Suspense fallback={null}>
        <WifiJoin
          onClose={() => setWifi(false)}
          onJoined={() => {
            if (!user) remember();
            setWifi(false);
            history.replaceState(null, "", "/");
            onJoin({ room: "WIFI", name: who(), wifi: true, user: user ? { id: user.id, name: user.name } : undefined });
          }}
        />
        </Suspense>
      )}
    </>
  );

  // one practice table at a time: a new one ends the one you had (Learn to play and Your mistakes aren't listed)
  const endPractice = () => Promise.all(yours.filter((t) => !t.people.length).map((t) => quit(t, true)));

  const create = async (solo: boolean) => {
    if (!who()) return setErr("Enter your name");
    if (solo) await endPractice();
    if (solo && atHome()) return here();
    setBusy(true);
    try {
      sit(await newRoom(), solo);
    } catch (e) {
      if (solo && offlineReady()) here();
      else setErr((e as Error).message || "Can't reach the server");
    } finally {
      setBusy(false);
    }
  };

  // the ☰ menu: the table menu's settings, for the tables you start from here
  const openMenu = async () => {
    setErr(null);
    try {
      const res = await fetch("/api/table-defaults", { method: "POST", headers, body: JSON.stringify({ settings: prefs.table }) });
      if (!res.ok) throw new Error();
      setDefaults(await res.json());
    } catch {
      setErr("Can't reach the server");
    }
  };
  const changeDefaults = (s: Partial<Settings>) => {
    setDefaults((d) => (d ? { ...d, ...s } : d));
    const keep = Object.fromEntries(Object.entries(s).filter(([k]) => (REMEMBERED as readonly string[]).includes(k)));
    if (!Object.keys(keep).length) return;
    setPrefs({ table: { ...prefs.table, ...keep } });
    if (user)
      account
        .call<Settings>("/api/me/table-settings", { settings: keep })
        .then((now) => setDefaults((d) => (d ? now : d)))
        .catch((e) => setErr((e as Error).message));
  };
  const practice = async (id: string) => {
    if (!who()) return setErr("Enter your name");
    await endPractice();
    if (atHome()) return here(id);
    setBusy(true);
    try {
      sit(await newRoom(id), true);
    } catch (e) {
      if (offlineReady()) here(id);
      else setErr((e as Error).message || "Can't reach the server");
    } finally {
      setBusy(false);
    }
  };
  const menuButton = (
    <button className="icon menu-btn" onClick={openMenu} aria-label="Menu">
      ☰
    </button>
  );
  // on the body, not in the lobby, so the lobby's own label styles stay out of the sheet
  const menu =
    defaults &&
    createPortal(
      <SettingsPanel
        settings={defaults}
        onChange={changeDefaults}
        onClose={() => setDefaults(null)}
        onPractice={practice}
        onAccount={
          user
            ? () => {
                setDefaults(null);
                onAccount();
              }
            : undefined
        }
      />,
      document.body,
    );

  const join = () => {
    const c = code.trim().toUpperCase();
    if (!who()) return setErr("Enter your name");
    if (c.length !== 6 && c.length !== 4) return setErr("Room codes have 4 letters");
    sit(c);
  };

  const playWith = async (f: Friend) => {
    setBusy(true);
    try {
      const room = await newRoom();
      // a banner if they have the app open, otherwise a notification. Notifications off: the table opens
      // Invite to game, where Send link is next to their name
      const r = f.status === "away" && !f.notify ? null : await account.call<{ shown: boolean; notified: boolean }>("/api/play/invite", { friend: f.id, room });
      sit(room, false, !r || (!r.shown && !r.notified));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const passkey = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      setMode("start");
      if (urlInvite) history.replaceState(null, "", "/");
    } catch (e) {
      if (!cancelled(e)) setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const crest = (
    <>
      <div className="crest" aria-hidden="true">
        {["SA", "HA", "CA", "DA"].map((c, i) => (
          <PlayingCard key={c} card={c} style={{ transform: `rotate(${-21 + i * 14}deg)`, zIndex: i }} />
        ))}
      </div>
      <h1>
        {/* the last word on a line of its own: "Card Club" becomes "Card / Club" */}
        {APP_NAME.includes(" ") && (
          <>
            {APP_NAME.slice(0, APP_NAME.lastIndexOf(" "))}
            <br />
          </>
        )}
        {APP_NAME.slice(APP_NAME.lastIndexOf(" ") + 1)}
      </h1>
      <UpdateBanner />
      {siteNotice && siteNotice.at !== hidNotice && (
        <div className="site-notice" role="status">
          <span>{siteNotice.text}</span>
          <button className="close" aria-label="Hide" onClick={hideNotice}>
            ✕
          </button>
        </div>
      )}
    </>
  );

  const tables = (
    <>
      {urlRoom ? null : (
        <>
          {!user && (
            <button className="primary" disabled={busy} onClick={() => create(false)}>
              New table
            </button>
          )}
          <button disabled={busy} onClick={() => create(true)}>
            Play with bots
          </button>
          <div className="divider">{user ? "or play by room code" : "or join your partner"}</div>
        </>
      )}
      <div className="row">
        <input className="code" placeholder="CODE" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={6} autoCapitalize="characters" />
        <button className={urlRoom ? "primary" : ""} onClick={join}>
          Join
        </button>
        {user && !urlRoom && (
          <button disabled={busy} onClick={() => create(false)} title="A new table your partner joins with its code">
            New
          </button>
        )}
      </div>
    </>
  );

  // Learn & practice: Learn to play, Your mistakes and every lesson, on one page
  const learnButton = (
    <button className="learn puzzles" onClick={() => onHub(true)}>
      Learn &amp; practice {puzzles > 0 && <span className="count">{puzzles}</span>}
    </button>
  );
  if (hub && !urlRoom)
    return (
      <LearnHub
        account={account}
        mistakes={puzzles}
        mistakeKinds={puzzleKinds}
        error={err}
        onClose={() => {
          setErr(null);
          onHub(false);
        }}
        onLearn={onLearn}
        onPuzzles={user ? onPuzzles : undefined}
        onStats={onStats}
        onPractice={practice}
      />
    );

  // --- signed in ---------------------------------------------------------------------------------------
  if (user)
    return (
      <div className="lobby">
        <div className="lobby-top">
          {urlRoom ? <span /> : menuButton}
          <button className="who" onClick={onAccount} aria-label="Your account">
            <span>{user.name}</span>
            <span className="avatar">{user.name.slice(0, 1).toUpperCase()}</span>
          </button>
        </div>
        {crest}
        {friendNote && <p className="tag">{friendNote}</p>}
        {!urlRoom && <YourTables tables={yours} onOpen={goBack} onQuit={quit} />}
        {!urlRoom && <Friends account={account} view={friends} onPlay={playWith} onJoin={(room) => sit(room)} />}
        {tables}
        {wifiJoin}
        {err && <div className="error">{err}</div>}
        {!urlRoom && learnButton}
        <Feedback />
        <Privacy />
        <WhatsNew />
        {menu}
      </div>
    );

  // --- making an account, or adding this device to one ---------------------------------------------------
  if (accounts && mode !== "start")
    return (
      <div className="lobby">
        {crest}
        {mode === "signup" ? (
          <>
            <p className="tag">Save your hands and see when friends are ready.</p>
            <label>
              Your name
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={24} autoComplete="given-name" />
            </label>
            <button className="primary" disabled={busy || !name.trim()} onClick={() => {
                setPendingInvite(""); // making the account uses the link
                passkey(() => account.signUp(name.trim(), urlInvite || null));
              }}>
              Create account with {faceId}
            </button>
            {urlInvite && (
              <p className="small muted-on-felt center-text">
                Already play? <button className="link" disabled={busy || account.checking} onClick={() => passkey(account.signIn)}>Sign in with {faceId}</button> and you'll be friends.
              </p>
            )}
          </>
        ) : (
          <>
            <p className="tag">On a signed-in device, make a code in your account. Enter it here.</p>
            <input className="code" placeholder="CODE" value={deviceCode} onChange={(e) => setDeviceCode(e.target.value.toUpperCase())} maxLength={8} autoCapitalize="characters" />
            <button className="primary" disabled={busy || deviceCode.trim().length < 6} onClick={() => passkey(() => account.signUp("", deviceCode.trim()))}>
              Add this device with {faceId}
            </button>
          </>
        )}
        <button className="ghost" onClick={() => setMode("start")}>
          Back
        </button>
        {err && <div className="error">{err}</div>}
      </div>
    );

  // --- signed out ----------------------------------------------------------------------------------------
  return (
    <div className="lobby">
      {(!accounts || guest) && !urlRoom && <div className="lobby-top">{menuButton}</div>}
      {crest}
      {accounts && !guest ? (
        <>
          <p className="tag">Save your hands and play with friends.</p>
          <button className="primary" disabled={busy || account.checking} onClick={() => passkey(account.signIn)}>
            Sign in with {faceId}
          </button>
          <button className="ghost" onClick={() => setMode("signup")}>
            Create an account
          </button>
          <p className="small muted-on-felt center-text">
            New accounts need an invite link. <button className="link" onClick={() => setMode("device")}>Add this device</button>
          </p>
          <button onClick={() => setGuest(true)}>
            Play as a guest
          </button>
        </>
      ) : (
        <>
          <p className="tag">Bots fill empty seats.</p>
          <label>
            Your name
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={24} autoComplete="given-name" />
          </label>
          {!urlRoom && <YourTables tables={yours} onOpen={goBack} onQuit={quit} />}
          {tables}
          {wifiJoin}
          {!urlRoom && learnButton}
          {accounts && (
            <button className="link" onClick={() => setGuest(false)}>
              Sign in instead
            </button>
          )}
        </>
      )}
      {err && <div className="error">{err}</div>}
      <Feedback />
      <Privacy />
      <WhatsNew />
      {menu}
    </div>
  );
}
