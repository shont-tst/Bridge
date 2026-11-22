/**
 * Card play for Learn to play, all in the app: no server, no bidding, no scoring. Hands can be short (steps 1 and 2
 * use 3 to 5 cards). The bots here are simple on purpose, about level 1 to 2, and only use what their seat can see:
 * their own hand, dummy once it's down, and the cards already played.
 */
import type { Seat } from "../types";

export const SEATS: Seat[] = ["N", "E", "S", "W"];
export const RANKS = "23456789TJQKA";
export const SUIT_NAMES: Record<string, string> = { S: "spades", H: "hearts", D: "diamonds", C: "clubs" };
export const SUIT_ONE: Record<string, string> = { S: "spade", H: "heart", D: "diamond", C: "club" };
export const SEAT_NAMES: Record<Seat, string> = { N: "North", E: "East", S: "South", W: "West" };

export type Hands = Record<Seat, string[]>;
export interface Played {
  seat: Seat;
  card: string;
}
export interface TrickT {
  leader: Seat;
  cards: Played[];
  winner?: Seat;
}

export const next = (s: Seat): Seat => SEATS[(SEATS.indexOf(s) + 1) % 4];
export const partner = (s: Seat): Seat => SEATS[(SEATS.indexOf(s) + 2) % 4];
export const sameSide = (a: Seat, b: Seat) => a === b || partner(a) === b;
export const rank = (c: string) => RANKS.indexOf(c[1]);
export const hcpOf = (c: string) => Math.max(0, rank(c) - 8); // J 1, Q 2, K 3, A 4
export const hcp = (cards: string[]) => cards.reduce((n, c) => n + hcpOf(c), 0);
export const suitOf = (cards: string[], s: string) => cards.filter((c) => c[0] === s);
const high = (cards: string[]) => [...cards].sort((a, b) => rank(b) - rank(a));
const low = (cards: string[]) => [...cards].sort((a, b) => rank(a) - rank(b));

/** The cards a seat may play: it must follow the suit led if it can. */
export function legal(hand: string[], trick: TrickT | null): string[] {
  const led = trick?.cards[0]?.card[0];
  if (!led) return hand;
  const follow = suitOf(hand, led);
  return follow.length ? follow : hand;
}

/** Whether card `a` beats card `b` in a trick where `led` was led. */
export function beats(a: string, b: string, led: string, trump: string): boolean {
  if (a[0] === b[0]) return rank(a) > rank(b);
  if (a[0] === trump) return true;
  if (b[0] === trump) return false;
  return a[0] === led && b[0] !== led;
}

export function winning(cards: Played[], trump: string): Played {
  const led = cards[0].card[0];
  return cards.reduce((best, p) => (beats(p.card, best.card, led, trump) ? p : best));
}

/**
 * Whether `card`, played now by `seat`, takes the trick for its side whatever the seats still to play hold.
 * Only used where all four hands are known (face-up steps, and the end of a trick).
 */
export function wins(card: string, seat: Seat, trick: TrickT, hands: Hands, trump: string): boolean {
  const cards = [...trick.cards, { seat, card }];
  const led = cards[0].card[0];
  const best = winning(cards, trump);
  if (best.seat !== seat) return false;
  let s = next(seat);
  for (let i = cards.length; i < 4; i++, s = next(s)) {
    if (sameSide(s, seat)) continue;
    const opts = legal(hands[s], { leader: trick.leader, cards });
    if (opts.some((c) => beats(c, card, led, trump))) return false;
  }
  return true;
}

/** Whether `seat`'s side is already sure to take this trick (all hands known). */
export function sideHasIt(seat: Seat, trick: TrickT, hands: Hands, trump: string): boolean {
  if (!trick.cards.length) return false;
  const best = winning(trick.cards, trump);
  if (!sameSide(best.seat, seat) || best.seat === seat) return false;
  const led = trick.cards[0].card[0];
  let s = next(seat);
  for (let i = trick.cards.length + 1; i < 4; i++, s = next(s)) {
    if (sameSide(s, seat)) continue;
    if (legal(hands[s], trick).some((c) => beats(c, best.card, led, trump))) return false;
  }
  return true;
}

/** What one seat can see: its hand, dummy (once down) and the cards played so far. */
export interface View {
  seat: Seat;
  hand: string[];
  dummy: { seat: Seat; cards: string[] } | null;
  played: Set<string>;
  trick: TrickT;
  trump: string; // "N" for no trumps
  declarer: Seat | null;
}

/** The highest card of a suit still out (not played, not in this seat's hand or dummy), or null. */
function topOut(view: View, suit: string): number {
  const seen = new Set([...view.played, ...view.hand, ...(view.dummy?.cards ?? [])]);
  for (let r = RANKS.length - 1; r >= 0; r--) if (!seen.has(suit + RANKS[r])) return r;
  return -1;
}

/** A card that can't be beaten by any card still out in its own suit. */
export const masterOf = (view: View, c: string) => rank(c) > topOut(view, c[0]);

function trumpsOut(view: View): number {
  if (view.trump === "N") return 0;
  const seen = [...view.played, ...view.hand, ...(view.dummy?.cards ?? [])].filter((c) => c[0] === view.trump).length;
  return 13 - seen;
}

/** A simple bot's card: cash winners, draw trumps as declarer, second hand low, third hand high, win cheaply. */
export function botCard(view: View): string {
  const { hand, trick, trump } = view;
  const opts = legal(hand, trick);
  if (opts.length === 1) return opts[0];
  if (!trick.cards.length) return lead(view, opts);
  const led = trick.cards[0].card[0];
  const best = winning(trick.cards, trump);
  const partnerWinning = sameSide(best.seat, view.seat);
  const last = trick.cards.length === 3;
  const winners = low(opts.filter((c) => beats(c, best.card, led, trump)));
  const lowest = low(opts)[0];
  const following = opts[0][0] === led;
  if (partnerWinning && (last || masterOf(view, best.card))) return discard(view, opts);
  if (!winners.length) return following ? lowest : discard(view, opts);
  if (trick.cards.length === 1 && following && !masterOf(view, winners[winners.length - 1])) return lowest; // second hand low
  // win as cheaply as is safe: last to play takes the lowest winner, otherwise a card nobody left can beat if there is one
  if (last) return winners[0];
  const safe = winners.filter((c) => c[0] !== trump || led === trump ? masterOf(view, c) : true);
  return safe[0] ?? winners[winners.length - 1];
}

function lead(view: View, opts: string[]): string {
  const declaring = view.declarer !== null && sameSide(view.declarer, view.seat);
  const trump = view.trump;
  const ours = opts.filter((c) => c[0] === trump);
  if (declaring && ours.length && trumpsOut(view) > 0) return high(ours)[0]; // draw trumps
  const masters = high(opts.filter((c) => masterOf(view, c) && (c[0] !== trump || declaring)));
  if (masters.length && (declaring || trump === "N" || trumpsOut(view) === 0 || masters.some((c) => c[0] !== trump))) {
    return masters.find((c) => c[0] !== trump) ?? masters[0];
  }
  // otherwise from the longest side suit: top of two touching honors, else a low card
  const suits = ["S", "H", "D", "C"].filter((s) => s !== trump && suitOf(opts, s).length);
  const pool = suits.length ? suits : ["S", "H", "D", "C"].filter((s) => suitOf(opts, s).length);
  const suit = pool.sort((a, b) => suitOf(opts, b).length - suitOf(opts, a).length)[0];
  const cards = high(suitOf(opts, suit));
  if (cards.length > 1 && rank(cards[0]) >= 9 && rank(cards[0]) - rank(cards[1]) === 1) return cards[0];
  return cards[cards.length - 1];
}

function discard(view: View, opts: string[]): string {
  // the lowest card of the suit least worth keeping: not trumps, not a winner
  const plain = opts.filter((c) => c[0] !== view.trump);
  const pool = plain.length ? plain : opts;
  return low(pool).sort((a, b) => Number(masterOf(view, a)) - Number(masterOf(view, b)) || rank(a) - rank(b))[0];
}

/** Sure tricks off the top in declarer's and dummy's hands together: A, AK, AKQ … in each suit. */
export function topTricks(a: string[], b: string[]): number {
  let total = 0;
  for (const s of "SHDC") {
    const both = new Set([...suitOf(a, s), ...suitOf(b, s)].map((c) => rank(c)));
    const longest = Math.max(suitOf(a, s).length, suitOf(b, s).length);
    let n = 0;
    for (let r = 12; r >= 0 && both.has(r); r--) n++;
    total += Math.min(n, longest);
  }
  return total;
}

/** The trump suit a pair should pick: their longest suit with 8 or more cards together (a major on a tie), else no trumps. */
export function pickTrump(a: string[], b: string[]): string {
  const fits = ["S", "H", "D", "C"]
    .map((s) => ({ s, n: suitOf(a, s).length + suitOf(b, s).length }))
    .filter((f) => f.n >= 8)
    .sort((x, y) => y.n - x.n);
  return fits[0]?.s ?? "N";
}

/** Tricks needed: game (9 in no trumps, 10 in ♥ or ♠, 11 in ♦ or ♣) with 25 or more points together, else 7. */
export function target(trump: string, points: number): number {
  if (points < 25) return 7;
  return trump === "N" ? 9 : "HS".includes(trump) ? 10 : 11;
}

/** A random deal, as hands of 13. */
export function deal(rand: () => number = Math.random): Hands {
  const deck: string[] = [];
  for (const s of "SHDC") for (const r of RANKS) deck.push(s + r);
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return { N: deck.slice(0, 13), E: deck.slice(13, 26), S: deck.slice(26, 39), W: deck.slice(39) };
}

export const balanced = (cards: string[]) => {
  const lens = "SHDC".split("").map((s) => suitOf(cards, s).length).sort((a, b) => a - b);
  return lens[0] >= 2 && lens.filter((n) => n === 2).length <= 1 && lens[3] <= 5;
};

/** A deal that passes `test`, found by dealing until one does. */
export function dealWhere(test: (h: Hands) => boolean, rand: () => number = Math.random): Hands {
  for (let i = 0; i < 20000; i++) {
    const h = deal(rand);
    if (test(h)) return h;
  }
  return deal(rand);
}
