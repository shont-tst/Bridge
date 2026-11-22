import { useCallback, useEffect, useState } from "react";
import type { Account } from "../account";

/** Learn to play progress: kept on this phone, and on the account too when signed in, so it follows the player. */
export interface Progress {
  games: string[] | null; // the card games they know; null until they've answered
  done: number[]; // steps finished
  tips: string[]; // "Coming from …?" tips already shown (this phone only)
}

const KEY = "bridge-tutorial";

function load(): Progress {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) || "{}");
    return { games: Array.isArray(p.games) ? p.games : null, done: Array.isArray(p.done) ? p.done : [], tips: Array.isArray(p.tips) ? p.tips : [] };
  } catch {
    return { games: null, done: [], tips: [] };
  }
}

function keep(p: Progress) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* private mode: kept until the app is closed */
  }
}

export function useProgress(account: Account) {
  const [p, setP] = useState<Progress>(load);
  const signedIn = !!account.user;
  const update = useCallback(
    (change: Partial<Progress>, send?: { games?: string[]; done?: number[] }) => {
      setP((old) => {
        const next = { ...old, ...change };
        keep(next);
        return next;
      });
      if (send && signedIn) account.call("/api/me/tutorial", send).catch(() => {});
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signedIn, account.token],
  );
  // signed in: what the account has wins for the games; finished steps from both are kept
  useEffect(() => {
    if (!signedIn) return;
    account
      .call<{ games: string[] | null; done: number[] }>("/api/me/tutorial")
      .then((t) => {
        setP((old) => {
          const done = [...new Set([...old.done, ...t.done])].sort();
          const games = t.games ?? old.games;
          const next = { ...old, games, done };
          keep(next);
          if (done.length !== t.done.length || (t.games === null && games)) {
            account.call("/api/me/tutorial", { games: games ?? undefined, done }).catch(() => {});
          }
          return next;
        });
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn, account.token]);

  return {
    ...p,
    setGames: (games: string[]) => update({ games }, { games }),
    finish: (n: number) => update({ done: [...new Set([...p.done, n])].sort() }, { done: [n] }),
    sawTip: (text: string) => update({ tips: [...p.tips, text] }),
  };
}
