import { useEffect, useState } from "react";
import type { Account } from "../account";
import { SEAT_NAME, partnerOf } from "../cards";
import type { AuctionEntry, BoardResult, ReplaySpec, Seat } from "../types";
import { replaySpec } from "../replay";
import AuctionView from "./AuctionView";
import PlayView from "./PlayView";
import ResultPanel from "./ResultPanel";

/** A board saved to the account, as /api/me/boards/{key} sends it. */
export type SavedRecord = BoardResult & {
  seat?: Seat;
  players?: Record<string, string>;
  help?: Record<string, { hints?: number; undos?: number; coach?: number }>;
  auction?: AuctionEntry[];
  conventions?: string[];
  difficulty?: number;
  signals?: string | null;
  leads?: boolean;
  below_before?: { NS: number; EW: number } | null;
  finished_at?: number;
};

/** A saved board's result and review, as hand history shows it. With `onReplay`, the review offers Play on from
 * here and Play this deal again. */
export function SavedBoardPanel({ rec, seat, title, onReplay }: {
  rec: SavedRecord;
  seat: Seat;
  title: string;
  onReplay?: (spec: ReplaySpec) => void;
}) {
  const names = rec.players ?? {};
  const nameOf = (s: Seat) => (s === seat ? "You" : names[s] ?? `Bot ${SEAT_NAME[s]}`);
  return (
    <ResultPanel
      result={rec}
      me={seat}
      nameOf={nameOf}
      help={rec.help?.[seat]}
      auction={rec.auction?.length ? <AuctionView auction={rec.auction} dealer={rec.dealer ?? "N"} turn={null} room="" board={0} /> : undefined}
      play={rec.play?.length ? (
        <PlayView play={rec.play} whys={{}} dummy={rec.contract ? partnerOf(rec.contract.declarer) : undefined} contract={rec.contract} room="" board={0} />
      ) : undefined}
      title={title}
      onReplay={onReplay && ((from) => onReplay(replaySpec(rec, seat, from)))}
    />
  );
}

/** One saved board on a page of its own, from Your mistakes' "See the whole board". */
export function SavedBoardPage({ account, boardKey, back, onClose }: {
  account: Account;
  boardKey: string;
  back: string;
  onClose: () => void;
}) {
  const [rec, setRec] = useState<SavedRecord | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    account.call<SavedRecord>(`/api/me/boards/${encodeURIComponent(boardKey)}`).then(setRec, (e) => setErr(e.message));
    window.scrollTo(0, 0);
  }, [account, boardKey]);
  const when = rec?.finished_at ? new Date(rec.finished_at * 1000).toLocaleDateString(undefined, { month: "long", day: "numeric" }) : "";
  return (
    <div className="stats-page">
      <div className="stats-top board-nav">
        <button className="link" onClick={onClose}>
          ‹ {back}
        </button>
      </div>
      {err && <p className="error">{err}</p>}
      {rec && <SavedBoardPanel rec={rec} seat={rec.seat ?? "S"} title={`Board ${rec.board}${when ? ` · ${when}` : ""}`} />}
    </div>
  );
}
