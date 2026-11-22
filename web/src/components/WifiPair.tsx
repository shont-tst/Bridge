import { useEffect, useRef, useState } from "react";
import qrcode from "qrcode-generator";
import jsQR from "jsqr";
import { deviceName } from "../connection";
import { Invite, Join } from "../wifi";

/** Pairing two phones on a Wi-Fi with no internet (wifi.ts): each shows a QR code and scans the other's. */

function QrCode({ text }: { text: string }) {
  const qr = qrcode(0, "L");
  qr.addData(text, "Byte");
  qr.make();
  const n = qr.getModuleCount();
  let d = "";
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c} ${r}h1v1h-1z`;
  return (
    <svg className="qr" viewBox={`-3 -3 ${n + 6} ${n + 6}`} role="img" aria-label="Pairing code" shapeRendering="crispEdges">
      <rect x={-3} y={-3} width={n + 6} height={n + 6} fill="#fff" />
      <path d={d} fill="#000" />
    </svg>
  );
}

/** The camera, reading QR codes until `onCode` takes one (returns true). Also, while the camera is on, iOS lets the
 * app see the phone's own address on the Wi-Fi, which the other phone needs. */
function useCamera(onCode: (text: string) => boolean, ready: (on: boolean) => void) {
  const video = useRef<HTMLVideoElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const take = useRef(onCode);
  take.current = onCode;
  useEffect(() => {
    let stream: MediaStream | null = null;
    let stop = false;
    let timer = 0;
    const canvas = document.createElement("canvas");
    const look = () => {
      const v = video.current;
      if (stop || !v) return;
      if (v.readyState >= 2 && v.videoWidth) {
        const scale = Math.min(1, 640 / v.videoWidth);
        canvas.width = Math.round(v.videoWidth * scale);
        canvas.height = Math.round(v.videoHeight * scale);
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        if (ctx) {
          ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
          const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
          const found = jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
          if (found?.data && take.current(found.data)) return;
        }
      }
      timer = window.setTimeout(look, 150);
    };
    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: "environment" }, audio: false })
      .then((s) => {
        if (stop) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        const v = video.current!;
        v.srcObject = s;
        void v.play().catch(() => {});
        ready(true);
        look();
      })
      .catch(() => {
        setProblem("The camera is off for this app. Turn it on in Settings, then try again.");
        ready(true); // carry on: the phones may still find each other
      });
    if (!navigator.mediaDevices) {
      setProblem("This browser can't use the camera.");
      ready(true);
    }
    return () => {
      stop = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return { video, problem };
}

function Camera({ cam }: { cam: { video: React.RefObject<HTMLVideoElement | null>; problem: string | null } }) {
  return cam.problem ? <p className="error">{cam.problem}</p> : <video ref={cam.video} className="scan" playsInline muted />;
}

function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet wifi" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>{title}</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

const why = (e: unknown) => (e as Error)?.message || "That didn't work. Try again.";

/** At a table on this phone: a partner on the same Wi-Fi joins it. */
export function WifiInvite({ onClose, onJoined }: { onClose: () => void; onJoined: () => void }) {
  const invite = useRef<Invite | null>(null);
  const [mine, setMine] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const cam = useCamera(
    (text) => {
      if (!text.startsWith("MBa") || !invite.current) return false;
      setJoining(true);
      invite.current.finish(text).catch((e) => {
        setErr(why(e));
        setJoining(false);
      });
      return true;
    },
    () => {
      // the camera's on (or refused): now the code, with this phone's address in it
      const i = new Invite();
      invite.current = i;
      i.start().then(setMine, (e) => setErr(why(e)));
      i.joined.then(onJoined, (e) => setErr(why(e)));
    },
  );
  useEffect(() => () => invite.current?.cancel(), []);
  return (
    <Sheet title="Invite on Wi-Fi" onClose={onClose}>
      <p className="muted">
        For a partner on this Wi-Fi with no internet. On their phone, open the app and tap <b>Join on Wi-Fi</b>, then scan this.
      </p>
      <div className="qr-box">{mine ? <QrCode text={mine} /> : <span className="muted">Making the code…</span>}</div>
      <p className="muted">{joining ? "Joining…" : "Then scan the code their phone shows."}</p>
      <Camera cam={cam} />
      {err && <p className="error">{err}</p>}
    </Sheet>
  );
}

/** In the lobby: join a table on a partner's phone, on the same Wi-Fi. */
export function WifiJoin({ onClose, onJoined }: { onClose: () => void; onJoined: () => void }) {
  const join = useRef<Join | null>(null);
  const [mine, setMine] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const cam = useCamera(
    (text) => {
      if (!text.startsWith("MBo") || join.current) return false;
      const j = new Join();
      join.current = j;
      j.answer(text).then(setMine, (e) => {
        setErr(why(e));
        join.current = null;
      });
      j.joined.then(onJoined, (e) => setErr(why(e)));
      return true;
    },
    () => {},
  );
  useEffect(() => () => join.current?.cancel(), []);
  const device = deviceName() || "device";
  return (
    <Sheet title="Join on Wi-Fi" onClose={onClose}>
      {mine ? (
        <>
          <p className="muted">Now let your partner's phone scan this.</p>
          <div className="qr-box">
            <QrCode text={mine} />
          </div>
          <p className="muted">Joining when it does.</p>
        </>
      ) : (
        <>
          <p className="muted">
            For a table on another phone on this Wi-Fi, with no internet. On that phone, start <b>Play with bots</b>, then Menu, <b>Invite to game</b>. Scan its code with this {device}.
          </p>
          <Camera cam={cam} />
        </>
      )}
      {err && <p className="error">{err}</p>}
    </Sheet>
  );
}
