import { useEffect, useState } from "react";
import { VERSION } from "./version";

// Asks the server which version is published, so Reload shows only when there's a newer one than this copy of the app.
// Checked when the app opens, whenever it comes back to the front, and every 10 minutes while it's open.

const EVERY = 10 * 60 * 1000;

/** True when version a ("1.42") is later than b ("1.40"). */
export function isNewer(a: string, b: string): boolean {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0;
    const y = pb[i] || 0;
    if (x !== y) return x > y;
  }
  return false;
}

let latest: string | null = null;
const listeners = new Set<(v: string | null) => void>();
let started = false;

async function check() {
  try {
    const res = await fetch("/api/version", { cache: "no-store" });
    if (!res.ok) return;
    const v = (await res.json()).version;
    const next = typeof v === "string" && isNewer(v, VERSION) ? v : null;
    if (next !== latest) {
      latest = next;
      listeners.forEach((f) => f(latest));
    }
  } catch {
    /* offline: try again later */
  }
}

function start() {
  if (started) return;
  started = true;
  check();
  setInterval(check, EVERY);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") check();
  });
}

/** The newer published version, or null when this copy is up to date. */
export function useUpdate(): string | null {
  const [v, setV] = useState(latest);
  useEffect(() => {
    start();
    listeners.add(setV);
    setV(latest);
    return () => {
      listeners.delete(setV);
    };
  }, []);
  return v;
}

/** Fetch the page again past any cache, so a Home Screen app picks up the new version, then reload. */
export async function reloadLatest() {
  try {
    const regs = (await navigator.serviceWorker?.getRegistrations()) ?? [];
    await Promise.all(regs.map((r) => r.unregister()));
  } catch {
    /* none to clear */
  }
  try {
    const keys = (await window.caches?.keys()) ?? [];
    // all but the offline engine's (offline.ts): Pyodide is 12 MB, and only changes when it's updated
    await Promise.all(keys.filter((k) => k !== "bridge-engine").map((k) => caches.delete(k)));
  } catch {
    /* none to clear */
  }
  try {
    await fetch(location.href, { cache: "reload" });
  } catch {
    /* offline: the reload below still tries */
  }
  location.reload();
}
