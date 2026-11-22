"""Bidding with a part score at rubber bridge.

At rubber, tricks bid and made below the line add up towards game (100 points). A side with a part score needs less
to finish its game: with 60 below the line, 2♣ or 1NT is game. The system's rules are written for a fresh game, so
`adjust` looks at the score after the rules have picked a call and changes it in three ways:

1. Stop: when partner's natural call already finishes our game and we have a fit (or a notrump-friendly hand), pass
   rather than invite or raise. Overtricks score above the line, so going higher only adds risk. A forcing or
   artificial call is still answered, and a hand with slam chances bids on.
2. Cheapest game: when the rules would jump in a fitted suit (or to 3NT) and a cheaper bid in that strain already
   finishes our game, bid the cheaper one, as long as the system plays it as natural and not forcing.
3. Compete: when the opponents' low contract would finish their game only because of their part score, or a low
   contract of ours would finish ours, the rules' overcalls, doubles and balancing calls are allowed a few points
   lighter. Fewer points when we're vulnerable and they're not, since going down costs us more.

How much a bot uses this depends on its level (`BotPlayer.score_for`): levels 1-5 ignore the score,
6 and up stop at game and bid the cheapest game, and 8 and up also compete lighter. Hints and the review use all three.

Every change carries a `note` the Why pop-up shows. Hints and the review use the same choice, so a player at a rubber
table is checked against bots that know the score. Duplicate (and a fresh game at rubber) is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.auction import Auction, is_bid
from ..core.board import is_vulnerable
from ..core.cards import partner, same_side
from ..core.scoring import trick_score
from .context import Ctx
from .evaluation import Eval
from .rules import cheapest
from .shows import readable, shows

GAME = 100
SLAM_POINTS = 33  # combined points where a slam is worth looking for, so the rules bid on as usual
FIT = 7  # a suit partner can stop in when it already makes game (a 5-2 fit plays fine for a part-score level)
RAISE_FIT = 8  # trumps needed before a jump is cut back to the cheapest game


def lighter_by(we_vul: bool, they_vul: bool) -> int:
    """How many points lighter to compete: going down costs more when we're vulnerable."""
    if not we_vul:
        return 3
    return 2 if they_vul else 1


@dataclass(frozen=True)
class Score:
    """The rubber score as the bidding sees it: points below the line for each side in this game, and who is
    vulnerable ("None", "NS", "EW" or "Both")."""
    ns: int = 0
    ew: int = 0
    vulnerability: str = "None"
    compete: bool = True  # also compete lighter (bots from level 8; hints and the review always)

    @property
    def matters(self) -> bool:
        return self.ns > 0 or self.ew > 0

    def below(self, seat: str) -> int:
        return self.ns if same_side(seat, "N") else self.ew

    @classmethod
    def from_rubber(cls, below: dict, vulnerability: str) -> "Score":
        return cls(below.get("NS", 0), below.get("EW", 0), vulnerability)

    def to_dict(self) -> dict:
        return {"NS": self.ns, "EW": self.ew, "vulnerability": self.vulnerability}


def points_below(call: str, doubled: int = 0) -> int:
    return trick_score(call[1], int(call[0])) * (1, 2, 4)[doubled]


def finishes_game(below: int, call: str, doubled: int = 0) -> bool:
    return below + points_below(call, doubled) >= GAME


def _slam_room(ev: Eval, ctx: Ctx, strain: str) -> bool:
    p = ctx.partner_info
    theirs = min(p.hcp[1], p.hcp[0] + 8)  # partner's likely best, not an unlimited bid's 37
    mine = ev.support_points(strain) if strain != "N" and ev.len(strain) + p.min_len(strain) >= RAISE_FIT else ev.tp
    return mine + theirs >= SLAM_POINTS



def _note(text: str) -> str:
    return readable(text)  # "2H" -> "2♥", so the app colors the suit


def adjust(engine, hand, auction: Auction, dec, score: Score):
    from .engine import Decision

    ctx = Ctx(auction, engine, score.vulnerability)
    ev = Eval(hand)
    me = ctx.me
    ours, theirs = score.below(me), score.below(ctx.lho)
    last = ctx.last_bid

    # 1. Stop in partner's call when it already finishes our game.
    if ours and last and is_bid(dec.call) and ctx.last_bidder == partner(me) and \
            finishes_game(ours, last):  # a double here is often for takeout, so don't count on it
        m = ctx.partner_last_meaning()
        strain = last[1]
        fits = ev.shape[-1] >= 2 if strain == "N" else ev.len(strain) + ctx.partner_info.min_len(strain) >= FIT
        if m and not (m.forcing or m.game_forcing or m.artificial) and fits and not _slam_room(ev, ctx, strain):
            return Decision("P", None, shows(f"To play: {last} is game with the part score"),
                            note=_note(f"{last} is game with the {ours} part score."), note_only=True)

    # 2. Bid only as high as our game needs.
    if ours and is_bid(dec.call) and finishes_game(ours, dec.call) and not dec.meaning.artificial:
        strain = dec.call[1]
        low = cheapest(ctx, strain)
        natural = int(dec.call[0]) <= 3 if strain == "N" else \
            ev.len(strain) + ctx.partner_info.min_len(strain) >= RAISE_FIT
        if low and low != dec.call and finishes_game(ours, low) and natural and not _slam_room(ev, ctx, strain):
            m = engine.explain_next(auction, low)
            if not (m.artificial or m.forcing or m.game_forcing):
                a = auction.copy()
                a.calls.append(low)
                return Decision(low, engine.explain_rule(a, len(a.calls) - 1), m,
                                note=_note(f"{low} is game with the {ours} part score, so no need for {dec.call}."))

    # 3. Compete a little lighter when a low contract is game for either side.
    if score.compete and dec.call == "P" and last and not ctx.contract_is_ours and int(last[0]) <= 3:
        their_game = theirs and finishes_game(theirs, last) and points_below(last) < GAME
        if their_game or ours:
            vul = score.vulnerability
            bonus = lighter_by(is_vulnerable(vul, me), is_vulnerable(vul, ctx.lho))
            for d in engine.candidates(hand, auction, bonus, vul=score.vulnerability):
                c = d.call
                if c == "P":
                    break
                if c == "X":
                    if not their_game:
                        break  # a light takeout double only to stop their game
                elif not is_bid(c) or c[1] == "N" or int(c[0]) > 3 or d.meaning.artificial or \
                        ev.len(c[1]) + ctx.partner_info.min_len(c[1]) < RAISE_FIT and ev.len(c[1]) < 5:
                    break
                elif not their_game and not finishes_game(ours, c):
                    break
                whose, pts, what = ("their", theirs, last) if their_game else ("the", ours, c)
                return Decision(c, d.rule, d.meaning,
                                note=_note(f"{what} would be game with {whose} {pts} part score, so compete on less."))
    return dec
