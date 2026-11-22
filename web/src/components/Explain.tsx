import botLevels from "../botLevels.json";
import CheatSheetLink from "./CheatSheet";
import Info from "./Info";

// The ⓘ pop-ups that say how the app works things out. Odds from 100 sampled layouts carry a margin of error:
// at 50% a 95% range is about 10 points either way, narrower toward 0% or 100%. Close calls get more layouts.

const ODDS_MARGIN = (
  <p>
    <strong>Margin of error:</strong> 100 layouts is a sample, so a percentage can be off by up to about 10 points either
    way (less near 0% or 100%). When the top two cards are within 10 points, the app deals 100 more layouts to tell
    them apart.
  </p>
);

// Who plays the cards about like each level. Levels 7 to 9 come from published matches scored the same way as the
// bots (world championships, a top national league, regional events); levels 1 to 6 are estimates (docs/bots.md).
const PLAYS_LIKE = [
  "New to the game", "Beginner", "Beginner", "Improving", "Social player", "Club player",
  "Regional tournament", "National to world class", "Beyond the pros", "The bot's best",
];
const LEVELS = botLevels as Record<string, { declaring: number; defending: number }>;

export function BotStrengthInfo({ level }: { level?: number }) {
  return (
    <Info title="How bot strength works">
      <h4>Bidding</h4>
      <p>
        All bots bid by the <CheatSheetLink>No Fear Bridge cheat sheet</CheatSheetLink> and the table's conventions.
        Their bidding is <strong>intermediate</strong>, about the same at every level. What changes with the level is
        how much they weigh the score:
      </p>
      <ul>
        <li>
          <strong>Vulnerability</strong>, from level 6: vulnerable, they bid a close game, since it pays more. From
          level 8 they also take risks when only the other side is vulnerable: they compete on a little less and
          sacrifice over a game with a long fit and a weak hand.
        </li>
        <li>
          <strong>Part scores at rubber</strong>, from level 6: they stop as soon as a bid makes game. From level 8
          they also compete on lighter hands.
        </li>
        <li>Levels 1 to 5 bid the same whatever the score.</li>
      </ul>
      <h4>Card play</h4>
      <p>
        Strength sets how well the bots play the cards. The table shows the tricks a bot gives away per hand, against
        perfect play with all the cards face up, and who plays about like that.
      </p>
      <table className="levels">
        <thead>
          <tr><th>Level</th><th>Declaring</th><th>Defending</th><th>Plays like</th></tr>
        </thead>
        <tbody>
          {PLAYS_LIKE.map((who, i) => (
            <tr key={i} className={level === i + 1 ? "me" : undefined}>
              <td>{i + 1}</td>
              <td>{LEVELS[i + 1].declaring.toFixed(2)}</td>
              <td>{LEVELS[i + 1].defending.toFixed(2)}</td>
              <td>{who}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Levels 7 to 9 are matched to published tournament play, the rest are estimates. The measure is kind to bots, and
        it can't see a clever misleading card. "Plays like" is about card play only.
      </p>
      <p>
        To pick a card, a bot deals out possible layouts of the cards it can't see, works out the best card in each with
        all the cards face up, and plays the card that does best across them.
      </p>
      <ul>
        <li>Higher levels try more layouts: 4 at level 1, rising to 48 at level 10.</li>
        <li>From level 3 up, the layouts fit what the bidding showed. Levels 1 and 2 ignore the bidding.</li>
        <li>Below level 10, a bot sometimes picks a good card that isn't quite the best, more often at lower levels.</li>
        <li>
          Levels 4 to 7 lose track of the side suits, as people do: which small cards have gone, and who showed out.
          They always remember trumps, tens and honors, and never miss a free ruff.
        </li>
        <li>Levels 1 to 9 now and then play a random card: 15% of the time at level 1, down to under 1% at level 9.</li>
      </ul>
    </Info>
  );
}

export function HintsInfo() {
  return (
    <Info title="How hints work">
      <p>
        <strong>Bidding:</strong> the hint is the call the system makes with your hand (the <CheatSheetLink /> and
        the table's conventions), with what it means.
      </p>
      <p>
        <strong>Card play:</strong> the app deals 100 layouts of the cards you can't see that fit the bidding and the play
        so far, works out each one with all the cards face up, and suggests the card that does best. It plays like the
        strongest bot, using only what you can see.
      </p>
      <p>
        The percentage is how often a card makes the contract (or beats it, when you defend) across those 100 layouts.
        Cards listed as "as good" did just as well. When the best cards make (or beat) the contract about equally
        often, the hint goes by one trick more, as the review does, and shows them on a second line ("But for an extra trick").
      </p>
      {ODDS_MARGIN}
      <p>The review counts how many hints you used on each board.</p>
    </Info>
  );
}

export function ReviewInfo() {
  return (
    <Info title="How the review works">
      <p>
        <strong>With perfect play</strong> is how many tricks declarer could take if everyone played perfectly with all 52
        cards face up.
      </p>
      <p>
        <strong>A card that cost a trick</strong> is one after which its side could take fewer tricks, with all the cards
        face up, than it could before.
      </p>
      <p>
        Each of those cards is then judged on what its player could see at the time. The app deals 100 layouts of the
        hidden cards that fit the bidding and the play so far, and counts how often each card would still have taken the
        tricks the side could have had.
      </p>
      <ul>
        <li>
          <span className="tag mistake">Mistake</span> another card did at least 10 points better on those odds, so it was
          the better bet.
        </li>
        <li>
          <span className="tag unlucky">Unlucky</span> the card played was as good a bet or better; the cards just lay badly
          this time.
        </li>
      </ul>
      <p>
        <strong>Margin of error:</strong> the percentages come from 100 layouts, so each can be off by up to about 10
        points either way (less near 0% or 100%). That's why a card has to be 10 points better to count as a Mistake.
        When the card played is within 20 points of the best, the app deals 200 more layouts, which narrows the margin
        to about 6 points. The tricks with all cards face up are exact.
      </p>
      <p>
        <strong>Bidding</strong> lists your side's calls that differ from the system's call with that hand. A sensible
        alternative is another call the system also allows.
      </p>
      <p>
        <strong>Helped or cost:</strong> a call off the system can work this time and still be a poor bet, so it's
        judged on 30 deals like this one: the app deals the other three hands to fit what the caller could see (their
        hand and the bidding so far). On each, it bids the auction out from that point twice, the system bidding every
        seat: once after the call made, once after the system's call. It scores both contracts, and the tag shows the
        average difference. The line after the tag is this deal alone.
      </p>
      <p>
        <strong>Both scores assume perfect play</strong> (all cards face up), not what happened at the table. That way
        only the bidding is judged. A contract that made only because a defender slipped still counts as going down, and
        one that went down only from a misplay still counts as making. Card play is judged separately, under Cards that
        cost a trick.
      </p>
      <ul>
        <li>
          <span className="tag helped">Helped</span> your call scored more than 20 points better on average.
        </li>
        <li>
          <span className="tag mistake">Cost</span> the system's call scored more than 20 points better on average.
        </li>
      </ul>
      <p>
        At rubber, a part score counts toward game. It's an estimate: after either call, the real players might have
        bid differently. When someone bid again after the call, their bid helped decide the result too, and the
        review says so.
      </p>
    </Info>
  );
}

export function LevelInfo({ hands }: { hands: number }) {
  return (
    <Info title="How your level works">
      <p>
        Every card you choose is checked with all the cards face up, as in the review: a card that lets your side take
        fewer tricks than before loses tricks. Dummy's cards count to declarer.
      </p>
      <p>
        Your level compares the tricks you lose per hand, declaring and defending, with how each bot level does on the same
        deals: level 1 bots lose about 4 tricks a hand as declarer, level 10 bots under half a trick. It uses your last{" "}
        {hands} hands, up to 40.
      </p>
      <p>
        <strong>Margin of error:</strong> the range under your level is where it most likely sits (about 95% sure), worked
        out from how much the tricks you lose vary from hand to hand. It narrows as you play more hands. The top levels
        play very alike, so the range is wider there.
      </p>
    </Info>
  );
}

export function PlayLocallyInfo({ device }: { device: string }) {
  return (
    <Info title="How playing locally works">
      <p>
        Your games with bots run on this {device} itself, so you can play anywhere, even with no internet: on the boat or
        on a plane. The bots, hints and review are the same as on the server.
      </p>
      <p>
        <strong>With internet,</strong> your boards still go to My stats, your AI coach can see the table, and your other
        devices can pick up where you left off. Inviting a friend moves the table to the server so they can join.
      </p>
      <p>
        <strong>With no internet,</strong> finished boards wait on this {device} and go to My stats once it's back
        online. A partner on the same Wi-Fi can still join: open Menu, then Invite to game, and they tap Join on Wi-Fi.
        Your phones then scan each other's codes. Their phone needs to have opened the app with internet once.
      </p>
      <p>
        <strong>Turned off,</strong> the server plays the bots. If the internet drops in the middle of a hand, this{" "}
        {device} takes over and hands the table back when the internet returns.
      </p>
      <p>The first time, the app saves about 12 MB on this {device} so it can play without internet.</p>
    </Info>
  );
}
