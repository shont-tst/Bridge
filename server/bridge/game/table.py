"""One board at the table: dealing, the auction, the play and the score.

The table is the authority on hidden information: `state_for(seat)` returns
only what that seat may see, and bots receive a BotView (see bots/view.py).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, replace

from ..bidding.context import Ctx
from ..bidding.engine import BiddingEngine
from ..bidding.partscore import Score
from ..bots.card_play import _need, choose_card, merge, top_two_gap
from ..bots.difficulty import difficulty
from ..bots.player import BotPlayer
from ..bots import leads, signals
from ..bots.view import BotView, view_for
from ..core.auction import Auction, Contract
from ..core.board import dealer_for, is_vulnerable, vulnerability_for
from ..core.cards import RANKS, SEATS, Hand, deal_random, rank_value, same_side

SEAT_NAME = {"N": "North", "E": "East", "S": "South", "W": "West"}
from ..core.claim import can_claim, play_claim
from ..core.play import Play
from ..core.scoring import duplicate_score

BIDDING, PLAYING, DONE = "bidding", "playing", "done"


@dataclass
class BoardResult:
    board: int
    dealer: str
    vulnerability: str
    hands: dict[str, str]  # PBN per seat
    calls: list[str]
    contract: dict | None
    declarer_tricks: int
    score_ns: int
    play: list[list[str]]  # [[seat, card], ...]
    dd: dict | None = None
    review: dict | None = None
    claimed: str | None = None  # the seat whose side claimed the last tricks
    claimed_tricks: int | None = None  # how many tricks the claim took
    claim_cards: dict | None = None  # the claiming side's cards when it claimed: {seat: [cards]} (declarer and dummy)
    claim_saw: list | None = None  # the seats that saw those cards as the claim was made (claimer, whoever accepted)
    claim_accepted: str | None = None  # who accepted a bot's claim: the first to accept settles it
    asked: list | None = None  # the calls and cards made right after a hint or AI coach question (review.asked_marks)
    finished_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


HINT_SAMPLES = 100  # as many layouts as the review's odds, so the two agree
# A close call (the best two cards within CLOSE points, about the margin of error of 100 layouts) gets HINT_MORE more
# layouts before the hint is given, so the % shown is surer where it matters. Most positions aren't close.
CLOSE = 10
HINT_MORE = 100
# When the best cards make (or beat) the contract within EXTRA_TIE points of each other, and at least EXTRA_FROM % of the
# time, the hint ranks those cards by one trick more, as the review does, and shows those odds too.
EXTRA_TIE = 5  # about the margin of error near 100% on 200 layouts
EXTRA_FROM = 50


def _extra_trick(view: BotView, choice) -> dict[str, int] | None:
    """In how many layouts each card takes one trick more than the side's goal, when that's worth looking at: the
    best two real choices reach the goal about equally often, and usually. None otherwise."""
    if not choice.layouts or not choice.samples:
        return None
    n, need = choice.samples, _need(view)
    pct = sorted({tuple(choice.layouts[c]): 100 * choice.made.get(c, 0) / n for c in choice.layouts}.values(),
                 reverse=True)
    if len(pct) < 2 or pct[0] - pct[1] > EXTRA_TIE or pct[1] < EXTRA_FROM:
        return None
    tricks = lambda v: v - 1 if v > need else v  # each layout's value is its tricks plus 1 for reaching the goal
    return {c: sum(tricks(v) >= need + 1 for v in vals) for c, vals in choice.layouts.items()}


def card_hint(view: BotView, engine: BiddingEngine, rng: random.Random | None = None) -> dict:
    """The card that most often makes (or beats) the contract across the layouts the player can't rule out, with
    those odds for it and for the next best different card. Ties go to the card that takes more tricks on average,
    then to the strongest bot's own pick. The hint ranks by the same odds it shows, so it never suggests a card
    that shows a lower % than the one beside it (the bot's own score counts making as worth only one trick, so
    it can prefer a card that wins more tricks on average but makes or beats the contract less often).
    When the best cards make (or beat) it about equally often (`_extra_trick`), they are ranked by one trick more and
    the hint shows those odds as `extra` too, so it agrees with the review, which judges every trick."""
    choice = choose_card(view, engine, replace(difficulty(10), samples=HINT_SAMPLES), rng)
    gap = top_two_gap(choice)
    if gap is not None and gap < CLOSE:
        more = choose_card(view, engine, replace(difficulty(10), samples=HINT_MORE), rng)
        if more.samples and more.layouts:
            choice = merge(choice, more, view)
    if not (choice.samples and choice.made):  # one legal card, or no layouts: the bot's pick as it stands
        return {"type": "hint", "phase": PLAYING, "seat": view.seat, "card": choice.card, "equal": [],
                "samples": choice.samples}
    n = choice.samples
    pct = lambda c: round(100 * choice.made.get(c, 0) / n)
    key = lambda c: (choice.made.get(c, 0), round(choice.scores[c], 9))
    extra = _extra_trick(view, choice)
    if extra:  # making (or beating) is about the same either way: rank those cards by the next trick (#171 board 8)
        near = [c for c in choice.scores if pct(c) >= max(map(pct, choice.scores)) - EXTRA_TIE]
        key = lambda c: (c in near, extra[c] if c in near else 0, choice.made.get(c, 0), round(choice.scores[c], 9))
    best = max(key(c) for c in choice.scores)
    equal = sorted(c for c in choice.scores if key(c) == best)
    card = choice.card if choice.card in equal else min(equal, key=lambda c: (rank_value(c), RANKS.index(c[1])))
    hint = {"type": "hint", "phase": PLAYING, "seat": view.seat, "card": card,
            "equal": equal if len(equal) > 1 else [], "samples": n}
    odds = [{"card": card, "pct": pct(card)}]
    others = [c for c in choice.scores if c not in equal]
    if others:
        odds.append({"card": max(others, key=key), "pct": pct(max(others, key=key))})
    hint["odds"] = odds
    if extra and len(odds) > 1 and odds[1]["card"] in near:
        shown = [{"card": o["card"], "pct": round(100 * extra[o["card"]] / n)} for o in odds]
        if shown[0]["pct"] != shown[1]["pct"]:
            declaring = same_side(view.seat, view.declarer)
            hint["extra"] = {"label": f"{view.contract.level + 7} tricks" if declaring else "Down 2", "odds": shown}
    hint["goal"] = "make" if same_side(view.seat, view.declarer) else "beat"
    if choice.signal and card == choice.card:
        hint["signal"] = signals.words(choice.signal, you=True)
    elif choice.lead:  # at the opening lead every choice is the method's card in its suit: name the hinted one's rule
        hint["signal"] = leads.words(leads.kind(view, card) or choice.lead)
    return hint


def shown_so_far(inf) -> str:
    """What a seat's calls have shown, in words: "12–21 HCP, 5+ ♠, balanced"."""
    parts = []
    lo, hi = inf.hcp
    if (lo, hi) != (0, 37):
        parts.append(f"{lo}+ HCP" if hi >= 37 else f"{lo}–{hi} HCP")
    for suit in "SHDC":
        a, b = inf.lengths[suit]
        sym = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}[suit]
        if a and b < 13:
            parts.append(f"{a}–{b} {sym}" if a != b else f"exactly {a} {sym}")
        elif a:
            parts.append(f"{a}+ {sym}")
        elif b < 13:
            parts.append(f"at most {b} {sym}")
    if inf.balanced:
        parts.append("balanced")
    elif inf.balanced is False:
        parts.append("unbalanced")
    return ", ".join(parts) or "nothing definite yet"


def card_reasons(choice, declaring: bool, level: int, trump: str = "N") -> dict:
    """What a bot's CardChoice says about why it played its card: how it chose, and, from the layouts it tried, how
    often that card and its next best two still reached its side's goal (making or beating the contract)."""
    kind = {"only card": "only", "blunder": "random", "best average": "best", "softmax": "best"}.get(choice.reason, "guess")
    out = {"kind": kind, "level": level, "samples": choice.samples, "goal": "make" if declaring else "beat"}
    if choice.made and choice.samples:
        n = choice.samples
        tricks = {c: round(choice.scores[c] - choice.made.get(c, 0) / n, 1) for c in choice.scores}  # less the goal bonus
        best = max(choice.scores.values())
        others = sorted((c for c in choice.scores if c != choice.card), key=lambda c: -choice.scores[c])
        out["made"], out["tricks"] = choice.made.get(choice.card, 0), tricks[choice.card]
        out["alts"] = [{"card": c, "made": choice.made.get(c, 0), "tricks": tricks[c]} for c in others[:2]]
        out["equal"] = sum(1 for c in others if choice.scores[c] >= best - 1e-9) if choice.scores[choice.card] >= best - 1e-9 else 0
        out["softened"] = choice.scores[choice.card] < best - 1e-9  # a lower level's looser pick, not its best
    if getattr(choice, "signal", None):  # what the card told partner: the table's agreement, so shown during the board
        out["signal"] = signals.words(choice.signal)
    if getattr(choice, "lead", None):  # during the board, what anyone reads from the card; after it, the rule used
        out["signal"] = leads.shows(choice.card, trump)
        out["lead"], out["led"] = leads.words(choice.lead), True
    return out


class Table:
    bot_claims = True  # tests that play whole hands through turn it off, so a claim doesn't stop them

    def __init__(self, engine: BiddingEngine, board: int, bot_seats: set[str],
                 bot: BotPlayer, rng: random.Random | None = None,
                 hands: dict[str, Hand] | None = None, dealer: str | None = None,
                 vulnerability: str | None = None, score: Score | None = None, signals: str | None = None,
                 leads: bool = True):
        self.engine = engine
        self.signals = signals  # the defensive signals the table plays (bots/signals.py), or None
        self.leads = leads  # whether the table leads by Standard leads (bots/leads.py)
        self.board = board
        self.dealer = dealer or dealer_for(board)
        self.vulnerability = vulnerability or vulnerability_for(board)  # rubber bridge passes its own
        self.score = score  # at rubber, the part scores when the board was dealt: the bots bid with them
        self.bot_seats = set(bot_seats)
        self.bot = bot
        self.hands = hands or deal_random(rng)
        self.auction = Auction(self.dealer)
        self.play: Play | None = None
        self.contract: Contract | None = None
        self.phase = BIDDING
        self.result: BoardResult | None = None
        self.last_bot_note: str | None = None
        self.actions: list[tuple[str, str, str]] = []  # (who acted, "call", "card" or "claim", what), for undo
        self.fixed = 0  # the first actions, made for the player before the board starts (leads practice), can't be undone
        self._claim: tuple[int, bool] | None = None  # (len(actions), can claim) for the position last asked about
        # a bot's claim waiting on the people on the other side: {"by": the bot claiming, "deciders": [seats],
        # "accepted": [seats]}. Bots don't act while it waits.
        self.claim_offer: dict | None = None
        self.claim_refused: set[str] = set()  # bots whose claim was rejected this board: they play it out
        self._why: dict[tuple, dict] = {}  # a bot's reasons for a call, by engine and the calls up to it
        self.card_why: dict[str, dict] = {}  # how a bot picked each card it played this board, by card

    # --- turn bookkeeping ----------------------------------------------------------
    def seat_to_act(self) -> str | None:
        if self.phase == BIDDING:
            return self.auction.next_to_call
        if self.phase == PLAYING:
            return self.play.next_to_play
        return None

    def controller_of(self, seat: str) -> str:
        """Declarer plays dummy's cards. When a bot partner declares opposite a human (solo games),
        the human plays both hands instead: they bid it together, so the human gets to play it."""
        if self.phase == PLAYING and seat in (self.contract.declarer, self.play.dummy):
            if self._human_declares_for_bot():
                return self.play.dummy
            if seat == self.play.dummy:
                return self.contract.declarer
        return seat

    def _human_declares_for_bot(self) -> bool:
        return self.contract.declarer in self.bot_seats and self.play.dummy not in self.bot_seats

    def controller_to_act(self) -> str | None:
        s = self.seat_to_act()
        return None if s is None else self.controller_of(s)

    def is_bot_turn(self) -> bool:
        if self.claim_offer:
            return False
        c = self.controller_to_act()
        return c is not None and c in self.bot_seats

    # --- actions ---------------------------------------------------------------------
    def make_call(self, seat: str, call: str) -> None:
        if self.phase != BIDDING:
            raise ValueError("the auction is over")
        if seat != self.auction.next_to_call:
            raise ValueError(f"it is {self.auction.next_to_call}'s turn to call")
        self.auction.add(call)
        self.actions.append((seat, "call", call))
        if self.auction.is_complete():
            self._end_auction()

    def _end_auction(self) -> None:
        self.contract = self.auction.contract()
        if self.contract is None:
            self._finish()
            return
        self.play = Play.start(self.contract.declarer, self.contract.strain, self.hands)
        self.phase = PLAYING

    def play_card(self, controller: str, card: str) -> None:
        if self.phase != PLAYING:
            raise ValueError("not in the play")
        seat = self.play.next_to_play
        if controller != self.controller_of(seat):
            raise ValueError(f"it is {seat}'s turn to play")
        if self.claim_offer:
            raise ValueError("accept or reject the claim first")
        self.play.play(card)
        self.actions.append((controller, "card", card))
        if self.play.is_complete():
            self._finish()

    def _certain(self, controller: str | None) -> bool:
        """Whether `controller`, to play, is certain to take every remaining trick (see core/claim.py)."""
        if self.phase != PLAYING or controller is None or controller != self.controller_to_act():
            return False
        if self._claim is None or self._claim[0] != len(self.actions):
            self._claim = (len(self.actions), can_claim(self.play))
        return self._claim[1]

    def can_claim(self, controller: str | None) -> bool:
        """Whether the person `controller` may tap Claim now (bots claim through `bot_step`)."""
        return controller not in self.bot_seats and not self.claim_offer and self._certain(controller)

    def claim(self, controller: str, saw: list[str] | None = None) -> None:
        """Take every remaining trick: the rest of the hand is played out along the sure line, the other side
        playing its lowest cards, so the review and the hand history see a whole hand.

        The claiming side's cards are kept on the result, so the people who didn't see them as the claim was made
        (a bot partner's claim on defense, say, with only bots to decide it) get a pop-up of them.
        `saw` lists the seats that did: the claimer and anyone who accepted it."""
        if self.claim_offer or not self._certain(controller):
            raise ValueError("you can claim only when every remaining trick is certain")
        seat = self.play.next_to_play
        left = self.tricks_left()
        decl = self.contract.declarer
        shown = [decl, self.play.dummy] if same_side(controller, decl) else [controller]
        cards = {s: list(self.play.hands[s]) for s in shown if self.play.hands[s]}
        play_claim(self.play)
        self.actions.append((controller, "claim", seat))
        self._finish()
        self.result.claimed = controller
        self.result.claimed_tricks = left
        self.result.claim_cards = cards
        self.result.claim_saw = sorted(set(saw or []) | {controller})

    def tricks_left(self) -> int:
        return 13 - len(self.play.completed_tricks()) if self.play else 0

    def _bot_claim(self, controller: str) -> dict | None:
        """A bot to play claims when every remaining trick is certain (two or more of them, and not after a
        rejected claim this board). The people on the other side accept or reject it, but never dummy (dummy
        doesn't approve a claim); with nobody there to decide, it goes ahead at once. A person in dummy's seat who is
        playing both hands (a bot partner declared, see controller_of) is the declarer in all but name, so decides."""
        if not self.bot_claims or controller in self.claim_refused or self.tricks_left() < 2 \
                or not self._certain(controller):
            return None
        dummy_sits_out = not self._human_declares_for_bot()
        deciders = sorted(s for s in SEATS if s not in self.bot_seats and not same_side(s, controller)
                          and not (s == self.play.dummy and dummy_sits_out))
        if not deciders:
            self.claim(controller)
            return {"seat": controller, "claim": True}
        self.claim_offer = {"by": controller, "deciders": deciders, "accepted": []}
        return {"seat": controller, "claim_offer": True}

    def answer_claim(self, seat: str, accept: bool) -> None:
        """A person on the other side accepts or rejects a bot's claim. The first to answer settles
        it: an Accept takes the claim at once, so they go straight on to the score, while a partner who hadn't
        answered gets the claimer's cards in a pop-up to look over (they're not in claim_saw); a Reject plays the
        hand out (and that bot doesn't claim again this board)."""
        offer = self.claim_offer
        if not offer:
            raise ValueError("there's no claim to answer")
        if seat not in offer["deciders"]:
            raise ValueError("the other side decides on this claim")
        self.claim_offer = None
        if not accept:
            self.claim_refused.add(offer["by"])
            return
        self.claim(offer["by"], saw=[seat])
        self.result.claim_accepted = seat

    def claim_offer_for(self, viewer: str | None) -> dict | None:
        offer = self.claim_offer
        if not offer:
            return None
        by = offer["by"]
        dummy = self.play.dummy if by == self.contract.declarer else None
        return {"by": by, "tricks": self.tricks_left(), "cards": list(self.play.hands[by]),
                "dummy": by == self.contract.declarer,
                # declarer's claim counts dummy's cards too: show them in the pop-up, which can cover dummy
                "dummy_cards": list(self.play.hands[dummy]) if dummy else None,
                "you_decide": viewer in offer["deciders"] and viewer not in offer["accepted"],
                "waiting": [s for s in offer["deciders"] if s not in offer["accepted"]]}

    def replay(self, who: str, kind: str, what: str) -> None:
        """Apply one saved action again (undo and restoring a saved table)."""
        if kind == "call":
            self.make_call(who, what)
        elif kind == "claim":
            self.claim(who, saw=list(SEATS))  # a restored or replayed claim was seen when it was first made
        else:
            self.play_card(who, what)

    def bot_step(self) -> dict | None:
        """Let the bot act once if it is a bot's turn. Returns a description."""
        if not self.is_bot_turn():
            return None
        seat = self.seat_to_act()
        if self.phase == PLAYING:
            claimed = self._bot_claim(self.controller_of(seat))
            if claimed:
                return claimed
        if self.phase == BIDDING:
            dec = self.bot.bid(self.hands[seat], self.auction, self.score, self.vulnerability)
            self.make_call(seat, dec.call)
            return {"seat": seat, "call": dec.call}
        view = view_for(self.play, self.auction, self.contract, self.vulnerability, seat, self.signals,
                        self.leads)
        choice = self.bot.play(view)
        self.play_card(self.controller_of(seat), choice.card)
        self.card_why[choice.card] = card_reasons(choice, same_side(seat, self.contract.declarer), self.bot.diff.level,
                                                    self.contract.strain)
        return {"seat": seat, "card": choice.card}

    # --- undo ------------------------------------------------------------------------------
    def can_undo(self) -> bool:
        return any(who not in self.bot_seats for who, _, _ in self.actions[self.fixed:])

    def undo(self) -> None:
        """Take back the last call or card a person made, and everything the bots did after it,
        so it is that person's turn again. Pressed again, it goes further back, to the start of the board."""
        humans = [i for i, (who, _, _) in enumerate(self.actions) if who not in self.bot_seats and i >= self.fixed]
        if not humans:
            raise ValueError("nothing to undo")
        keep = self.actions[:humans[-1]]
        self.auction = Auction(self.dealer)
        self.play = self.contract = self.result = None
        self.phase = BIDDING
        self.actions = []
        self._claim = None
        self.claim_offer = None  # a refused claim stays refused: that bot plays the board out (claim_refused kept)
        for who, kind, what in keep:
            self.replay(who, kind, what)

    # --- hints -------------------------------------------------------------------------
    def hint(self, controller: str, rng: random.Random | None = None) -> dict:
        """Suggest a call or card for the human whose turn it is.

        Bids come from the system with the hint-taker's own hand. Cards come from
        the strongest bot playing from the same BotView a bot in that seat would
        get, so a hint never uses cards the player can't see.
        """
        ready = self.hint_start(controller)
        return ready if isinstance(ready, dict) else card_hint(ready, self.engine, rng)

    def hint_start(self, controller: str) -> dict | BotView:
        """The quick part of a hint: a bidding hint outright, or the view a card hint is worked out from.
        The view is a copy, so the slow part (`card_hint`) can run while the board moves on."""
        if controller != self.controller_to_act():
            raise ValueError("it isn't your turn")
        seat = self.seat_to_act()
        if self.phase == BIDDING:
            dec = self.engine.choose(self.hands[seat], self.auction, self.score, self.vulnerability)
            return {"type": "hint", "phase": BIDDING, "call": dec.call,
                    "text": dec.text,
                    "convention": dec.rule.module if dec.rule else None}
        return view_for(self.play, self.auction, self.contract, self.vulnerability, seat, self.signals,
                        self.leads)

    # --- scoring -----------------------------------------------------------------------
    def _finish(self) -> None:
        self.phase = DONE
        tricks = self.play.declarer_tricks() if self.play else 0
        score_ns = 0
        if self.contract:
            vul = is_vulnerable(self.vulnerability, self.contract.declarer)
            s = duplicate_score(self.contract, tricks, vul)
            score_ns = s if same_side(self.contract.declarer, "N") else -s
        self.result = BoardResult(
            board=self.board, dealer=self.dealer, vulnerability=self.vulnerability,
            hands={s: self.hands[s].to_pbn() for s in SEATS},
            calls=list(self.auction.calls),
            contract=self.contract.to_dict() if self.contract else None,
            declarer_tricks=tricks, score_ns=score_ns,
            play=[[s, c] for s, c in (self.play.played_cards() if self.play else [])],
        )

    # --- views -------------------------------------------------------------------------
    def visible_hands(self, viewer: str | None) -> dict[str, list[str] | None]:
        out: dict[str, list[str] | None] = {s: None for s in SEATS}
        if self.phase == DONE:
            return {s: list(self.hands[s].cards) for s in SEATS}
        if viewer:
            out[viewer] = list(self.play.hands[viewer]) if self.play else list(self.hands[viewer].cards)
        if self.play and self.play.opening_lead_made():
            out[self.play.dummy] = list(self.play.hands[self.play.dummy])
        if self.play and viewer == self.play.dummy:
            # dummy sees declarer's hand too, to follow the play (and plays it, opposite a bot declarer)
            out[self.contract.declarer] = list(self.play.hands[self.contract.declarer])
        return out

    def state_for(self, viewer: str | None, all_hands: bool = False) -> dict:
        """What `viewer` sees; `all_hands` for someone watching. Someone watching sees what everyone at the table sees
        (dummy once it's down) and every hand only once the board is over: otherwise a player could open the table
        again in a second window, watch, and see the hidden hands of the board they're playing."""
        hands = self.visible_hands(viewer)
        counts = {s: (len(self.play.hands[s]) if self.play else 13) for s in SEATS}
        to_act = self.seat_to_act()
        controller = self.controller_to_act()
        legal_calls = (self.auction.legal_calls()
                       if self.phase == BIDDING and viewer == to_act else [])
        state = {
            "board": self.board,
            "dealer": self.dealer,
            "vulnerability": self.vulnerability,
            "phase": self.phase,
            "hands": hands,
            "counts": counts,
            "auction": [
                {"seat": s, "call": c, "meaning": self._meaning(i),
                 **({"why": self.bot_why(i)} if s in self.bot_seats else {})}
                for i, (s, c) in enumerate(self.auction.with_seats())
            ],
            "turn": to_act,
            "controller": controller,
            "your_turn": viewer is not None and controller == viewer,
            "can_undo": self.can_undo(),
            "can_claim": viewer is not None and not all_hands and self.can_claim(viewer),
            "claim_offer": self.claim_offer_for(viewer),
            "contract": self.contract.to_dict() if self.contract else None,
            "legal_calls": legal_calls,
            "call_meanings": {c: self._meaning_next(c) for c in legal_calls},
            "legal_cards": (self.play.legal_cards(to_act)
                            if self.phase == PLAYING and viewer == controller else []),
            "trick": None,
            "last_trick": None,
            "tricks_won": {"NS": 0, "EW": 0},
            "result": self.result.to_dict() if self.result else None,
        }
        if self.play:
            state["trick"] = self.play.current.to_dict()
            done = self.play.completed_tricks()
            if done:
                last = done[-1]
                state["last_trick"] = {**last.to_dict(), "winner": last.winner(self.play.trump)}
            state["tricks_won"] = {"NS": self.play.tricks_won("NS"),
                                   "EW": self.play.tricks_won("EW")}
            state["dummy"] = self.play.dummy
            state["card_why"] = self.card_reasons_shown()
        return state

    def card_reasons_shown(self) -> dict[str, dict]:
        """How the bots picked the cards they played, for the ⓘ on a played card. During the board only how it chose
        (layouts tried, or a random card at a low level) is shown: the odds of its other cards, and that a card was
        its only legal one, would give away its hand, so those come once the board is over."""
        played = {c for _, c in self.play.played_cards()} if self.play else set()
        out = {}
        for card, why in self.card_why.items():
            if card not in played:
                continue  # taken back by undo
            seen = {"play": self._card_in_trick(card)}
            if self.phase == DONE:
                out[card] = {**why, **seen}
                if "lead" in why:
                    out[card]["signal"] = why["lead"]
            else:  # its own card's odds say how sure it was, not what else it holds
                keep = ("level", "samples", "goal", "made", "tricks", "softened", "signal", "led")
                out[card] = {"kind": "hidden" if why["kind"] == "only" else why["kind"], **seen,
                             **{k: why[k] for k in keep if k in why}}
        return out

    def _card_in_trick(self, card: str) -> str:
        """What everyone at the table saw the card do: led, followed, ruffed or discarded, and who won the trick."""
        tricks = self.play.completed_tricks() + ([self.play.current] if self.play.current.cards else [])
        trump = self.play.trump
        name = lambda s: "dummy" if s == self.play.dummy else f"Bot {SEAT_NAME[s]}" if s in self.bot_seats else "you"
        for t in tricks:
            at = next((i for i, (_, c) in enumerate(t.cards) if c == card), None)
            if at is None:
                continue
            seat, lead = t.cards[at][0], t.lead_suit
            if at == 0:
                what = "It led this card."
            elif card[0] == lead:
                what = "It followed suit."
            elif trump != "N" and card[0] == trump:
                what = "It ruffed: it was out of the suit led."
            else:
                what = "It discarded: it was out of the suit led" + ("" if trump == "N" else " and chose not to ruff") + "."
            if t.is_complete():
                w = t.winner(trump)
                what += (" It won the trick." if w == seat else
                         " Its partner won the trick." if same_side(w, seat) else f" {name(w).capitalize()} won the trick.")
            return what
        return ""

    def bot_why(self, index: int) -> dict:
        """Why a bot made the call at `index`: the system rule it followed, and the convention that rule belongs to.
        Once the board is over, also the bot's hand and the other calls its hand fit there. During the board the
        bot's cards stay hidden, so a player can tap a bot's bid without learning more than the auction says."""
        calls = tuple(self.auction.calls[:index + 1])
        done = self.phase == DONE
        key = (id(self.engine), calls, done)
        if key not in self._why:
            self._why[key] = self._work_out_why(index, done)
        return self._why[key]

    def _work_out_why(self, index: int, done: bool) -> dict:
        before = Auction(self.dealer, list(self.auction.calls[:index]))
        call = self.auction.calls[index]
        rule = self.engine.explain_rule(self.auction, index)
        out: dict = {"rule": rule.name if rule else None, "convention": self._convention_title(rule),
                     "shown": shown_so_far(self.engine.infer(Auction(self.dealer, list(self.auction.calls[:index + 1])),
                                                             before.next_to_call)),
                     "instead": self._passed_over(before, call, rule)}
        if self.score is not None or self.bot.vul_for(self.vulnerability):
            seat = before.next_to_call
            dec = self.engine.choose(self.hands[seat], before, self.bot.score_for(self.score),
                                     self.bot.vul_for(self.vulnerability))
            if dec.note and dec.call == call:
                out["note"] = dec.note  # what the score or vulnerability changed; the same for any hand, so fine during the board
        if not done:
            return out
        seat = before.next_to_call
        hand = self.hands[seat]
        cands = self.engine.candidates(hand, before)
        chosen = next((d for d in cands if d.call == call), None)
        if chosen and chosen.rule:  # the rule that actually picked it, which may differ from the first that explains it
            out["rule"], out["convention"] = chosen.rule.name, self._convention_title(chosen.rule)
        lengths = hand.lengths()
        out["hand"] = {"hcp": hand.hcp, "lengths": {s: lengths[s] for s in "SHDC"}}
        out["also"] = [{"call": d.call, "rule": d.rule.name if d.rule else None, "text": d.meaning.text}
                       for d in cands if d.call != call and (d.call != "P" or call == "P")][:2]  # a pass is always possible
        return out

    def _passed_over(self, before: Auction, call: str, rule) -> list[dict]:
        """Calls the system tries before `rule` here, and what each would have shown: the bot's hand didn't fit them,
        which is part of why it made its call. Only the system's rules, never the bot's cards, so it's fine mid-board."""
        if rule is None or rule not in self.engine.rules:
            return []
        ctx = Ctx(before, self.engine)
        out, seen = [], {call}
        for r in self.engine.rules[:self.engine.rules.index(rule)]:
            try:
                if not r.when(ctx):
                    continue
                calls = r.candidate_calls(ctx)
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            for c in calls:
                if c in seen or c == "P":
                    continue
                seen.add(c)
                try:
                    out.append({"call": c, "text": r.meaning(ctx, c).text})
                except (IndexError, KeyError, TypeError, ValueError):
                    pass
                break  # one call per rule is plenty
            if len(out) >= 3:
                break
        return out

    def _convention_title(self, rule) -> str | None:
        if not rule:
            return None
        conv = next((c for c in self.engine.conventions if c.id == rule.module), None)
        return conv.title if conv else None

    def _meaning(self, index: int) -> dict:
        return self._meaning_dict(self.engine.explain(self.auction, index))

    def _meaning_next(self, call: str) -> dict:
        """What `call` would mean if the seat to act made it now."""
        return self._meaning_dict(self.engine.explain_next(self.auction, call))

    @staticmethod
    def _meaning_dict(m) -> dict:
        return {"text": m.text, "alert": m.artificial, "forcing": m.forcing or m.game_forcing,
                "hcp": list(m.hcp) if m.hcp != (0, 37) else None}
