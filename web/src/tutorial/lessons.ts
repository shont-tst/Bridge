/** The Learn to play course: the steps, their hands, and the tips for players who know another card game. */
import type { Seat } from "../types";
import DEALS from "./deals.json";
import { balanced, hcp, pickTrump, type Hands } from "./play";

const h = (cards: string) => cards.split(" ");

/** A hand written out in full, with every card face up. */
export interface SetHand {
  title: string;
  intro: string; // one sentence before the first card
  hands: Hands;
  trump: string; // "N": no trumps
  leader: Seat;
  script?: Partial<Record<Seat, string[]>>; // cards a bot plays first when it can, so the hand shows its idea
  remember: string;
}

/** A full deal found to fit, played with no bidding: the side with more points declares. */
export interface MiniHand {
  title: string;
  intro: string;
  test: (h: Hands) => boolean;
  remember: string;
}

/** Lesson ideas the coach checks for (see lessonSpot in Tutorial.tsx). */
export type Rule = "finesse" | "ruff" | "sequence" | "second" | "third" | "return";

/** One of the deals in deals.json, found and checked with the double-dummy solver (server/scripts/tutorial_deals.py). */
export interface FixedDeal {
  hands: Record<Seat, string>;
  declarer: Seat;
  trump: string;
  needed: number;
}

/** A lesson played on a fixed deal: declarer, trumps and the tricks needed come with it. One of its deals is picked. */
export interface DealHand {
  title: string;
  intro: string;
  deals: FixedDeal[];
  rules: Rule[];
  quiz?: boolean; // ask "How many sure winners?" before the first card
  remember: string;
}

export interface Step {
  n: number;
  title: string;
  blurb: string;
  set?: SetHand[];
  mini?: MiniHand[];
  deal?: DealHand[];
  table?: boolean; // played at a real table with bots (steps 6 and 7)
  remember: string; // the one thing to take away, at the end of the step
}

const deals = (key: string) => (DEALS as unknown as Record<string, FixedDeal[]>)[key];

const ns = (d: Hands) => hcp(d.N) + hcp(d.S);
const ew = (d: Hands) => hcp(d.E) + hcp(d.W);

export const STEPS: Step[] = [
  {
    n: 1,
    title: "Tricks",
    blurb: "Follow suit; the highest card wins",
    remember: "Follow suit when you can. The highest card of the suit led wins, and partner's tricks count for you too.",
    set: [
      {
        title: "Highest wins",
        intro: "Each player plays one card. The highest card of the suit led wins the trick.",
        hands: { N: h("S6 H7 DQ C5"), E: h("SQ HA D4 C9"), S: h("SA HK DA CK"), W: h("SJ H2 DK C8") },
        trump: "N",
        leader: "S",
        remember: "An ace beats a king, a king beats a queen, and so on down to the 2.",
      },
      {
        title: "Can't follow",
        intro: "You must play the suit that was led if you can. With none left, play any card, but it can't win.",
        hands: { N: h("S3 H5 D7 C2"), E: h("SA H4 D3 CQ"), S: h("S4 H6 D2 CK"), W: h("SQ HA DA HK") },
        trump: "N",
        leader: "S",
        script: { W: ["DA"] },
        remember: "Only a card of the suit led can win the trick, even an ace of another suit can't.",
      },
      {
        title: "Partner's tricks count",
        intro: "North is your partner. A trick either of you wins counts for your side.",
        hands: { N: h("SA HA D2 C3"), E: h("SK H4 D5 C6"), S: h("S2 H3 DA CA"), W: h("SQ HK DK CK") },
        trump: "N",
        leader: "S",
        remember: "When partner's card already wins the trick, play a low card and save your winners.",
      },
    ],
  },
  {
    n: 2,
    title: "Trumps",
    blurb: "A trump beats any other suit",
    remember: "Draw the other side's trumps first, so they can't ruff your winners.",
    set: [
      {
        title: "Ruff",
        intro: "Hearts are trumps. When you can't follow suit, a heart beats any card of another suit.",
        hands: { N: h("SK S7 CQ D3"), E: h("SJ H9 CK D8"), S: h("SA SQ H2 C5"), W: h("DA S5 H6 CJ") },
        trump: "H",
        leader: "W",
        script: { W: ["DA"], N: ["D3"], E: ["D8"] },
        remember: "Even the smallest trump beats an ace of another suit. That's called a ruff.",
      },
      {
        title: "Draw trumps",
        intro: "Hearts are trumps. Lead your hearts first, so East has none left to ruff with.",
        hands: { N: h("S5 S4 D6 D5 C3"), E: h("H4 H3 SK SQ D9"), S: h("HA HK HQ CA S2"), W: h("CK CQ CJ D8 D7") },
        trump: "H",
        leader: "S",
        script: { W: ["D7", "D8"] },
        remember: "Leading trumps pulls the other side's trumps out. Then your other winners are safe.",
      },
      {
        title: "Overruff",
        intro: "Hearts are trumps. When two players ruff, the higher trump wins.",
        hands: { N: h("D4 D3 S7 C6"), E: h("H5 SK CK CQ"), S: h("H9 H2 SA CA"), W: h("DA DK SQ CJ") },
        trump: "H",
        leader: "N",
        script: { N: ["D4"], E: ["H5"] },
        remember: "A higher trump beats a lower one, so you can overruff.",
      },
      {
        title: "No trumps",
        intro: "The same cards as before, but this time there are no trumps. Nobody can ruff.",
        hands: { N: h("S5 S4 D6 D5 C3"), E: h("H4 H3 SK SQ D9"), S: h("HA HK HQ CA S2"), W: h("CK CQ CJ D8 D7") },
        trump: "N",
        leader: "S",
        remember: "With no trumps, the highest card of the suit led always wins.",
      },
    ],
  },
  {
    n: 3,
    title: "Minibridge",
    blurb: "Count points and play full hands",
    remember: "Count your sure winners before you play to the first trick.",
    mini: [
      {
        title: "Count your winners",
        intro: "Count your points: A 4, K 3, Q 2, J 1. The side with more points plays the hand.",
        test: (d) => hcp(d.S) >= 15 && hcp(d.S) <= 17 && balanced(d.S) && ns(d) >= 25 && hcp(d.S) > hcp(d.N) && pickTrump(d.S, d.N) === "N",
        remember: "Count your sure winners first. Cash them once you know you have enough.",
      },
      {
        title: "Pick trumps",
        intro: "You and North hold lots of hearts this time. A long suit together makes a good trump suit.",
        test: (d) => ns(d) >= 22 && hcp(d.S) > hcp(d.N) && pickTrump(d.S, d.N) === "H",
        remember: "Eight or more cards in a suit between you and dummy makes a good trump suit.",
      },
      {
        title: "You're dummy",
        intro: "North has more points than you, so North plays the hand and your cards go face up.",
        test: (d) => ns(d) >= 22 && hcp(d.N) > hcp(d.S),
        remember: "Dummy puts their cards down, and declarer plays them.",
      },
      {
        title: "Defend",
        intro: "East and West have more points, so they play the hand. You lead first.",
        test: (d) => ew(d) >= 22 && hcp(d.E) > hcp(d.W),
        remember: "Lead from your longest suit. Its small cards can win tricks once the high ones are gone.",
      },
      {
        title: "Go for game",
        intro: "Your side has 25 points or more. That's enough to try for game.",
        test: (d) => ns(d) >= 25 && hcp(d.S) > hcp(d.N),
        remember: "With 25 points together, try for game: 9 tricks with no trumps, 10 in ♥ or ♠, 11 in ♦ or ♣.",
      },
    ],
  },
  {
    n: 4,
    title: "Declarer",
    blurb: "Count winners, set up a suit, finesse",
    remember: "Count your sure winners first. Then find the rest: set up a long suit, take a finesse, or ruff in dummy.",
    deal: [
      {
        title: "Count your winners",
        intro: "You're declarer. Before you play, count the tricks you can take right away.",
        deals: deals("4.1"),
        rules: [],
        quiz: true,
        remember: "Count your sure winners first. When you have enough, take them.",
      },
      {
        title: "Set up a long suit",
        intro: "You're a trick or two short. Your long suit can make extra tricks once the other side's high cards are gone.",
        deals: deals("4.2"),
        rules: [],
        remember: "Give up a trick early in your long suit. Its small cards win later.",
      },
      {
        title: "Finesse",
        intro: "You have the A and Q of a suit, and the K is missing. Lead a small card from dummy toward them.",
        deals: deals("4.3"),
        rules: ["finesse"],
        remember: "Lead toward the card you hope will win. If East has the K, your Q wins.",
      },
      {
        title: "Ruff in dummy",
        intro: "Dummy is short in one suit. Ruff your losers there before you draw all the trumps.",
        deals: deals("4.4"),
        rules: ["ruff"],
        remember: "Ruff losers in dummy, the hand with fewer trumps, before you draw trumps.",
      },
      {
        title: "Put it together",
        intro: "Count your winners, then find a way to make the rest.",
        deals: deals("4.5"),
        rules: ["finesse", "ruff"],
        quiz: true,
        remember: "Make a plan before the first card: count, then find the extra tricks.",
      },
    ],
  },
  {
    n: 5,
    title: "Defense",
    blurb: "Opening leads, second hand low",
    remember: "Lead the top of touching honors, play second hand low and third hand high, and return partner's suit.",
    deal: [
      {
        title: "Opening lead",
        intro: "East plays the hand and you lead. With three touching honors, like K Q J, lead the top one.",
        deals: deals("5.1"),
        rules: ["sequence"],
        remember: "From touching honors, lead the top card. It pushes out their high cards and keeps yours safe.",
      },
      {
        title: "Second hand low",
        intro: "When declarer leads a small card and you play next, play low. Partner plays after dummy.",
        deals: deals("5.2"),
        rules: ["second"],
        remember: "Second hand low: save your high cards to beat theirs.",
      },
      {
        title: "Third hand high",
        intro: "West plays the hand and North leads. When partner leads a small card, play your highest.",
        deals: deals("5.3"),
        rules: ["third"],
        remember: "Third hand high: win the trick, or make declarer use a high card to beat you.",
      },
      {
        title: "Return partner's suit",
        intro: "North leads again. When you get the lead, lead back the suit partner led.",
        deals: deals("5.4"),
        rules: ["third", "return"],
        remember: "Return partner's suit. Partner led it for a reason.",
      },
    ],
  },
  {
    n: 6,
    title: "Bidding",
    blurb: "Opening bids from the No Fear cheat sheet",
    table: true,
    remember: "Open with 12 or more points: a five-card major first, 1NT with 15 to 17 balanced, else your longer minor.",
  },
  {
    n: 7,
    title: "Scoring",
    blurb: "Games, part scores and rubber",
    table: true,
    remember: "100 below the line wins a game, and two games win the rubber. Everything else goes above the line.",
  },
];

/** Steps built so far; the rest show as Coming soon. */
export const READY = STEPS.filter((s) => s.set || s.mini || s.deal || s.table).map((s) => s.n);

/** Step 6's hands, one per opening lesson (the server deals them in this order: bridge/tutorial.py). */
export const BIDDING_HANDS = 5;

export const GAMES = ["Hearts", "Spades", "Oh Hell", "Euchre", "Pinochle"] as const;

/** Steps a player already knows from another game. */
export const KNOWS: Record<string, number[]> = {
  Hearts: [1],
  Spades: [1, 2],
  "Oh Hell": [1, 2],
  Euchre: [1],
  Pinochle: [1],
};

/** How bridge works: the page before the steps, read once (and again from the steps page). */
export const BASICS: { head: string; text: string }[] = [
  { head: "Partners", text: "Four players in two partnerships. Your partner sits across from you." },
  { head: "Tricks", text: "Each player gets 13 cards. Everyone plays one card to each trick, and the highest card of the suit led wins it." },
  { head: "The auction", text: "Before the play, both sides bid. The highest bid says how many tricks that side promises, and which suit is trumps, or no trumps." },
  { head: "Declarer and dummy", text: "One player on that side, the declarer, plays both hands: their own and partner's, which goes face up as dummy." },
  { head: "Scoring", text: "Make what you promised and you score points. Go down and the other side scores. Two games win a rubber." },
];

/** One line for each game a player knows: what's the same in bridge, and what isn't. */
export const COMPARE: Record<string, string> = {
  Spades: "Like Spades, you bid tricks with a partner. But trumps aren't always ♠: the auction picks the suit, or no trumps.",
  Hearts: "Tricks work just as in Hearts, but here you want to win them, and you play with a partner.",
  "Oh Hell": "Like Oh Hell, you bid tricks and then try to make them. But only the side that wins the auction has a target to make.",
  Euchre: "Like Euchre, you play with a partner and bidding picks trumps. But you use all 52 cards, and there are no bowers.",
  Pinochle: "Like Pinochle, you play with a partner and bid for trumps. But it's one ordinary deck, with no melds.",
};

export type TipWhen = "start" | "trumps" | "nt" | "over" | "follow";

/** One tip per game, shown once, the first time its idea comes up. */
export const TIPS: { game: string; when: TipWhen; text: string }[] = [
  { game: "Hearts", when: "start", text: "Coming from Hearts? Here you want to win tricks, not dodge them." },
  { game: "Euchre", when: "trumps", text: "Coming from Euchre? A jack is just a jack: no bowers, and the ace is the top trump." },
  { game: "Spades", when: "nt", text: "Coming from Spades? With no trumps, a high spade is just a high spade." },
  { game: "Oh Hell", when: "over", text: "Coming from Oh Hell? Extra tricks are a bonus here, not a bust." },
  { game: "Pinochle", when: "follow", text: "Coming from Pinochle? You don't have to beat the card led. Play low when you can't win." },
];

export function knownSteps(games: string[]): number[] {
  return [...new Set(games.flatMap((g) => KNOWS[g] ?? []))].sort();
}
