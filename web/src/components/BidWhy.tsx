import { SEAT_NAME, callLabel } from "../cards";
import type { AuctionEntry } from "../types";
import Feedback from "./Feedback";
import Info from "./Info";
import SuitText from "./SuitText";

const SUITS = ["S", "H", "D", "C"] as const;
const SYMBOL = { S: "♠", H: "♥", D: "♦", C: "♣" };

/** A bot's call explained (opened on a tap, or from an ⓘ): why it bid that, and (signed in) a Feedback pull-down about that call. During the
 * board the bot's cards stay hidden; afterwards its hand and the other calls it fit are shown too. */
export default function BidWhy({ entry, index, room, board, onClose }: { entry: AuctionEntry; index: number; room: string; board: number; onClose?: () => void }) {
  const why = entry.why;
  if (!why) return null;
  const who = `Bot ${SEAT_NAME[entry.seat]}`;
  const did = { P: "passed", X: "doubled", XX: "redoubled" }[entry.call];
  const title = did ? `Why ${who} ${did}` : `Why ${who} bid ${callLabel(entry.call)}`;
  const heading = did ? title : <>Why {who} bid <SuitText text={callLabel(entry.call)} /></>;
  // "General judgment · General bidding judgment" says it twice: name the convention only when it adds something
  const words = (t: string) => t.toLowerCase().split(/\W+/).filter(Boolean);
  const convention =
    why.convention && !words(why.rule ?? "").every((w) => words(why.convention!).includes(w)) ? why.convention : null;
  return (
    <Info title={title} heading={heading} onClose={onClose}>
      <p className="meaning">
        {entry.meaning.alert && <span className="badge">alert</span>}
        {entry.meaning.forcing && <span className="badge">forcing</span>} <SuitText text={entry.meaning.text} />
        {entry.meaning.hcp && (
          <span className="muted">
            {" "}
            · HCP {entry.meaning.hcp[0]}–{entry.meaning.hcp[1]}
          </span>
        )}
      </p>
      {why.rule && (
        <p>
          <strong>Rule:</strong> {why.rule}
          {convention && <span className="muted"> · {convention}</span>}
        </p>
      )}
      {why.note && (
        <p>
          <strong>Score:</strong> <SuitText text={why.note} />
        </p>
      )}
      {why.shown && (
        <p>
          <strong>Shown so far:</strong> <SuitText text={why.shown} />
        </p>
      )}
      {why.instead && why.instead.length > 0 && (
        <p>
          <strong>Didn't fit:</strong>{" "}
          {why.instead.map((c, i) => (
            <span key={c.call}>
              {i > 0 && "; "}
              <SuitText text={callLabel(c.call)} /> (<SuitText text={c.text} />)
            </span>
          ))}
          .
        </p>
      )}
      {why.hand ? (
        <>
          <p>
            <strong>Its hand:</strong> {why.hand.hcp} HCP,{" "}
            {SUITS.map((s, i) => (
              <span key={s}>
                {i > 0 && " "}
                <SuitText text={`${why.hand!.lengths[s]}${SYMBOL[s]}`} />
              </span>
            ))}
          </p>
          {why.also && why.also.length > 0 && (
            <p>
              <strong>Also fit:</strong>{" "}
              {why.also.map((a, i) => (
                <span key={a.call}>
                  {i > 0 && "; "}
                  <SuitText text={callLabel(a.call)} /> ({a.rule ?? "no rule"})
                </span>
              ))}
              . The system tries {why.rule ?? "its rule"} first.
            </p>
          )}
        </>
      ) : (
        <p className="muted">More in the review after the board.</p>
      )}
      <Feedback
        about={{ bid: { room, board, index } }}
        intro="Bid look wrong? The deal and auction go with your note."
        placeholder="What would you bid? (optional)"
        optional
      />
    </Info>
  );
}
