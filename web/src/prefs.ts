import { useCallback, useEffect, useState } from "react";
import type { Settings } from "./types";

/** Choices that belong to this phone: kept in the browser. Only `table` is sent, when making a table. */
export interface Prefs {
  pointsDetail: boolean; // your points spelled out with points needed, rather than just "HCP / long / short"
  dealAnimation: boolean;
  fourColour: boolean; // diamonds blue and clubs green, so each suit has its own color
  largeText: boolean; // bigger words and numbers everywhere except on the cards
  table: Partial<Pick<Settings, RememberedKey>>; // the table settings last chosen, for the next new table (an account keeps its own)
}

/** Table settings a new table starts with from the ones last chosen (the server's room.REMEMBERED). */
export const REMEMBERED = ["difficulty", "conventions", "hints", "undo", "ai_coach", "trick_pause", "scoring", "signals", "leads"] as const;
type RememberedKey = (typeof REMEMBERED)[number];

const KEY = "bridge-prefs";
const SYNC = "bridge-prefs-changed";
const DEFAULTS: Prefs = { pointsDetail: false, dealAnimation: true, fourColour: false, largeText: false, table: {} };

function load(): Prefs {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    if (saved.scoring && !saved.table) saved.table = { scoring: saved.scoring }; // before 1.56 only the scoring was kept
    return { ...DEFAULTS, ...saved };
  } catch {
    return DEFAULTS;
  }
}

export function usePrefs(): [Prefs, (p: Partial<Prefs>) => void] {
  const [prefs, setPrefs] = useState<Prefs>(load);
  const update = useCallback((p: Partial<Prefs>) => {
    setPrefs((old) => {
      const next = { ...old, ...p };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* private mode: fine */
      }
      window.setTimeout(() => window.dispatchEvent(new CustomEvent(SYNC, { detail: next })));
      return next;
    });
  }, []);
  // the table and your account sheet each hold the prefs: a change in one shows in the other at once
  useEffect(() => {
    const sync = (e: Event) => setPrefs((e as CustomEvent<Prefs>).detail);
    window.addEventListener(SYNC, sync);
    return () => window.removeEventListener(SYNC, sync);
  }, []);
  // Larger text scales everything sized in rem (the cards are sized in pixels, so they stay put)
  useEffect(() => {
    document.documentElement.classList.toggle("large-text", prefs.largeText);
  }, [prefs.largeText]);
  return [prefs, update];
}

export const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
