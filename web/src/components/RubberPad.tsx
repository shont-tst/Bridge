import { SUIT_SYMBOL } from "../cards";
import type { RubberLine } from "../types";
import SuitText from "./SuitText";

/** A We/They score pad: bonuses above the line, the points towards game below it, a rule under each game. */
export default function RubberPad({ lines, gameEnds, we, finished }: {
  lines: RubberLine[];
  gameEnds: number[]; // a game ended after this many lines
  we: "NS" | "EW";
  finished?: boolean; // the rubber is over: every game has its rule
}) {
  const they = we === "NS" ? "EW" : "NS";
  const entry = (l: RubberLine, i: number) => (
    <li key={i}>
      <b>{l.points}</b> <span className="what">
        <SuitText text={l.what.replace(/^(\d)([CDHSN])/, (_, n, s) => `${n}${SUIT_SYMBOL[s]}`)} />
      </span>
    </li>
  );
  const column = (side: string, where: "above" | "below", from: number, to: number) => (
    <ul>
      {lines
        .map((l, i) => [l, i] as const)
        .filter(([l, i]) => l.side === side && l.where === where && i >= from && i < to)
        .map(([l, i]) => entry(l, i))}
    </ul>
  );
  // where each game's lines start and end; a finished rubber has no game in progress after the last rule
  const games = finished ? [0, ...gameEnds] : [0, ...gameEnds, lines.length];
  const total = (side: string) => lines.filter((l) => l.side === side).reduce((n, l) => n + l.points, 0);
  return (
    <div className="pad">
      <div className="pad-head">
        <span>We</span>
        <span>They</span>
      </div>
      <div className="pad-row above">
        {column(we, "above", 0, Infinity)}
        {column(they, "above", 0, Infinity)}
      </div>
      {games.slice(0, -1).map((from, g) => (
        <div key={g} className={`pad-row below ${g < gameEnds.length ? "game-over" : ""} ${finished && g === games.length - 2 ? "rubber-end" : ""}`}>
          {column(we, "below", from, games[g + 1])}
          {column(they, "below", from, games[g + 1])}
        </div>
      ))}
      <div className="pad-row total">
        <b>{total(we)}</b>
        <b>{total(they)}</b>
      </div>
    </div>
  );
}
