import { useEffect, useRef, useState } from "react";
import { useAccount, usePresence, type Invite } from "./account";
import { deviceName, loadSession, saveSession, useRoom, type Session } from "./connection";
import { botsHere, canCarryOn, carryBack, carryOn, tableClosed, forgetTable, keepCarry, offlineReady, onBoardsKept, parkTable, parkWith, prepareOffline, retireEngine, sendBoards, serverAnswers, TableClosed } from "./offline";
import { usePrefs } from "./prefs";
import { leaveWifi } from "./wifi";
import AccountSheet from "./components/AccountSheet";
import Admin from "./components/Admin";
import ConnectAI from "./components/ConnectAI";
import Lobby from "./components/Lobby";
import MyStats from "./components/MyStats";
import TableView from "./components/TableView";
import Tutorial from "./components/Tutorial";

export default function App() {
  const account = useAccount();
  const [session, setSession] = useState<Session | null>(() => {
    const fromUrl = new URLSearchParams(location.search).get("room");
    const saved = loadSession();
    if (fromUrl && (!saved || saved.room !== fromUrl.toUpperCase())) return null;
    return saved;
  });
  const update = (s: Session | null) => {
    saveSession(s);
    setSession(s);
  };
  const [notice, setNotice] = useState<string | null>(null);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [accountOpen, setAccountOpen] = useState<boolean | "ai">(false); // "ai": open at the AI coach section
  const [prefs, setPrefs] = usePrefs(); // for the avatar sheet; the table keeps its own copy in step
  // four-color suits apply on every screen, not just at the table
  useEffect(() => {
    document.documentElement.classList.toggle("fourc", !!prefs.fourColour);
  }, [prefs.fourColour]);
  const [statsOpen, setStatsOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [inviting, setInviting] = useState(false); // the lobby's Invite, for a friend with notifications off
  const [myTable, setMyTable] = useState<string | null>(null); // a table you're seated at, for "Back to your table"
  const [learning, setLearning] = useState(() => new URLSearchParams(location.search).has("learn")); // Learn to play
  const [connectAI] = useState(() => new URLSearchParams(location.search).get("connect")); // an AI app's Allow page
  const sendRef = useRef<(msg: object) => void>(() => {});
  const leave = () => {
    sendRef.current({ type: "away" }); // so opening the app on another device shows the lobby, not this table
    if (session?.local) retireEngine();
    if (session?.wifi) leaveWifi();
    else if (session && !session.watch && !session.local) setMyTable(session.room);
    update(null);
    history.replaceState(null, "", "/");
  };
  // the Admin page closed the table played on this phone: it ends here too
  const closedHere = (message: string) => {
    retireEngine();
    forgetTable();
    setNotice(message);
    setMyTable(null);
    update(null);
    history.replaceState(null, "", "/");
  };
  // a table on this phone, opened again (Back to your table, or the app reopened at it): was it closed meanwhile?
  useEffect(() => {
    if (!session?.local) return;
    const room = session.room;
    let stop = false;
    const look = () => {
      if (document.visibilityState === "hidden") return;
      void tableClosed(room, sessionRef.current?.token)
        .then((yes) => !stop && yes && sessionRef.current?.room === room && closedHere("This table was closed"))
        .catch(() => {}); // no internet: carry on
    };
    look();
    const every = window.setInterval(look, 30000);
    document.addEventListener("visibilitychange", look);
    return () => {
      stop = true;
      clearInterval(every);
      document.removeEventListener("visibilitychange", look);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.local, session?.room]);
  // Leave, then Quit table: for good. A bot table ends on every device; with people, the bot takes your seat.
  const quit = () => {
    const s = session;
    if (!s) return;
    if (s.local) {
      retireEngine();
      forgetTable();
    }
    if (s.wifi) leaveWifi();
    else if (s.token && !s.watch)
      void fetch("/api/rooms/quit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: s.room, token: s.token }) }).catch(() => {});
    setMyTable(null);
    update(null);
    history.replaceState(null, "", "/");
  };
  const { state, error, connected, unreachable, send, hint, hintPending, askHint, moved, takeBack } = useRoom(session, (s) => update(s), (message) => {
    setNotice(message);
    setMyTable(null);
    if (session?.local) forgetTable(); // the table on this phone can't go on
    update(null);
    history.replaceState(null, "", "/");
  }, (s) => {
    // the server stopped answering: the table carries on on this phone (offline.ts)
    history.replaceState(null, "", "/");
    update({ ...s, user: account.user ? { id: account.user.id, name: account.user.name } : undefined });
    setToast(`No connection: playing on this ${deviceName() || "device"}`);
  });
  sendRef.current = send;

  // offline play: get the engine's files onto this phone while there's internet, and send boards played offline to
  // your account once there is
  useEffect(() => {
    if (!navigator.onLine) return;
    const idle = window.setTimeout(() => void prepareOffline(), 8000); // after the app has settled
    return () => clearTimeout(idle);
  }, []);
  useEffect(() => {
    if (!account.token || !account.user) return;
    const user = account.user.id;
    const token = account.token;
    const go = () => void sendBoards(token, user).catch(() => {});
    go();
    let soon = 0;
    onBoardsKept(() => {
      clearTimeout(soon);
      soon = window.setTimeout(go, 2000); // a board just finished on this phone (and again once its review is done)
    });
    window.addEventListener("online", go);
    return () => {
      clearTimeout(soon);
      onBoardsKept(null);
      window.removeEventListener("online", go);
    };
  }, [account.token, account.user?.id, state?.table?.board]);
  // a table played on this phone goes back to the server once it answers again, between boards, so a board isn't
  // split between the two (unless this device is set to play the bots here)
  const phase = state?.table?.phase;
  useEffect(() => {
    if (!session?.local || botsHere() || phase !== "done" || !session.token) return;
    let stop = false;
    const tryBack = async () => {
      if (stop || !(await serverAnswers()) || stop) return;
      try {
        const code = await carryBack(session.token!, account.token);
        if (stop) return;
        history.replaceState(null, "", `/?room=${code}`);
        update({ room: code, name: session.name, solo: true, token: session.token, auth: account.token ?? undefined });
        setToast("Back online");
        if (account.token && account.user) void sendBoards(account.token, account.user.id).catch(() => {});
      } catch (e) {
        if (e instanceof TableClosed) closedHere(e.message); // else try again later
      }
    };
    void tryBack();
    const again = window.setInterval(tryBack, 30000);
    return () => {
      stop = true;
      clearInterval(again);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.local, session?.token, phase]);

  // a table that went to the server for an invite stays there until someone joins it. Once they have, it's an
  // ordinary table with people: when it's down to you and the bots again, it comes back to this phone (below).
  const people = state?.room === session?.room ? Object.keys(state?.players ?? {}).length : 0;
  useEffect(() => {
    if (session?.stay && people > 1) update({ ...session, stay: undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.stay, people]);

  // the other way: a bot table on the server comes to this phone between boards (bots play here by default), unless
  // it went there for an invite. The server sends this phone a copy of it after each change while you're the only
  // person at it (connection.ts), so a table a partner just left comes too, rubber score and all.
  useEffect(() => {
    if (!session || session.local || session.wifi || session.stay || session.watch || phase !== "done") return;
    if (!botsHere() || !offlineReady()) return;
    const s = session;
    const come = () => {
      if (!canCarryOn(s.room)) return false;
      carryOn(s.room);
      history.replaceState(null, "", "/");
      update({ ...s, local: true, fresh: undefined, user: account.user ? { id: account.user.id, name: account.user.name } : undefined });
      return true;
    };
    if (come()) return;
    // the copy comes just after the table's news, so a partner leaving as the board ends needs a moment
    const soon = window.setTimeout(come, 1500);
    return () => clearTimeout(soon);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.room, session?.local, session?.stay, phase, people]);

  // a bot table on this phone, signed in: a copy goes to your account after each change, so your iPad (say) can carry
  // on with it, and your AI coach can see it. If another device has carried on with it, this phone follows.
  useEffect(() => {
    const s = session;
    if (!s?.local || !s.token || !account.token) return parkWith(null);
    const auth = account.token;
    let timer = 0;
    let latest: object | null = null;
    const send = () => {
      if (!latest || !navigator.onLine) return;
      parkTable(latest, s.token!, auth)
        .then(({ taken: code, closed }) => {
          if (sessionRef.current?.room !== s.room) return;
          if (closed) return closedHere(closed);
          if (!code) return;
          history.replaceState(null, "", `/?room=${code}`);
          update({ room: code, name: s.name, solo: true, token: s.token, auth, followed: true });
        })
        .catch(() => {});
    };
    parkWith((snap) => {
      latest = snap;
      clearTimeout(timer);
      timer = window.setTimeout(send, 1500);
    });
    // coming back to the app (or now and then while it's open): has another device carried on with the table?
    const onShow = () => document.visibilityState === "visible" && send();
    document.addEventListener("visibilitychange", onShow);
    const every = window.setInterval(onShow, 20000);
    return () => {
      clearTimeout(timer);
      clearInterval(every);
      document.removeEventListener("visibilitychange", onShow);
      parkWith(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.local, session?.room, session?.token, account.token]);

  // the AI coach sees a table on this phone through the copy sent to your account, so only when signed in and the
  // server answers; a table on a partner's phone over the Wi-Fi it can't see at all
  const [serverUp, setServerUp] = useState(true);
  useEffect(() => {
    if (!session?.local) return;
    let stop = false;
    const look = () => void serverAnswers().then((ok) => !stop && setServerUp(ok));
    look();
    const every = window.setInterval(look, 30000);
    window.addEventListener("online", look);
    window.addEventListener("offline", look);
    return () => {
      stop = true;
      clearInterval(every);
      window.removeEventListener("online", look);
      window.removeEventListener("offline", look);
    };
  }, [session?.local]);
  const coachOff = !!session?.wifi || (!!session?.local && (!account.user || !serverUp));

  // Invite at a bot table on this phone: with internet, the table moves to the server so a friend can join it
  const inviteFromHere = async (): Promise<boolean> => {
    const s = sessionRef.current;
    if (!s?.local || !s.token || !(await serverAnswers())) return false;
    try {
      const code = await carryBack(s.token, account.token);
      history.replaceState(null, "", `/?room=${code}`);
      setInviting(true);
      update({ room: code, name: s.name, solo: true, token: s.token, auth: account.token ?? undefined, stay: true });
      return true;
    } catch (e) {
      if (e instanceof TableClosed) closedHere(e.message);
      return false;
    }
  };

  // signed in on another device: go straight to the table you were just playing at, or offer the way back
  const sessionRef = useRef(session);
  sessionRef.current = session;
  useEffect(() => {
    if (!account.token || !account.user) return;
    const user = account.user;
    const token = account.token;
    const check = () => {
      if (document.visibilityState === "hidden" || connectAI || new URLSearchParams(location.search).get("room")) return;
      account
        .call<{ room?: string; jump?: boolean; snap?: object }>("/api/me/table")
        .then((t) => {
          const now = sessionRef.current;
          if (t.room && t.snap && offlineReady()) keepCarry(t.room, t.snap); // to carry on with if the internet drops
          if (t.room && t.jump && t.room !== now?.room) {
            history.replaceState(null, "", `/?room=${t.room}`);
            update({ room: t.room, name: user.name, auth: token });
          } else if (!now) setMyTable(t.room ?? null);
        })
        .catch(() => {});
    };
    check();
    // a device left open in the lobby picks it up too, when you come back to it
    const onShow = () => !sessionRef.current && check();
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account.token, account.user?.id]);
  const friends = usePresence(
    account.user ? account.token : null,
    (i) => {
      if (i.room !== session?.room) setInvite(i);
    },
    (a) => {
      if (!a.accepted) setToast(`${a.from} can't play right now`);
    },
  );

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [toast]);

  // signing in (or out) while seated: sit down again as yourself, so this board is saved to your account
  useEffect(() => {
    if (session && account.token && account.user && session.auth !== account.token) update({ ...session, auth: account.token, name: account.user.name });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account.token, account.user]);

  const answer = (accept: boolean) => {
    if (!invite) return;
    account.call("/api/play/answer", { from: invite.from_id, room: invite.room, accept }).catch(() => {});
    if (accept && account.user) {
      history.replaceState(null, "", `/?room=${invite.room}`);
      update({ room: invite.room, name: account.user.name, auth: account.token ?? undefined });
    }
    setInvite(null);
  };

  const overlays = (
    <>
      {invite && (
        <div className="invite-banner" role="alert">
          <div className="toast-card">
            <span className="avatar">{invite.from.slice(0, 1).toUpperCase()}</span>
            <span>
              <b>{invite.from} wants to play</b>
            </span>
          </div>
          <div className="row">
            <button className="primary" onClick={() => answer(true)}>
              Join
            </button>
            <button className="ghost" onClick={() => answer(false)}>
              Not now
            </button>
          </div>
        </div>
      )}
      {toast && <div className="invite-banner small-toast">{toast}</div>}
      {accountOpen && (
        <AccountSheet
          account={account}
          prefs={prefs}
          onPrefs={setPrefs}
          onStats={() => {
            setAccountOpen(false);
            setStatsOpen(true);
          }}
          onAdmin={
            account.user?.admin
              ? () => {
                  setAccountOpen(false);
                  setAdminOpen(true);
                }
              : undefined
          }
          onClose={() => setAccountOpen(false)}
          focus={accountOpen === "ai" ? "ai" : undefined}
        />
      )}
    </>
  );

  if (connectAI) return <ConnectAI request={connectAI} account={account} />;
  if (adminOpen && account.user?.admin)
    return (
      <>
        <Admin account={account} onClose={() => setAdminOpen(false)} back={session ? "Table" : "Lobby"} />
        {overlays}
      </>
    );
  // My stats opens from the lobby, or from the table's ☰ menu (the table stays connected underneath)
  if (statsOpen && account.user)
    return (
      <>
        <MyStats account={account} onClose={() => setStatsOpen(false)} back={session ? "Table" : "Lobby"} />
        {overlays}
      </>
    );
  if (learning && !session)
    return (
      <>
        <Tutorial
          account={account}
          onTable={async (step) => {
            // steps 6 and 7 play at a real table: bots at level 2, kept out of My stats
            try {
              const res = await fetch("/api/rooms", {
                method: "POST",
                headers: { "Content-Type": "application/json", ...(account.token ? { Authorization: `Bearer ${account.token}` } : {}) },
                body: JSON.stringify({ tutorial: step }),
              });
              const body = await res.json().catch(() => ({}));
              if (!res.ok) throw new Error(body.detail || "Can't reach the server");
              const name = account.user?.name ?? (localStorage.getItem("bridge-name") || "You");
              history.replaceState(null, "", `/?room=${body.code}`);
              update({ room: body.code, name, solo: true, auth: account.token ?? undefined });
            } catch (e) {
              setToast((e as Error).message || "Can't reach the server");
            }
          }}
          onClose={() => {
            setLearning(false);
            if (new URLSearchParams(location.search).has("learn")) history.replaceState(null, "", "/");
          }}
        />
        {overlays}
      </>
    );
  if (!session)
    return (
      <>
        <Lobby
          onLearn={() => setLearning(true)}
          notice={notice}
          myTable={myTable}
          account={account}
          friends={friends}
          onAccount={() => setAccountOpen(true)}
          onJoin={(s, invite) => {
            setNotice(null);
            setInviting(!!invite);
            update(s);
          }}
        />
        {overlays}
      </>
    );
  return (
    <>
      <TableView
        key={session.room}
        onLocalInvite={inviteFromHere}
        coachOff={coachOff}
        state={state}
        hint={hint}
        hintPending={hintPending}
        askHint={askHint}
        error={error}
        connected={connected}
        unreachable={unreachable}
        send={send}
        onLeave={leave}
        onQuit={session?.watch ? undefined : quit}
        onTutorialStop={() => {
          // back to Learn to play, not the lobby
          sendRef.current({ type: "away" });
          update(null);
          setLearning(true);
          history.replaceState(null, "", "/?learn");
        }}
        onYou={(focus) => setAccountOpen(focus ?? true)}
        initial={account.user?.name.slice(0, 1).toUpperCase()}
        account={account}
        friends={friends}
        inviting={inviting}
        where={session.local ? "local" : session.wifi ? "wifi" : session.stay ? "invite" : undefined}
      />
      {moved && (
        <div className="sheet-backdrop moved-backdrop">
          <div className="sheet moved" role="alert">
            <h2>Playing on {moved === "another device" ? moved : `your ${moved === deviceName() ? "other " : ""}${moved}`} now</h2>
            <div className="result-actions">
              <button onClick={leave}>Lobby</button>
              <button className="primary" onClick={takeBack}>
                Continue here
              </button>
            </div>
          </div>
        </div>
      )}
      {overlays}
    </>
  );
}
