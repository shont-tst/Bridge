import type { Seat } from "./types";

export const SUIT_SYMBOL: Record<string, string> = { S: "♠", H: "♥", D: "♦", C: "♣", N: "NT" };
export const SUIT_ORDER = ["S", "H", "D", "C"];
export const RANKS = "23456789TJQKA";

export function rankLabel(card: string): string {
  return card[1] === "T" ? "10" : card[1];
}

export function isRed(suit: string): boolean {
  return suit === "H" || suit === "D";
}

export function sortCards(cards: string[]): string[] {
  return [...cards].sort(
    (a, b) => SUIT_ORDER.indexOf(a[0]) - SUIT_ORDER.indexOf(b[0]) || RANKS.indexOf(b[1]) - RANKS.indexOf(a[1]),
  );
}

export function callLabel(call: string): string {
  if (call === "P") return "Pass";
  if (call === "X") return "Dbl";
  if (call === "XX") return "Rdbl";
  return call[0] + SUIT_SYMBOL[call[1]];
}

/** Rotate so `me` sits at the bottom: returns seats for [bottom, left, top, right]. */
export function compass(me: Seat): { bottom: Seat; left: Seat; top: Seat; right: Seat } {
  const order: Seat[] = ["N", "E", "S", "W"];
  const i = order.indexOf(me);
  return { bottom: me, left: order[(i + 1) % 4], top: order[(i + 2) % 4], right: order[(i + 3) % 4] };
}

export const SEAT_NAME: Record<Seat, string> = { N: "North", E: "East", S: "South", W: "West" };

export function contractLabel(c: { level: number; strain: string; declarer: Seat; doubled: number } | null): string {
  if (!c) return "Passed out";
  return `${c.level}${SUIT_SYMBOL[c.strain]}${c.doubled === 2 ? "XX" : c.doubled === 1 ? "X" : ""} by ${SEAT_NAME[c.declarer]}`;
}

/** A score with its sign: +150, −50 (a real minus, as in the review). */
export function signed(n: number): string {
  return n > 0 ? `+${n}` : n < 0 ? `−${-n}` : `${n}`;
}

/**
 * The solver's par contracts ("3NTE+2", "4♠Nx-3") in the words the rest of the app uses:
 * "3NT by East or West +2" (just made: no "="). Anything it can't read is shown as it came.
 */
export function parLabel(codes: string[]): string {
  const groups = new Map<string, Seat[]>();
  const odd: string[] = [];
  for (const code of codes) {
    const m = code.match(/^(\d)(NT|[♠♥♦♣])([NESW])(x{0,2})(=|[+-]\d+)$/);
    if (!m) {
      odd.push(code);
      continue;
    }
    const result = m[5] === "=" ? "=" : m[5][0] === "-" ? `−${m[5].slice(1)}` : m[5];
    const key = `${m[1]}${m[2]}${m[4].toUpperCase()}|${result}`;
    groups.set(key, [...(groups.get(key) ?? []), m[3] as Seat]);
  }
  return [
    ...[...groups].map(([key, seats]) => {
      const [contract, result] = key.split("|");
      return `${contract} by ${seats.map((s) => SEAT_NAME[s]).join(" or ")}${result === "=" ? "" : ` ${result}`}`;
    }),
    ...odd,
  ].join(", ");
}

export function cardLabel(card: string): string {
  return SUIT_SYMBOL[card[0]] + rankLabel(card);
}

/** A held hand alternates colors: spades, hearts, clubs, diamonds; high to low. */
export const FAN_ORDER = ["S", "H", "C", "D"];

/** Once there's a trump suit it goes on the left, and the colors still alternate (♥ trumps: ♥ ♠ ♦ ♣). */
export function fanOrder(trump?: string): string[] {
  if (!trump || !"SHDC".includes(trump)) return FAN_ORDER;
  const [same, other] = isRed(trump) ? [["H", "D"], ["S", "C"]] : [["S", "C"], ["H", "D"]];
  return [trump, other[0], same.find((s) => s !== trump)!, other[1]];
}

export function sortFan(cards: string[], trump?: string): string[] {
  const order = fanOrder(trump);
  return [...cards].sort(
    (a, b) => order.indexOf(a[0]) - order.indexOf(b[0]) || RANKS.indexOf(b[1]) - RANKS.indexOf(a[1]),
  );
}

export function partnerOf(s: Seat): Seat {
  return ({ N: "S", S: "N", E: "W", W: "E" } as const)[s];
}

export function sameSide(a: Seat, b: Seat): boolean {
  return a === b || partnerOf(a) === b;
}

/** Your own point count, as on the cheat sheet. Shortness counts 3/2/1 before a fit and 5/3/1 once there is one. */
export function handPoints(cards: string[], fit: boolean) {
  const HC: Record<string, number> = { A: 4, K: 3, Q: 2, J: 1 };
  const hcp = cards.reduce((t, c) => t + (HC[c[1]] ?? 0), 0);
  const len: Record<string, number> = { S: 0, H: 0, D: 0, C: 0 };
  cards.forEach((c) => len[c[0]]++);
  const suits = Object.keys(len);
  const length = suits.reduce((t, s) => t + Math.max(0, len[s] - 4), 0);
  const short = suits.reduce((t, s) => t + (len[s] === 0 ? (fit ? 5 : 3) : len[s] === 1 ? (fit ? 3 : 2) : len[s] === 2 ? 1 : 0), 0);
  return {
    hcp,
    length,
    short,
    longSuits: suits.filter((s) => len[s] > 4),
    shortSuits: suits.filter((s) => len[s] < 3),
    len,
  };
}

/** The cheat sheet's contract limit guide, in total points. */
export function pointsNeeded(call: string): number {
  const l = Number(call[0]);
  const s = call[1];
  const minor = s === "C" || s === "D";
  if (l === 7) return s === "N" ? 37 : 35;
  if (l === 6) return s === "N" ? 33 : 31;
  if (l === 5) return minor ? 29 : 25;
  if (l === 4) return minor ? 24 : 25;
  if (l === 3) return s === "N" ? 25 : 23;
  return l === 2 ? 21 : 19;
}
