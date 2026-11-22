import { forwardBoards, hostLink, type Link } from "./offline";

/** Partners on a Wi-Fi with no internet, such as a boat's: one phone plays the table (the engine in offline.ts) and
 * the other joins it straight over the Wi-Fi, with WebRTC. With no server to introduce them, the two phones swap
 * QR codes: the host shows one, the partner scans it and shows one back, and the host scans that.
 *
 * Messages are the same ones the server's WebSocket carries. Long ones (the table's state) go in pieces. */

const PIECE = 12000;
const MORE = "\u0001"; // a piece with more to come; the last piece has no mark

function sendText(ch: RTCDataChannel, text: string) {
  if (ch.readyState !== "open") return;
  for (let i = 0; i < text.length; i += PIECE) ch.send((i + PIECE < text.length ? MORE : "") + text.slice(i, i + PIECE));
}

function hearText(ch: RTCDataChannel, on: (text: string) => void) {
  let held = "";
  ch.onmessage = (ev) => {
    const piece = String(ev.data);
    if (piece.startsWith(MORE)) held += piece.slice(1);
    else {
      const text = held + piece;
      held = "";
      on(text);
    }
  };
}

// --- the codes the phones swap ---------------------------------------------------------------------------------
async function squeeze(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  if (typeof CompressionStream === "undefined") return "R" + b64(bytes);
  const out = await new Response(new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate-raw"))).arrayBuffer();
  return "Z" + b64(new Uint8Array(out));
}

async function unsqueeze(code: string): Promise<string> {
  const bytes = unb64(code.slice(1));
  if (code[0] === "R") return new TextDecoder().decode(bytes);
  const out = await new Response(new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer();
  return new TextDecoder().decode(out);
}

const b64 = (b: Uint8Array) => btoa(String.fromCharCode(...b));
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

/** Only what the other phone needs: candidates on this Wi-Fi (not loopback or relays), so the code stays small. */
function trim(sdp: string): string {
  return sdp
    .split(/\r?\n/)
    .filter((l) => l && !/^a=(extmap|rtcp|ssrc|msid|ice-options)/.test(l))
    .filter((l) => !l.startsWith("a=candidate:") || / typ host/.test(l))
    .join("\r\n") + "\r\n";
}

async function code(pc: RTCPeerConnection, kind: "o" | "a"): Promise<string> {
  // wait for this phone's addresses on the Wi-Fi (a few hundred milliseconds), all in the one code
  await new Promise<void>((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const t = window.setTimeout(resolve, 3000);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(t);
        resolve();
      }
    });
  });
  const sdp = pc.localDescription?.sdp ?? "";
  if (!/a=candidate:/.test(sdp)) throw new Error("This phone isn't on a Wi-Fi");
  return `MB${kind}` + (await squeeze(trim(sdp)));
}

async function read(text: string, kind: "o" | "a"): Promise<RTCSessionDescriptionInit> {
  if (!text.startsWith(`MB${kind}`)) throw new Error(kind === "o" ? "That's not a table's code" : "That's not a partner's code");
  return { type: kind === "o" ? "offer" : "answer", sdp: await unsqueeze(text.slice(3)) };
}

// --- the phone with the table ------------------------------------------------------------------------------------
/** One partner joining this phone's table. `start()` gives the code to show; `finish()` takes the partner's. */
export class Invite {
  pc = new RTCPeerConnection({ iceServers: [] });
  ch = this.pc.createDataChannel("table", { ordered: true });
  joined: Promise<void>;

  constructor() {
    this.joined = new Promise((resolve, reject) => {
      this.ch.onopen = () => {
        linkUp(this.pc, this.ch);
        resolve();
      };
      this.pc.addEventListener("connectionstatechange", () => {
        if (this.pc.connectionState === "failed") reject(new Error("The phones couldn't reach each other on this Wi-Fi"));
      });
    });
  }

  async start(): Promise<string> {
    await this.pc.setLocalDescription(await this.pc.createOffer());
    return code(this.pc, "o");
  }

  async finish(partner: string) {
    await this.pc.setRemoteDescription(await read(partner, "a"));
  }

  cancel() {
    if (this.ch.readyState !== "open") this.pc.close();
  }
}

/** Partners at this phone's table, and the account each is signed in to (for the boards they play). */
const partners = new Set<{ link: Link; user: string | null }>();

function linkUp(pc: RTCPeerConnection, ch: RTCDataChannel) {
  let conn: { link: Link; user: string | null } | null = null;
  const open = () => {
    const link = hostLink((text) => sendText(ch, text));
    conn = { link, user: null };
    partners.add(conn);
  };
  open();
  hearText(ch, (text) => {
    try {
      const m = JSON.parse(text);
      if (m.type === "join") {
        // the partner's app sat down again (after waking up, say): a fresh seat-taking, as with the server
        if (conn && conn.user !== null) {
          conn.link.close();
          partners.delete(conn);
          open();
        }
        conn!.user = (m.user && typeof m.user.id === "string" && m.user.id) || "";
      }
    } catch {
      /* not ours to read: the table answers it */
    }
    conn?.link.send(text);
  });
  const gone = () => {
    if (!conn) return;
    conn.link.close();
    partners.delete(conn);
    conn = null;
  };
  ch.onclose = gone;
  pc.addEventListener("connectionstatechange", () => {
    if (pc.connectionState === "failed" || pc.connectionState === "closed") gone();
  });
}

/** A board finished at this phone's table for a partner's account: it goes to their phone, for their My stats. */
export function toPartner(user: string, rec: unknown): boolean {
  const p = [...partners].find((x) => x.user === user);
  if (!p) return false;
  p.link.hear(JSON.stringify({ type: "your_board", user, rec }));
  return true;
}

forwardBoards(toPartner);

export function partnerCount(): number {
  return partners.size;
}

// --- the partner's phone ------------------------------------------------------------------------------------------
let joinedTable: { pc: RTCPeerConnection; ch: RTCDataChannel | null; heard: (text: string) => void; ended: () => void } | null = null;

/** Joining a table on another phone: `answer(code)` takes the host's code and gives the one to show back. */
export class Join {
  pc = new RTCPeerConnection({ iceServers: [] });
  joined: Promise<void>;

  constructor() {
    const pc = this.pc;
    const here = { pc, ch: null as RTCDataChannel | null, heard: (_: string) => {}, ended: () => {} };
    this.joined = new Promise((resolve, reject) => {
      pc.ondatachannel = (ev) => {
        const ch = ev.channel;
        here.ch = ch;
        hearText(ch, (t) => here.heard(t));
        ch.onclose = () => here.ended();
        ch.onopen = () => {
          joinedTable?.pc.close();
          joinedTable = here;
          resolve();
        };
      };
      pc.addEventListener("connectionstatechange", () => {
        if (pc.connectionState === "failed") {
          reject(new Error("The phones couldn't reach each other on this Wi-Fi"));
          here.ended();
        }
      });
    });
  }

  async answer(host: string): Promise<string> {
    await this.pc.setRemoteDescription(await read(host, "o"));
    await this.pc.setLocalDescription(await this.pc.createAnswer());
    return code(this.pc, "a");
  }

  cancel() {
    if (joinedTable?.pc !== this.pc) this.pc.close();
  }
}

/** Leaving the table on the other phone. */
export function leaveWifi() {
  joinedTable?.pc.close();
  joinedTable = null;
}

/** A WebSocket to the table on the other phone, for connection.ts. */
export class WifiSocket {
  static readonly OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor() {
    const t = joinedTable;
    window.setTimeout(() => {
      if (this.readyState === 3) return;
      if (!t || t.ch?.readyState !== "open") {
        // the link is gone: the table can't go on here
        this.readyState = 1;
        this.onmessage?.({ data: JSON.stringify({ type: "error", fatal: true, message: "Lost the Wi-Fi link to your partner's phone" }) });
        this.close();
        return;
      }
      t.heard = (text) => this.readyState === 1 && this.onmessage?.({ data: text });
      t.ended = () => {
        if (this.readyState !== 1) return;
        this.onmessage?.({ data: JSON.stringify({ type: "error", fatal: true, message: "Lost the Wi-Fi link to your partner's phone" }) });
        this.close();
      };
      this.readyState = 1;
      this.onopen?.();
    }, 0);
  }

  send(text: string) {
    const ch = joinedTable?.ch;
    if (this.readyState === 1 && ch) sendText(ch, text);
  }

  close() {
    // the link stays up: a new socket (after the app wakes, say) carries on over it
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.();
  }
}
