import { useEffect, useRef } from "react";
import type { Seat } from "../types";

const ORDER: Seat[] = ["N", "E", "S", "W"];
const STAGGER = 26;
const FLIGHT = 340;

/**
 * Cards go around the table one at a time, clockwise from the dealer's left, then the fans appear.
 * Tapping anywhere ends it at once; the ☰ menu can turn it off.
 */
export default function DealAnimation({ dealer, at, onDone }: {
  dealer: Seat;
  at: Record<Seat, "top" | "left" | "right" | "bottom">; // where each seat sits on this screen
  onDone: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    const r = box.getBoundingClientRect();
    const to = {
      top: [0, -r.height / 2 + 40, 0],
      bottom: [0, r.height / 2 - 50, 0],
      left: [-r.width / 2 + 34, -20, 90],
      right: [r.width / 2 - 34, -20, 90],
    } as const;
    const first = (ORDER.indexOf(dealer) + 1) % 4;
    const anims: Animation[] = [];
    const cards: HTMLElement[] = [];
    for (let i = 0; i < 52; i++) {
      const el = document.createElement("div");
      el.className = "pc back flyer";
      el.style.zIndex = String(60 - i);
      box.appendChild(el);
      cards.push(el);
      const [x, y, rot] = to[at[ORDER[(first + i) % 4]]];
      anims.push(
        el.animate([{ transform: "translate(0, 0) rotate(0deg)" }, { transform: `translate(${x}px, ${y}px) rotate(${rot + 360}deg)` }], {
          duration: FLIGHT,
          delay: i * STAGGER,
          easing: "cubic-bezier(.25,.7,.3,1)",
          fill: "forwards",
        }),
      );
    }
    const timer = window.setTimeout(() => done.current(), 52 * STAGGER + FLIGHT + 40);
    return () => {
      window.clearTimeout(timer);
      anims.forEach((a) => a.cancel());
      cards.forEach((c) => c.remove());
    };
  }, [dealer, at]);

  return (
    <div className="deal-overlay" ref={ref} onClick={() => done.current()} />
  );
}
