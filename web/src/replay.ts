import type { BoardResult, ReplaySpec, Seat, Settings } from "./types";

/** A finished board as the review has it: at the table, or saved to the account (hand history). */
type Finished = BoardResult & {
  conventions?: string[];
  difficulty?: number;
  signals?: string | null;
  leads?: boolean;
  below_before?: { NS: number; EW: number } | null;
};

/** What the server needs to play a finished board again from the seat you sat in (game/replay.py): from the first
 * call (`from` 0, Play this deal again) or after that many calls and cards (Play on from here). At the table its
 * settings come from the table's; a saved board keeps the ones it was played with. */
export function replaySpec(r: Finished, seat: Seat, from: number, settings?: Settings): ReplaySpec {
  return {
    board: r.board,
    dealer: r.dealer ?? "N",
    vulnerability: r.vulnerability ?? "None",
    hands: r.hands,
    calls: r.calls ?? [],
    play: r.play ?? [],
    seat,
    from,
    conventions: settings?.conventions ?? r.conventions,
    difficulty: settings?.difficulty ?? r.difficulty,
    signals: settings ? (settings.signals === "off" ? null : settings.signals) : r.signals,
    leads: settings?.leads ?? r.leads,
    below: r.below_before ?? r.dd?.rubber?.below ?? null, // at rubber, the part scores the bots bid with
  };
}
