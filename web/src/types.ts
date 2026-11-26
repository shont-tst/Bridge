export type Seat = "N" | "E" | "S" | "W";
export const SEATS: Seat[] = ["N", "E", "S", "W"];

export interface Meaning {
  text: string;
  alert: boolean;
  forcing: boolean;
  hcp: [number, number] | null;
}

/** Why a bot made a call: the system rule it followed; its hand and other calls it fit only once the board is over. */
export interface BotWhy {
  rule: string | null;
  convention: string | null;
  note?: string; // at rubber, how the part score changed the call ("2♥ is game for North–South, …")
  shown?: string; // everything this bot's calls have shown so far, this one included
  instead?: { call: string; text: string }[]; // calls the system tries first here, which its hand didn't fit
  hand?: { hcp: number; lengths: Record<"S" | "H" | "D" | "C", number> };
  also?: { call: string; rule: string | null; text: string }[];
}

/** How a bot picked a card it played. During the board only how it chose; once the board is over, how often that card
 * and its next best two reached its side's goal across the layouts it tried. */
export interface CardWhy {
  kind: "best" | "random" | "only" | "guess" | "hidden";
  level: number;
  samples: number;
  goal?: "make" | "beat";
  made?: number;
  tricks?: number;
  alts?: { card: string; made: number; tricks: number }[];
  equal?: number;
  softened?: boolean;
  play?: string; // what the table saw it do: led, followed, ruffed or discarded, and who won the trick
  signal?: string; // what the card told partner, at a table that plays signals, or what an opening lead shows
  led?: boolean; // an opening lead by Standard leads
}

export interface AuctionEntry {
  seat: Seat;
  call: string;
  meaning: Meaning;
  why?: BotWhy; // bots' calls only
}

export interface Contract {
  level: number;
  strain: string;
  declarer: Seat;
  doubled: number;
}

export interface Trick {
  leader: Seat;
  cards: { seat: Seat; card: string }[];
  winner?: Seat;
}

export interface DDSummary {
  tricks?: Record<string, Record<Seat, number>>;
  par_score_ns?: number;
  par_contracts?: string[];
  // rubber: par with the part scores below the line counting towards game, and this board scored the same way
  rubber?: { par_score_ns: number; par_contracts: string[]; below: { NS: number; EW: number }; score_ns: number };
  error?: string;
}

export interface CardReview {
  trick: number;
  seat: Seat;
  by: Seat;
  card: string;
  lost: number;
  best: string[];
  role: "declarer" | "defence";
  reach?: number; // tricks the side to play could still take, all cards seen
  back?: number; // tricks the other side gave straight back (netted out: the review charges `lost - back`)
  given_back?: { card: string; by: Seat; seat: Seat }; // the other side's card that gave it back
  later_back?: { card: string; by: Seat; seat: Seat; trick: number }; // the other side gave it back by the next trick (not netted)
  // judged only on what the player could see, over sampled layouts of the hidden cards.
  // tricks: the side's total it could have had with all cards seen; played/best_pct: % of layouts each card reaches it
  // (null tricks: older boards, where the % is for making or beating the contract). better: `best` was clearly better
  odds?: { goal: "make" | "beat"; samples: number; tricks?: number | null; played: number; best: string; best_pct: number; better?: boolean;
    hindsight?: string | null; hindsight_pct?: number | null }; // the best card with all cards seen, and its %
}

export interface BidReview {
  index: number;
  seat: Seat;
  call: string;
  meaning: string;
  system_call: string;
  system_meaning: string;
  minor?: boolean; // a sensible alternative the system also allows with this hand: hidden unless asked
  // the auction bid again by the system from its call, both contracts scored double dummy (server bidpath.py)
  outcome?: { system_contract: Contract | null; system_dd_ns: number; actual_dd_ns: number; bid_after?: Seat[];
    // averaged over deals of the other hands that fit what the caller could see (from 2.5 on)
    avg?: { points_ns: number; deals: number; helped: number; hurt: number } | null } | null;
}

/** The same deal played again with a level 10 bot in a person's seat and the table's bots elsewhere (server
 * game/second.py), scored against the person's result in IMPs. Scores are for that person's side. */
export interface SecondTable {
  seat: Seat;
  level: number;
  auction: AuctionEntry[];
  contract: Contract | null;
  tricks: number;
  play: [Seat, string][];
  claimed?: number; // the tricks left when a bot claimed them
  score: number;
  table_score: number;
  imps: number;
  bidding_imps?: number; // the IMPs from the two contracts, both played with every card seen
  play_imps?: number; // the rest
}

export interface BoardReview {
  bidding?: BidReview[];
  play?: { cards: CardReview[]; dd_declarer_tricks: number; lost_by: Record<Seat, number> } | null;
  second?: Partial<Record<Seat, SecondTable>>; // by the people's seats
  second_pending?: boolean;
  odds_pending?: boolean;
  odds_error?: string;
  error?: string;
}

export interface BoardResult {
  board: number;
  contract: Contract | null;
  declarer_tricks: number;
  score_ns: number;
  hands: Record<Seat, string>;
  play?: [Seat, string][]; // every card in the order played
  dd: DDSummary | null;
  review: BoardReview | null;
  claimed?: Seat | null; // the seat that claimed the last tricks
  claimed_tricks?: number | null; // how many tricks the claim took
  claim_cards?: Partial<Record<Seat, string[]>> | null; // the claiming side's cards when it claimed
  claim_played?: boolean; // the claim's cards were played out on the table for everyone to watch
  dealer?: Seat;
  vulnerability?: string;
  calls?: string[]; // the auction, from the dealer
  // the calls and cards made right after a hint or an AI coach question: index in the auction or the play
  asked?: { kind: "call" | "card"; index: number; seat: Seat; asked: ("hints" | "coach")[] }[] | null;
}

export interface TableState {
  board: number;
  step?: number; // calls and cards made so far: sent back with a call or card (see Queued in connection.ts)
  dealer: Seat;
  vulnerability: "None" | "NS" | "EW" | "Both";
  phase: "bidding" | "playing" | "done";
  hands: Record<Seat, string[] | null>;
  counts: Record<Seat, number>;
  auction: AuctionEntry[];
  turn: Seat | null;
  controller: Seat | null;
  your_turn: boolean;
  can_undo?: boolean;
  can_claim?: boolean; // you're on lead and certain to take every remaining trick
  claiming?: { by: Seat; tricks: number } | null; // a claim being played out on the table, a card at a time
  contract: Contract | null;
  legal_calls: string[];
  call_meanings: Record<string, Meaning>;
  legal_cards: string[];
  trick: Trick | null;
  last_trick: Trick | null;
  tricks_won: { NS: number; EW: number };
  result: BoardResult | null;
  dummy?: Seat;
  card_why?: Record<string, CardWhy>; // bots' cards played this board
  played?: [Seat, string][]; // a deal played again: the cards so far, for Tricks so far
}

export interface Settings {
  difficulty: number;
  conventions: string[];
  solo: boolean;
  hints: boolean;
  ai_coach: boolean; // a player's own AI assistant may see their seat during a board
  practice: string | null;
  practice_title?: string | null;
  trick_pause: number;
  undo: boolean;
  scoring: "duplicate" | "rubber";
  tutorial?: number | null; // a Learn to play table: step 6 or 7
  signals: "off" | "standard" | "upside"; // defensive signals the bots give and read
  leads: boolean; // the bots lead, and read the opening lead, by Standard leads
  replay?: ReplayInfo | null; // a deal played again, or Your mistakes
}

/** The answer to a Your mistakes puzzle, as the server judged it (game/replay.py). */
export interface PuzzleAnswer {
  kind: "card" | "call";
  right: boolean;
  right_count: number; // right answers so far, this one included
  retired: boolean; // right twice: it won't come back
  retry?: boolean; // Try again after a wrong answer: shown, never saved
  removed?: boolean; // the player chose Don't show this again: it never comes back
  // a card puzzle
  card?: string; // the card tapped
  better?: string; // the card shown as the answer: the one tapped when right, else the best on the odds
  original?: string; // the card played at the table
  seat?: Seat; // whose card it is (dummy's, when declarer plays it)
  trick?: number;
  pct?: Record<string, number>; // how often each of those cards takes `tricks` tricks
  tricks?: number | null;
  goal?: "make" | "beat" | null;
  dd?: Record<string, number>; // the tricks each takes as the cards lay
  // a bidding puzzle
  call?: string;
  meaning?: string | null;
  system_call?: string;
  system_meaning?: string | null;
  original_meaning?: string | null;
  cost?: number | null; // points the call made at the table costs (on average when `average`)
  average?: boolean;
}

/** A deal played again (Settings.replay). With `puzzles`, Your mistakes: puzzle n of `of`. */
export interface ReplayInfo {
  board: number;
  puzzles: boolean;
  n?: number;
  of?: number;
  key?: string; // the saved board the puzzle comes from
  kind?: "card" | "call";
  trick?: number | null;
  answer?: PuzzleAnswer | null;
  playing_on?: boolean; // chose Play on from here (or Play this deal again) after answering
}

/** What the server needs to play a deal again (game/replay.py's spec). */
export interface ReplaySpec {
  board: number;
  dealer: Seat;
  vulnerability: string;
  hands: Record<Seat, string>;
  calls: string[];
  play: [Seat, string][];
  seat: Seat;
  from: number; // calls and cards made for you before you take over
  conventions?: string[];
  difficulty?: number;
  signals?: string | null;
  leads?: boolean;
  below?: { NS: number; EW: number } | null;
}

export interface RubberLine {
  board: number;
  side: "NS" | "EW";
  where: "above" | "below";
  points: number;
  what: string;
}

export interface RubberState {
  number: number;
  games: { NS: number; EW: number };
  vulnerability: string;
  lines: RubberLine[];
  game_ends: number[]; // a game ended after this many lines
  totals: { NS: number; EW: number };
  finished: {
    number: number;
    NS: number;
    EW: number;
    winner: "NS" | "EW";
    // from 1.26: the board that ended it, and its whole pad
    board?: number;
    games?: { NS: number; EW: number };
    lines?: RubberLine[];
    game_ends?: number[];
  }[];
}

export type Hint =
  | { type: "hint"; phase: "bidding"; call: string; text: string; convention: string | null }
  | {
      type: "hint";
      phase: "playing";
      seat: Seat;
      card: string;
      equal: string[];
      samples: number;
      odds?: { card: string; pct: number }[]; // the hinted card and the next best, % of layouts that reach the goal
      goal?: "make" | "beat";
      extra?: { label: string; odds: { card: string; pct: number }[] }; // making is about equal: odds of one trick more ("10 tricks", "Down 2")
      signal?: string; // what the card tells partner, at a table that plays signals, or the opening lead's rule
      decision?: string; // board/decision: a firmer answer to a hint the player hid stays hidden
      firming?: boolean; // a close call: the first layouts' answer, with more layouts on the way
      firmer?: boolean; // that answer over the extra layouts, replacing the first one
    };

export interface RoomState {
  type: "state";
  room: string;
  rev?: number; // the room's update number (see the pong in connection.ts)
  you: Seat | null; // null: watching, or still picking a seat
  watching?: boolean;
  choosing?: boolean;
  pending?: Seat | null; // a watcher's seat, from the next board
  waiting?: Partial<Record<Seat, string>>; // who sits where from the next board
  watchers?: string[];
  can_skip?: boolean;
  skip_ask?: { by: Seat; name: string } | null; // a person playing as partner asked to skip this hand
  skip_no?: string | null; // your partner said no to skipping this hand
  tutorial_call?: string | null; // Learn to play step 6: the cheat sheet's call on your turn
  players: Partial<Record<Seat, string>>;
  gone?: Partial<Record<Seat, Gone>>; // people who tapped Leave or closed the app 3+ minutes ago
  connected: Partial<Record<Seat, boolean>>;
  bots: Seat[];
  settings: Settings;
  waiting_for_partner: boolean;
  next_ready?: boolean; // you tapped Next board; the deal waits for next_waiting
  next_waiting?: string[];
  table: TableState | null;
  totals: { boards: number; score_ns: number };
  rubber: RubberState | null;
  history: { board: number; contract: Contract | null; tricks: number; score_ns: number; par_ns: number | null }[];
  help?: { hints?: number; undos?: number; coach?: number }; // what you used on this board
}

export interface ConventionInfo {
  id: string;
  title: string;
  description: string;
  default_on: boolean;
  core: boolean;
  lesson: boolean;
}

export interface LessonInfo {
  id: string;
  title: string;
  description: string;
}

export interface ConventionPage extends ConventionInfo {
  explainer?: string[];
  student?: "opener" | "responder" | "doubler" | "overcaller";
  examples?: { title: string; calls: { seat: Seat; call: string; text: string; artificial: boolean }[] }[];
  // the signals and leads pages: card examples, with the card to play (by each signals method, or `play`)
  situations?: { title: string; hand: string; standard?: string; upside?: string; play?: string }[];
  practice_note?: string;
}

/** Someone at the table who left (tapped Leave) or has had the app closed for 3 minutes. */
export interface Gone {
  name: string;
  left: boolean; // tapped Leave (else: away)
  since: number; // when they went, to tell one time from the next
  bot: boolean; // a bot plays their seat until they're back
}

/** A table you still have a seat at, on the home screen's Your tables (the server's brief() in game/room.py). */
export interface TableBrief {
  room: string;
  seat: string;
  board: number; // boards dealt so far
  people: string[]; // the other people at the table
  here: string[]; // those of them with it open now
  we: number | null; // the rubber so far, your side and theirs (null: duplicate scoring)
  they: number | null;
  last: number; // when you last played there (seconds)
  lesson: string | null;
  parked?: boolean; // your bot table on another phone
  local?: boolean; // the table kept on this phone
}
