import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { dummyStep } from "./Dummy";

type Fit = { scale?: number; top?: number };

/**
 * Dummy across the top in suit columns: a long suit runs down the table and can reach the trick, which would then lie
 * over dummy's lowest cards so they can't be tapped. When it would, the trick moves down (as far as your name at the
 * bottom allows), and only if that isn't enough are dummy's cards drawn smaller, so every card shows in full.
 * Returns the size to draw dummy's cards at (a fraction of w and h) and the trick's center (px from the table's top),
 * or nothing when all is clear. w and h are dummy's usual card size.
 */
export function useDummyFit(tbl: RefObject<HTMLDivElement | null>, w: number, h: number): Fit {
  const [fit, setFit] = useState<Fit>({});
  const measure = useCallback(() => {
    const el = tbl.current;
    const cols = el ? [...el.querySelectorAll<HTMLElement>(".dummy-wrap.top .dummy.columns .dcol")] : [];
    const trick = el?.querySelector<HTMLElement>(".trick-area");
    let next: Fit = {};
    if (el && cols.length && trick) {
      const n = Math.max(...cols.map((c) => c.children.length));
      const full = h + (n - 1) * dummyStep(w); // the longest column at the usual size
      const GAP = 8; // between dummy's name and the trick, and between the trick and your name
      const TOP = 4; // .dummy-wrap.top
      const name = el.querySelector<HTMLElement>(".dummy-wrap.top .seatlbl")?.offsetHeight ?? 0;
      const mine = el.querySelector<HTMLElement>(".seatlbl.bottom")?.offsetHeight ?? 0;
      const half = trick.offsetHeight / 2;
      // where the stylesheet puts the trick (offsetTop leaves out the centering transform, so it is the center)
      const was = trick.style.top;
      trick.style.top = "";
      const natural = trick.offsetTop;
      trick.style.top = was;
      const room = (center: number) => center - half - GAP - name - 2 - TOP; // for the column, above the trick
      const below = (column: number) => TOP + column + 2 + name + GAP + half; // the trick's center just below it
      const lowest = Math.max(natural, el.clientHeight - 4 - mine - GAP - half);
      if (full > room(natural)) {
        const scale = full > room(lowest) ? Math.max(0.55, room(lowest) / full) : 1;
        const center = Math.min(lowest, below(full * scale));
        next = { scale: scale < 1 ? Math.floor(scale * 100) / 100 : undefined, top: center > natural ? Math.round(center) : undefined };
      }
    }
    setFit((f) => (f.scale === next.scale && f.top === next.top ? f : next));
  }, [tbl, w, h]);
  // after every render (a card played, the hand turned) and whenever the table changes size
  useLayoutEffect(measure);
  const watched = useRef<{ el: HTMLElement; ro: ResizeObserver } | null>(null);
  useEffect(() => {
    const el = tbl.current;
    if (watched.current?.el === el) return;
    watched.current?.ro.disconnect();
    watched.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(el);
    watched.current = { el, ro };
  });
  useEffect(() => () => watched.current?.ro.disconnect(), []);
  return fit;
}
