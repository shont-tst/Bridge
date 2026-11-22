import { SUIT_SYMBOL, callLabel, handPoints, partnerOf, pointsNeeded } from "../cards";
import type { AuctionEntry, Seat } from "../types";
import SuitText from "./SuitText";

/** A strain both partners have bid naturally, or partner's natural major when you hold three of it. */
export function findFit(auction: AuctionEntry[], me: Seat, cards: string[]): string | null {
  const natural = (s: Seat) =>
    auction.filter((e) => e.seat === s && /^[1-7][SHDC]$/.test(e.call) && !e.meaning.alert).map((e) => e.call[1]);
  const mine = natural(me);
  const theirs = natural(partnerOf(me));
  const both = theirs.find((s) => mine.includes(s));
  if (both) return both;
  return theirs.find((s) => (s === "H" || s === "S") && cards.filter((c) => c[0] === s).length >= 3) ?? null;
}

/** What partner's calls have shown, in HCP: the overlap of their ranges, or the latest if they don't overlap. */
export function partnerRange(auction: AuctionEntry[], me: Seat): [number, number] | null {
  const ranges = auction.filter((e) => e.seat === partnerOf(me) && e.meaning.hcp).map((e) => e.meaning.hcp!);
  if (!ranges.length) return null;
  const lo = Math.max(...ranges.map((r) => r[0]));
  const hi = Math.min(...ranges.map((r) => r[1]));
  return lo <= hi ? [lo, hi] : ranges[ranges.length - 1];
}

/** Your own point count while you bid. Shown only on your phone: it's worked out from your hand here. */
export default function PointsPanel({ cards, auction, me, partnerName, target, detail, onDetail }: {
  cards: string[];
  auction: AuctionEntry[];
  me: Seat;
  partnerName: string;
  target: string | null; // the bid being looked at, if any
  detail: boolean; // spelled out, or just "HCP / long / short"
  onDetail: (on: boolean) => void;
}) {
  const fit = findFit(auction, me, cards);
  const p = handPoints(cards, !!fit);
  const sym = (ss: string[]) => ss.map((s) => SUIT_SYMBOL[s]).join("");
  const mine = p.hcp + (fit ? p.short : p.length);
  const goal = target && /^[1-7]/.test(target) ? target : fit ? (fit === "H" || fit === "S" ? `4${fit}` : `5${fit}`) : "3N";
  const need = pointsNeeded(goal);
  const range = partnerRange(auction, me);
  const lo = mine + (range?.[0] ?? 0);
  const hi = mine + (range?.[1] ?? 0);
  const verdict = !range ? null : lo >= need ? "enough" : hi >= need ? "borderline" : "short";

  return (
    <div className="points">
      {!detail ? (
        <button
          type="button"
          className="pts-compact"
          onClick={() => onDetail(true)}
          aria-label={`Points: ${p.hcp} high card, ${p.hcp + p.length} with length, ${p.hcp + p.short} with shortness. Tap for details.`}
        >
          <b className="hcp">{p.hcp}</b> / {p.hcp + p.length} / {p.hcp + p.short}
        </button>
      ) : (
        <div className="pts-detail" onClick={() => onDetail(false)}>
          <dl className="pts">
            <div>
              <dt>HCP</dt>
              <dd className="hcp">{p.hcp}</dd>
            </div>
            <div>
              <dt>
                With length{p.longSuits.length > 0 && <SuitText text={` (${sym(p.longSuits)} +${p.length})`} />}
              </dt>
              <dd>{p.hcp + p.length}</dd>
            </div>
            <div>
              <dt>
                With shortness{" "}
                <SuitText text={`(${p.shortSuits.length ? `${sym(p.shortSuits)} +${p.short}, ` : ""}${fit ? `${SUIT_SYMBOL[fit]} fit, 5/3/1` : "3/2/1"})`} />
              </dt>
              <dd>{p.hcp + p.short}</dd>
            </div>
          </dl>
          <div className="need">
            {range ? (
              <>
                You + {partnerName} <b>{lo === hi ? lo : `${lo}–${hi}`}</b>
              </>
            ) : (
              <>
                You <b>{mine}</b> + {partnerName} ?
              </>
            )}{" "}
            / {need} for <SuitText text={callLabel(goal)} />
            {verdict && <span className={`verdict ${verdict}`}> · {verdict}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
