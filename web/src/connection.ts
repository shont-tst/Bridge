import { useCallback, useEffect, useRef, useState } from "react";
import type { Hint, RoomState } from "./types";
import { canCarryOn, carryOn, forgetCarry, keepBoard, keepCarry, LocalSocket, offlineReady, warmEngine } from "./offline";
import { WifiSocket } from "./wifi";

export interface Session {
  room: string;
  name: string;
  token?: string;
  solo?: boolean;
  watch?: boolean; // join to watch rather than to play
  auth?: string; // signed in: the account token, so the board is saved and friends see you at the table
  local?: boolean; // the table is played on this phone (offline.ts), not on the server
  fresh?: { settings: object; practice?: string }; // a new table on this phone: what it starts with (until joined)
  user?: { id: string; name: string }; // signed in, at a table on this phone or a partner's: whose account its boards go to
  wifi?: boolean; // the table is on a partner's phone, joined over the Wi-Fi (wifi.ts)
  stay?: boolean; // a bot table moved to the server for an invite: it stays there
  followed?: boolean; // this phone's table moved to the server because another device carried on with it
  replay?: boolean; // a deal played again, or Your mistakes: a side trip, never "your table"
  back?: Session; // the table to go back to when the replay is done
}

/** What the table talks to: the server's WebSocket, or the table on this phone (offline.ts). */
type Sock = Pick<WebSocket, "send" | "close" | "readyState"> & {
  onopen: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: (() => void) | null;
};

const KEY = "bridge-session";

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: fine */
  }
}

/** This phone or tablet, so the server knows which of a player's devices has the game. Kept for good on this device. */
export function deviceId(): string {
  try {
    let id = localStorage.getItem("bridge-device");
    if (!id) {
      id = Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
      localStorage.setItem("bridge-device", id);
    }
    return id;
  } catch {
    return ""; // private mode: the seat just follows whichever device last opened the table
  }
}

/** What to call this device on the others: "Playing on your iPad now". */
export function deviceName(): string {
  const ua = navigator.userAgent;
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "iPad"; // iPadOS says Mac
  if (/iPhone|iPod/.test(ua)) return "iPhone";
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? "Android phone" : "Android tablet";
  if (/Macintosh/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "PC";
  return "";
}

/** A call or card waiting to reach the table. On a poor connection it is sent again each time the app connects,
 * until the table answers: `id` makes sure it counts once, and `at` (the table as it was when tapped) that it isn't
 * made later at a moment it wasn't meant for. `slow`: no answer yet after a moment, so the table says it's waiting. */
export interface Queued {
  type: "call" | "play";
  call?: string;
  card?: string;
  id: string;
  at: string;
  slow: boolean;
}

function stepKey(st: RoomState | null): string {
  const t = st?.table;
  return t && typeof t.step === "number" ? `${t.board}/${t.step}` : "";
}

function decisionKey(st: RoomState): string {
  const t = st.table;
  if (!t) return "";
  const cards = Object.values(t.counts).reduce((a, n) => a + n, 0);
  return `${t.board}/${t.auction.length}/${cards}`;
}

function wire(q: Queued): object {
  const { slow: _slow, ...msg } = q;
  return msg;
}

/** One WebSocket to the room; reconnects automatically and reclaims the seat by token. */
/** `onGone` hears when the room can't be joined any more (it ended when the server restarted, or the seats are taken). */
/** `onLocal` hears when the server stopped answering at a table this phone can carry on by itself (offline.ts). */
export function useRoom(session: Session | null, onSession: (s: Session) => void, onGone: (message: string) => void,
  onLocal?: (s: Session) => void) {
  const [state, setState] = useState<RoomState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<Hint | null>(null);
  const [connected, setConnected] = useState(false);
  const [hintPending, setHintPending] = useState(false);
  const [moved, setMoved] = useState<string | null>(null); // the device the game moved to, e.g. "iPad"
  const [unreachable, setUnreachable] = useState(false); // the server isn't answering and there's no copy here to go on with
  const [attempt, setAttempt] = useState(0); // goes up with Continue here, to connect again and take the game back
  const [queued, setQueued] = useState<Queued | null>(null);
  const queueRef = useRef<{ msg: Queued; slow?: number } | null>(null);
  const stateRef = useRef<RoomState | null>(null);
  const hintAsked = useRef<string | null>(null); // the decision the hint being worked out is for
  const hintShown = useRef<string | null>(null); // the decision the hint on screen is for, for its firmer answer
  const wsRef = useRef<Sock | null>(null);
  const keyRef = useRef("");
  const revRef = useRef(0); // the room's update number in the last table update received
  const checkRef = useRef<() => void>(() => {});
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const goneRef = useRef(onGone);
  goneRef.current = onGone;
  const localRef = useRef(onLocal);
  localRef.current = onLocal;

  // the call or card got there (or the table moved on without it): stop sending it
  const unqueue = useCallback((id?: string) => {
    const q = queueRef.current;
    if (!q || (id && q.msg.id !== id)) return;
    clearTimeout(q.slow);
    queueRef.current = null;
    setQueued(null);
  }, []);

  useEffect(() => {
    if (!session) return;
    let stopped = false;
    let retry: number | undefined;
    let first = true; // opening the table here takes the game from another device; reconnecting after sleep doesn't
    let waiting: number | undefined; // a ping not answered yet (see check)
    let misses = 0; // tries in a row the server didn't answer: after two, a table with a copy here carries on here

    const missed = () => {
      misses++;
      const s = sessionRef.current;
      if (!s || s.local || s.wifi) return;
      warmEngine(); // it takes a few seconds to start, so start it now in case
      if (misses >= 2 && canCarryOn(s.room) && localRef.current) {
        stopped = true;
        carryOn(s.room);
        localRef.current({ ...s, local: true, fresh: undefined });
      } else if (misses >= 2) setUnreachable(true);
    };

    const connect = () => {
      const s = sessionRef.current!;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws: Sock = s.local ? new LocalSocket(s.room, s.fresh) : s.wifi ? new WifiSocket() : (new WebSocket(`${proto}://${location.host}/ws/${encodeURIComponent(s.room)}`) as unknown as Sock);
      wsRef.current = ws;
      revRef.current = 0;
      ws.onopen = () => {
        setConnected(true);
        ws.send(JSON.stringify({
          type: "join", name: s.name, token: s.token, solo: s.solo, watch: s.watch, auth: s.auth,
          device: deviceId(), device_name: deviceName(), takeover: first && !s.followed,
          carry: !s.local && !s.wifi && offlineReady(), // send this phone a copy of the table, to carry on with offline
          user: s.local || s.wifi ? s.user : undefined,
        }));
        first = false;
        const q = queueRef.current; // still waiting to get through: send it again (the server makes it only once)
        if (q) ws.send(JSON.stringify(wire(q.msg)));
      };
      ws.onmessage = (ev) => {
        if (waiting !== undefined) {
          clearTimeout(waiting); // still alive
          waiting = undefined;
        }
        misses = 0;
        setUnreachable(false);
        const msg = JSON.parse(ev.data);
        if (msg.type === "joined") {
          onSession({ ...sessionRef.current!, token: msg.token, fresh: undefined });
        } else if (msg.type === "your_board") {
          keepBoard(msg.user, msg.rec); // played at the table on your partner's phone, for your account
        } else if (msg.type === "carry") {
          keepCarry(sessionRef.current!.room, msg.snap);
        } else if (msg.type === "pong") {
          // the server has moved on since the last update this phone got: one went missing, so ask for the table again
          if (typeof msg.rev === "number" && msg.rev > revRef.current) ws.send('{"type":"sync"}');
        } else if (msg.type === "state") {
          const st = msg as RoomState;
          if (typeof st.rev === "number") revRef.current = st.rev;
          stateRef.current = st;
          const q = queueRef.current;
          if (q && stepKey(st) !== q.msg.at) unqueue(); // made, or the table moved on (the server then says so)
          if (!sessionRef.current?.local && !sessionRef.current?.wifi && Object.keys(st.players).length > 1) forgetCarry(); // others' cards: not here
          setState(st);
          // a hint is for one decision: retire it once anyone calls or plays
          const key = decisionKey(st);
          if (key !== keyRef.current) {
            setHint(null);
            setHintPending(false);
            hintAsked.current = null; // the server stops a hint once its decision is made, so none may come
            hintShown.current = null;
          }
          keyRef.current = key;
        } else if (msg.type === "ack") {
          unqueue(msg.id);
        } else if (msg.type === "hint") {
          // a hint that arrives after the play moved on is for a decision already made; a close call's firmer
          // answer replaces the first one while the decision is still open
          const h = msg as Hint;
          if (h.phase === "playing" && h.firmer) {
            if (hintShown.current === keyRef.current) setHint(h);
            return;
          }
          if (hintAsked.current === keyRef.current) {
            setHint(h);
            hintShown.current = keyRef.current;
          }
          hintAsked.current = null;
          setHintPending(false);
        } else if (msg.type === "moved") {
          stopped = true; // waits for Continue here
          setMoved(msg.to || "another device");
          ws.close();
        } else if (msg.type === "error" && msg.fatal) {
          stopped = true; // retrying can't help
          goneRef.current(msg.message);
        } else if (msg.type === "error") {
          if (msg.id) unqueue(msg.id);
          setHintPending(false);
          setError(msg.message);
          setTimeout(() => setError(null), 4000);
        }
      };
      ws.onclose = () => {
        if (wsRef.current !== ws) return; // given up on already (see check)
        setConnected(false);
        missed();
        if (!stopped) retry = window.setTimeout(connect, 1500);
      };
    };

    // An iPhone that slept or switched apps can come back with a socket that looks open but is dead: the table
    // stops changing and taps go nowhere. So ask the server to answer now and then, and at once on coming back,
    // and connect again if it doesn't.
    const check = () => {
      const ws = wsRef.current;
      if (stopped || !ws || ws.readyState !== 1 || waiting !== undefined) return;
      ws.send('{"type":"ping"}');
      waiting = window.setTimeout(() => {
        waiting = undefined;
        if (stopped || wsRef.current !== ws) return;
        wsRef.current = null;
        ws.close();
        setConnected(false);
        missed();
        if (!stopped) connect();
      }, 5000);
    };
    checkRef.current = check;
    const onShow = () => document.visibilityState === "visible" && check();
    const beat = window.setInterval(onShow, 20000);
    // a call or card still waiting: check the connection every few seconds rather than every 20, so it goes as soon
    // as the connection is back
    const nudge = window.setInterval(() => queueRef.current && check(), 3000);
    document.addEventListener("visibilitychange", onShow);
    window.addEventListener("pageshow", onShow);
    window.addEventListener("online", check);

    setMoved(null);
    setUnreachable(false);
    connect();
    return () => {
      stopped = true;
      unqueue(); // another table, or this one somewhere else: a call or card meant for the old one mustn't follow
      if (retry) clearTimeout(retry);
      if (waiting) clearTimeout(waiting);
      clearInterval(beat);
      clearInterval(nudge);
      document.removeEventListener("visibilitychange", onShow);
      window.removeEventListener("pageshow", onShow);
      window.removeEventListener("online", check);
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.room, session?.local, session?.wifi, attempt]);

  const send = useCallback((msg: object) => {
    const ws = wsRef.current;
    const kind = (msg as { type?: string }).type;
    const at = stepKey(stateRef.current);
    if ((kind === "call" || kind === "play") && at) {
      // held until the table answers, and sent again if the connection drops before it does
      if (queueRef.current) return; // one at a time: the first is still on its way
      const q: Queued = { ...(msg as { call?: string; card?: string }), type: kind, at, slow: false,
        id: Math.random().toString(36).slice(2, 10) + Date.now().toString(36) };
      const slow = window.setTimeout(() => {
        if (queueRef.current?.msg.id !== q.id) return;
        queueRef.current.msg = { ...q, slow: true };
        setQueued(queueRef.current.msg);
      }, 1500);
      queueRef.current = { msg: q, slow };
      setQueued(q);
      msg = wire(q);
    }
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); // open
    // after a call, card, claim or Undo, check soon that the table's answer arrived (a ping tells, see pong)
    if (kind && ["call", "play", "undo", "claim", "next_board"].includes(kind)) {
      window.setTimeout(() => checkRef.current(), 2000);
    }
  }, []);

  const askHint = useCallback(() => {
    if (hintAsked.current === keyRef.current) return; // already asked for this decision
    hintAsked.current = keyRef.current;
    setHintPending(true);
    send({ type: "hint" });
  }, [send]);

  const takeBack = useCallback(() => setAttempt((n) => n + 1), []);

  return { state, error, connected, unreachable, send, hint, hintPending, askHint, moved, takeBack, queued };
}

// This page was at a table before a reload (Update available, Reload): kept for this tab only, so opening the app
// again later starts on the home screen, while a reload goes back to the table.
const AT_TABLE = "bridge-at-table";
export function atTableBefore(): boolean {
  try {
    return sessionStorage.getItem(AT_TABLE) === "1";
  } catch {
    return false;
  }
}
export function markAtTable(yes: boolean) {
  try {
    if (yes) sessionStorage.setItem(AT_TABLE, "1");
    else sessionStorage.removeItem(AT_TABLE);
  } catch {
    /* private mode: a reload starts on the home screen */
  }
}
