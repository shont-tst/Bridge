import { useCallback, useEffect, useRef, useState } from "react";

/** Signing in with a passkey (Face ID, Touch ID, a fingerprint or the screen lock), and what comes with an account:
 * the friends list, invites to play and phone notifications. The token is kept on this phone only. */

export interface User {
  id: string;
  name: string;
  friend_code: string;
  notify: boolean;
  push: boolean;
  admin?: boolean; // the site's owner: the lobby shows the Admin page
}

export interface Friend {
  id: string;
  name: string;
  status: "ready" | "table" | "away";
  room?: string;
  last_seen?: number;
  notify?: boolean;
}

export interface FriendsView {
  friends: Friend[];
  incoming: { id: string; name: string }[];
  outgoing: { id: string; name: string }[];
}

export interface Invite {
  from: string;
  from_id: string;
  room: string;
}

const KEY = "bridge-account";

export function loadToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function saveToken(t: string | null) {
  try {
    if (t) localStorage.setItem(KEY, t);
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: fine */
  }
}

export async function api<T = any>(path: string, body?: object, token?: string | null): Promise<T> {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Please try again.");
  return data as T;
}

/** What this phone calls its passkey, for button labels. */
export function passkeyName(): string {
  const ua = navigator.userAgent;
  if (/iPhone|iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "Face ID";
  if (/Android/.test(ua)) return "your fingerprint";
  if (/Macintosh/.test(ua)) return "Touch ID";
  return "a passkey";
}

// --- passkeys: the browser speaks bytes, the server speaks base64url ---------------------------------
const fromB64 = (s: string) => {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
};
const toB64 = (buf: ArrayBuffer | null) => {
  if (!buf) return null;
  let s = "";
  for (const b of new Uint8Array(buf)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

async function createPasskey(o: any): Promise<object> {
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...o,
    challenge: fromB64(o.challenge),
    user: { ...o.user, id: fromB64(o.user.id) },
    excludeCredentials: (o.excludeCredentials || []).map((c: any) => ({ ...c, id: fromB64(c.id) })),
  };
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential;
  const r = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id,
    rawId: toB64(cred.rawId),
    type: cred.type,
    response: { clientDataJSON: toB64(r.clientDataJSON), attestationObject: toB64(r.attestationObject), transports: r.getTransports?.() },
  };
}

async function getPasskey(o: any): Promise<object> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...o,
    challenge: fromB64(o.challenge),
    allowCredentials: (o.allowCredentials || []).map((c: any) => ({ ...c, id: fromB64(c.id) })),
  };
  const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential;
  const r = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: toB64(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: toB64(r.clientDataJSON),
      authenticatorData: toB64(r.authenticatorData),
      signature: toB64(r.signature),
      userHandle: toB64(r.userHandle),
    },
  };
}

/** The passkey sheet was closed, or the phone said no: not worth an error message. */
export function cancelled(e: unknown): boolean {
  return e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "AbortError");
}

// who's signed in, kept so the app still knows with no internet (offline.ts): boards played then go to this account
const USER = "bridge-user";

function loadUser(): User | null {
  try {
    return loadToken() ? (JSON.parse(localStorage.getItem(USER) || "null") as User | null) : null;
  } catch {
    return null;
  }
}

function saveUser(u: User | null) {
  try {
    if (u) localStorage.setItem(USER, JSON.stringify(u));
    else localStorage.removeItem(USER);
  } catch {
    /* private mode: fine */
  }
}

export function useAccount() {
  const [config, setConfig] = useState<{ accounts: boolean; push_key?: string; notice?: { text: string; at: number } | null } | null>(null);
  const [token, setToken] = useState<string | null>(loadToken);
  const [user, setUserNow] = useState<User | null>(null);
  const [checking, setChecking] = useState(() => !!loadToken());
  const setUser = useCallback((u: User | null | ((old: User | null) => User | null)) => {
    setUserNow((old) => {
      const next = typeof u === "function" ? u(old) : u;
      saveUser(next);
      return next;
    });
  }, []);

  const signedIn = useCallback((t: string, u: User) => {
    saveToken(t);
    setToken(t);
    setUser(u);
  }, [setUser]);

  const signOut = useCallback(() => {
    saveToken(null);
    setToken(null);
    setUser(null);
  }, [setUser]);

  useEffect(() => {
    // with no internet: as a guest, unless signed in on this phone before (then as that account)
    api("/api/config").then(setConfig).catch(() => setConfig({ accounts: !!loadUser() }));
  }, []);

  // check the saved token once at start (the server renews it when it's a week old)
  useEffect(() => {
    const t = loadToken();
    if (!t) return;
    api("/api/me", undefined, t)
      .then((r) => signedIn(r.token, r.user))
      .catch((e: Error) => {
        if (/sign in/i.test(e.message)) signOut(); // only a refused token signs you out, not a dropped connection
        else if (!navigator.onLine || e instanceof TypeError) setUserNow(loadUser()); // no internet: who it was
      })
      .finally(() => setChecking(false));
  }, [signedIn, signOut]);

  const signUp = useCallback(
    async (name: string, invite?: string | null) => {
      const o = await api("/api/auth/register/options", { name, invite });
      const credential = await createPasskey(o.options);
      const r = await api("/api/auth/register/verify", { challenge_id: o.challenge_id, credential });
      signedIn(r.token, r.user);
    },
    [signedIn],
  );

  const signIn = useCallback(async () => {
    const o = await api("/api/auth/login/options", {});
    const credential = await getPasskey(o.options);
    const r = await api("/api/auth/login/verify", { challenge_id: o.challenge_id, credential });
    signedIn(r.token, r.user);
  }, [signedIn]);

  const call = useCallback(<T = any>(path: string, body?: object) => api<T>(path, body, token), [token]);

  return { config, token, user, setUser, checking, signUp, signIn, signOut, signedIn, call };
}

export type Account = ReturnType<typeof useAccount>;

/** Makes a one-use invite link for a friend (the lobby's + Add). */
export async function makeInviteLink(account: Account): Promise<string> {
  return (await account.call<{ url: string }>("/api/me/invite", {})).url;
}

// --- notifications --------------------------------------------------------------------------------------
export function notificationsPossible(): "yes" | "home-screen" | "no" {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    // an iPhone only allows them for apps added to the Home Screen
    return /iPhone|iPad/.test(navigator.userAgent) ? "home-screen" : "no";
  }
  return "yes";
}

export async function turnOnNotifications(account: Account): Promise<User> {
  const key = account.config?.push_key;
  if (!key) throw new Error("Notifications aren't available yet");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications are blocked for this app in your phone's Settings");
  const reg = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: fromB64(key) }));
  return account.call<User>("/api/me/push", { subscription: sub.toJSON() });
}

export async function turnOffNotifications(account: Account): Promise<User> {
  try {
    const reg = await navigator.serviceWorker?.getRegistration("/sw.js");
    await (await reg?.pushManager.getSubscription())?.unsubscribe();
  } catch {
    /* the server forgets the phone either way */
  }
  return account.call<User>("/api/me/notify", { on: false });
}

// --- presence: the live friends list and invites, while the app is open -----------------------------------
export function usePresence(token: string | null, onInvite: (i: Invite) => void, onAnswer: (a: { from: string; accepted: boolean }) => void) {
  const [view, setView] = useState<FriendsView | null>(null);
  const inviteRef = useRef(onInvite);
  inviteRef.current = onInvite;
  const answerRef = useRef(onAnswer);
  answerRef.current = onAnswer;

  useEffect(() => {
    if (!token) {
      setView(null);
      return;
    }
    let stopped = false;
    let retry: number | undefined;
    let ping: number | undefined;
    let ws: WebSocket | null = null;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/presence`);
      ws.onopen = () => {
        ws!.send(JSON.stringify({ token }));
        ping = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('{"type":"ping"}'), 25000);
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "friends") setView(msg);
        else if (msg.type === "invite") inviteRef.current(msg);
        else if (msg.type === "invite_answer") answerRef.current(msg);
        else if (msg.type === "error" && msg.fatal) stopped = true;
      };
      ws.onclose = () => {
        clearInterval(ping);
        if (!stopped) retry = window.setTimeout(connect, 3000);
      };
    };
    connect();
    // a phone that was asleep reconnects as soon as the app is back on screen
    const wake = () => {
      if (document.visibilityState === "visible" && ws && ws.readyState === WebSocket.CLOSED && !stopped) {
        clearTimeout(retry);
        connect();
      }
    };
    document.addEventListener("visibilitychange", wake);
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearInterval(ping);
      document.removeEventListener("visibilitychange", wake);
      ws?.close();
    };
  }, [token]);

  return view;
}

export function lastSeen(t?: number): string {
  if (!t) return "Not here yet";
  const mins = (Date.now() / 1000 - t) / 60;
  if (mins < 2) return "Here a moment ago";
  if (mins < 60) return `Last here ${Math.round(mins)} minutes ago`;
  const hours = mins / 60;
  if (hours < 24) return `Last here ${Math.round(hours)} hour${Math.round(hours) === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "Last here yesterday" : `Last here ${days} days ago`;
}

// --- the Admin page -----------------------------------------------------------------------------------------
/** The server's answer when an admin action needs Face ID again (bridge/admin.py CONFIRM). */
const CONFIRM = "Please confirm with Face ID";

/** An admin call that removes or puts back data: if the server asks for Face ID again, ask for it, then retry. */
export async function withFaceId<T>(account: Account, fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if ((e as Error).message !== CONFIRM) throw e;
  }
  const o = await account.call("/api/admin/confirm/options", {});
  const credential = await getPasskey(o.options);
  await account.call("/api/admin/confirm/verify", { challenge_id: o.challenge_id, credential });
  return fn();
}

/** Downloads a file an admin call returns (a backup), keeping its name. */
export async function adminDownload(account: Account, path: string, name: string): Promise<void> {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${account.token}` } });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : "The download didn't work");
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
