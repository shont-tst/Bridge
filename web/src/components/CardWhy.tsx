import { SEAT_NAME, cardLabel, contractLabel } from "../cards";
import type { CardWhy as Why, Contract, Seat } from "../types";
import Feedback from "./Feedback";
import Info from "./Info";
import SuitText from "./SuitText";

/** The ⓘ next to a card a bot played: how it picked that card, and (signed in) a Feedback pull-down about it.
 * During the board it says only how the bot chose; its odds and the other cards it weighed would give its hand
 * away, so they show once the board is over. */
export default function CardWhy({ card, seat, why, dummy, contract, room, board, onClose }: {
  card: string;
  seat: Seat;
  why: Why;
  dummy?: Seat;
  contract: Contract | null;
  room: string;
  board: number;
  onClose?: () => void; // opened straight away, with no ⓘ
}) {
  const label = cardLabel(card);
  const fromDummy = seat === dummy;
  const title = fromDummy ? `Why ${label} from dummy` : `Why Bot ${SEAT_NAME[seat]} played ${label}`;
  const heading = fromDummy ? <>Why <SuitText text={label} /> from dummy</> : <>Why Bot {SEAT_NAME[seat]} played <SuitText text={label} /></>;
  const goal = contract ? `${why.goal === "make" ? "makes" : "beats"} ${contractLabel(contract).replace(/ by .*/, "")}` : "";
  const tricks = (n: number) => `${n} ${n === 1 ? "trick" : "tricks"}`;
  const how = {
    best: `Best card across ${why.samples} layouts of the hidden cards.`,
    hidden: `More in the review after the board.`,
    random: `A random card: level ${why.level} bots play one now and then.`,
    only: `It was the only card it could play.`,
    guess: `It couldn't find layouts that fit the bidding, so it played a low card.`,
  }[why.kind];
  return (
    <Info title={title} heading={heading} onClose={onClose}>
      {why.play && <p>{why.play}</p>}
      <p>{how}</p>
      {why.signal && (
        <p>
          <SuitText text={why.signal} />
        </p>
      )}
      {why.made !== undefined && why.tricks !== undefined && (
        <>
          <p>
            <SuitText text={label} /> <SuitText text={goal} /> in {why.made} of {why.samples} layouts, taking{" "}
            {tricks(why.tricks)} from here on average.
          </p>
          {why.alts && why.alts.length > 0 && (
            <p>
              <strong>Next best:</strong>{" "}
              {why.alts.map((a, i) => (
                <span key={a.card}>
                  {i > 0 && "; "}
                  <SuitText text={cardLabel(a.card)} /> {a.made} of {why.samples}, {tricks(a.tricks)}
                </span>
              ))}
              .
            </p>
          )}
          {!why.alts && why.kind !== "hidden" && (
            <p className="muted">More in the review after the board.</p>
          )}
          {!!why.equal && (
            <p className="muted">
              {why.equal === 1 ? "Another card" : `${why.equal} other cards`} did just as well. {why.signal && !why.led ? "A bot signals with equal cards." : "A bot plays the lowest of equal cards."}
            </p>
          )}
          {why.softened && (
            <p className="muted">
              Below level 10 a bot sometimes picks a good card that isn't quite its best. This was one, at level{" "}
              {why.level}.
            </p>
          )}
        </>
      )}
      <Feedback
        about={{ card: { room, board, card } }}
        intro="Card look wrong? The deal and play so far go with your note."
        placeholder="What would you play? (optional)"
        optional
      />
    </Info>
  );
}
