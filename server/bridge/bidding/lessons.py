"""Learning material for each switchable convention: an explainer, example
auctions, and a recipe for practice deals where the convention comes up.

Example auctions are only calls: their meanings are looked up in the bidding
engine when the page is shown, so the explainer always says exactly what the
bots play. Practice deals are found by rejection sampling: a cheap test on
the two hands that matter, then a full auction by the engine to confirm the
convention is actually used by North or South.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable

from ..core.auction import Auction
from ..core.cards import SEATS, Hand, full_deck, partner
from .engine import BiddingEngine
from .evaluation import Eval
from .rules import Rule

# A test on (opener's hand, responder's hand) as Evals.
PairTest = Callable[[Eval, Eval], bool]

STUDENT = "S"  # South is always a human, so practice puts the convention in South's hands


@dataclass
class Lesson:
    id: str
    explainer: list[str]                 # paragraphs
    examples: list[tuple[str, list[str]]] = field(default_factory=list)  # (title, calls from `dealer`)
    opening: tuple[str, ...] = ()        # opener's first call in a practice deal
    student: str = "responder"           # who uses it: "opener", "responder", or (over their opening) "doubler"
    quick: Callable[[Eval], bool] = lambda o: True  # cheap pre-test of opener's hand
    responder: PairTest = lambda o, r: True  # test on (opener, the other hand dealt): partner, or South over theirs
    # A lesson on a switchable convention shares its id. A lesson on part of the base system has a title of its
    # own and says which of the system's rules it is about.
    title: str = ""
    description: str = ""
    rules: tuple[str, ...] = ()
    dealer: str = "N"

    @property
    def conv(self) -> str | None:
        """The convention this lesson teaches, if it's a switchable one."""
        return None if self.rules else self.id

    def uses(self, rule: Rule) -> bool:
        return rule.name in self.rules if self.rules else rule.module == self.id

    def seats(self) -> tuple[str, str]:
        """(opener, other hand dealt) for practice deals; the student sits South."""
        if self.student == "opener":
            return STUDENT, partner(STUDENT)
        if self.student in ("doubler", "overcaller"):
            return "E", STUDENT  # East opens, South acts over it
        return partner(STUDENT), STUDENT


def _major(r: Eval, n: int) -> bool:
    return r.len("H") >= n or r.len("S") >= n


def _longer_major(h: Eval) -> str:
    return "S" if h.len("S") >= h.len("H") else "H"


LESSONS: dict[str, Lesson] = {l.id: l for l in [
    Lesson(
        "stayman",
        ["After partner opens 1NT, 2♣ asks: \"do you have a four-card major?\" Opener answers "
         "2♦ (no), 2♥ (four hearts, maybe spades too) or 2♠ (four spades, not four hearts).",
         "Use it with a four-card major and 8+ points, so that you can still invite or bid game "
         "after the answer. Over 2NT, the same question is 3♣.",
         "Garbage Stayman: with 0-7 and 5-4 in the majors you may also bid 2♣, and pass whatever "
         "partner says (over 2♦, bid two of your five-card major to play)."],
        [("Fit found", ["1N", "P", "2C", "P", "2H", "P", "4H", "P", "P", "P"]),
         ("No fit", ["1N", "P", "2C", "P", "2D", "P", "3N", "P", "P", "P"])],
        opening=("1N",), quick=lambda o: 15 <= o.hcp <= 17,
        responder=lambda o, r: (r.len("H") == 4 or r.len("S") == 4) and r.hcp >= 8,
    ),
    Lesson(
        "jacoby",
        ["Over 1NT, 2♦ shows five or more hearts and 2♥ shows five or more spades. Opener "
         "\"completes the transfer\" by bidding the next suit up, so the strong hand becomes "
         "declarer.",
         "Then: with 0-7 pass; with 8-9 raise to three (six cards) or bid 2NT (five cards); with "
         "10+ bid game in the major (six cards) or 3NT (five cards), and opener chooses.",
         "Over 2NT the transfers are 3♦ and 3♥."],
        [("Weak hand", ["1N", "P", "2H", "P", "2S", "P", "P", "P"]),
         ("Game choice", ["1N", "P", "2D", "P", "2H", "P", "3N", "P", "P", "P"])],
        opening=("1N",), quick=lambda o: 15 <= o.hcp <= 17,
        responder=lambda o, r: _major(r, 5),
    ),
    Lesson(
        "minor_transfer",
        ["Over 1NT, 2♠ forces opener to bid 3♣. Responder passes with long clubs, or bids 3♦ "
         "with long diamonds, and opener passes.",
         "It is a way to play a part score in a six-card minor with a weak hand (0-7). It "
         "needs Jacoby transfers to be on."],
        [("Clubs", ["1N", "P", "2S", "P", "3C", "P", "P", "P"]),
         ("Diamonds", ["1N", "P", "2S", "P", "3C", "P", "3D", "P", "P", "P"])],
        opening=("1N",), quick=lambda o: 15 <= o.hcp <= 17,
        responder=lambda o, r: (r.len("C") >= 6 or r.len("D") >= 6) and r.hcp <= 7
        and not _major(r, 4),
    ),
    Lesson(
        "gerber",
        ["Over 1NT or 2NT, 4♣ asks partner how many aces they hold: 4♦ = 0 or 4, 4♥ = 1, "
         "4♠ = 2, 4NT = 3. 5♣ then asks for kings in the same way.",
         "Use it with slam values (about 33 combined points) when you know you want to play in "
         "notrump. If two aces are missing, sign off in 4NT."],
        [("Two aces", ["1N", "P", "4C", "P", "4S", "P", "6N", "P", "P", "P"])],
        opening=("1N", "2N"), quick=lambda o: 15 <= o.hcp <= 21,
        responder=lambda o, r: r.hcp >= 16 and r.balanced,
    ),
    Lesson(
        "blackwood",
        ["Once a suit is agreed and slam is in view, 4NT asks for aces: 5♣ = 0 or 4, 5♦ = 1, "
         "5♥ = 2, 5♠ = 3. 5NT then asks for kings (6♣ = 0 or 4, and so on), and promises that "
         "all the aces are held.",
         "If two aces are missing, sign off in five of the agreed suit."],
        [("Slam reached", ["1S", "P", "3S", "P", "4N", "P", "5H", "P", "6S", "P", "P", "P"])],
        opening=("1H", "1S"), quick=lambda o: o.hcp >= 16 and _major(o, 5),
        student="opener",
        responder=lambda o, r: r.hcp >= 13 and r.len(_longer_major(o)) >= 4,
    ),
    Lesson(
        "strong_2c",
        ["2♣ is the one opening partner may not pass: 22+ points, any shape. Responder bids "
         "2♦ (waiting, 0-7) or makes a positive response with 8+ or an ace and a king.",
         "Opener's 2NT rebid shows 22-24 balanced and can be passed; any other rebid forces "
         "to game."],
        [("Balanced", ["2C", "P", "2D", "P", "2N", "P", "3N", "P", "P", "P"])],
        opening=("2C",), quick=lambda o: o.hcp >= 19,
        student="opener",
    ),
    Lesson(
        "weak_twos",
        ["2♦, 2♥ and 2♠ show a good six-card suit and 5-10 points, with no outside four-card "
         "major. They take bidding space away from the opponents.",
         "Partner raises to three with three-card support (still pre-emptive), or bids 2NT with "
         "15+ to ask for a feature: with a maximum, opener shows an outside ace or king (3NT "
         "with two of the top three trump honors); with a minimum, opener rebids the suit."],
        [("Pre-emptive raise", ["2H", "P", "3H", "P", "P", "P"]),
         ("Feature ask", ["2S", "P", "2N", "P", "3D", "P", "4S", "P", "P", "P"])],
        opening=("2D", "2H", "2S"), quick=lambda o: o.hcp <= 11 and max(o.shape) == 6,
        student="opener",
    ),
    Lesson(
        "preempts",
        ["With a good seven-card suit and 5-10 points, open at the three level (with eight "
         "cards, the four level). It makes life hard for the opponents.",
         "Partner raises with three-card support and bids game or a new suit (forcing) with "
         "16+. Opener does not bid again unless partner bids a new suit."],
        [("Raise", ["3H", "P", "4H", "P", "P", "P"])],
        opening=("3C", "3D", "3H", "3S", "4C", "4D", "4H", "4S"),
        quick=lambda o: o.hcp <= 11 and max(o.shape) >= 7,
        student="opener",
    ),
    Lesson(
        "takeout_doubles",
        ["When an opponent opens one of a suit, double asks partner to pick a suit. It shows opening "
         "values (12+) with shortness in their suit and three or four cards in each of the others, "
         "or any strong hand (17+) that will bid again.",
         "Partner must answer, even with nothing: with 0-8 bid your longest unbid suit (a four-card "
         "major first), with 9-12 jump in it, and with 13+ bid game or cue-bid their suit. "
         "Notrump answers promise a stopper in their suit.",
         "Partner passes only with long, strong trumps in their suit, to defend doubled."],
        [("Partner answers", ["1H", "X", "P", "1S", "P", "P", "P"]),
         ("Jump with 9-12", ["1D", "X", "P", "2H", "P", "4H", "P", "P", "P"])],
        opening=("1C", "1D", "1H", "1S"), student="doubler",
        responder=lambda o, r: r.hcp >= 12,
        title="Takeout doubles", description="Double their opening to find your best suit, and how to answer.",
        rules=("Takeout double", "Strong takeout double", "Advance a takeout double"), dealer="E",
    ),
    Lesson(
        "overcalls",
        ["Over their opening, bid a good five-card suit (two honors, or one of the top three with 11+ points) "
         "with 8-16 HCP at the one level, or 10-16 at the two level. It competes for the part score and tells partner "
         "what to lead.",
         "1NT over their opening shows 15-18 balanced with a stopper in their suit, the same as a "
         "1NT opening.",
         "A jump overcall is weak: 5-10 HCP with a six-card suit at the two level, seven cards at "
         "the three level.",
         "Partner raises with support (three cards for a major), cue-bids their suit with support "
         "and 10+, or bids notrump with a stopper."],
        [("Simple overcall", ["1D", "1S", "P", "2S", "P", "P", "P"]),
         ("1NT overcall", ["1H", "1N", "P", "3N", "P", "P", "P"])],
        opening=("1C", "1D", "1H", "1S"), student="overcaller",
        responder=lambda o, r: 8 <= r.hcp <= 18 and (max(r.shape) >= 5 or r.balanced),
        title="Overcalls", description="Bid your own suit, or 1NT, over their opening.",
        rules=("Simple overcall", "Weak jump overcall", "1NT overcall", "Advance an overcall"), dealer="E",
    ),
    Lesson(
        "major_raises",
        ["With three or more cards in partner's 1♥ or 1♠, raise straight away. Count your points with "
         "shortness once you have the fit: void 5, singleton 3, doubleton 1.",
         "6-9 points: raise to two. 10-12: jump to three (a limit raise, invitational). 13+: game "
         "values, so bid a new suit first, or 2NT if you play Jacoby 2NT.",
         "Opener passes a raise with a minimum, makes a game try with 16-18, and bids game with 19+. "
         "Over a limit raise, opener bids game with 14+."],
        [("Single raise", ["1H", "P", "2H", "P", "P", "P"]),
         ("Limit raise", ["1S", "P", "3S", "P", "4S", "P", "P", "P"])],
        opening=("1H", "1S"), quick=lambda o: max(o.len("H"), o.len("S")) >= 5,
        responder=lambda o, r: r.len(_longer_major(o)) >= 3 and 6 <= r.hcp <= 12,
        title="Raising partner's major", description="Single and limit raises of 1♥ and 1♠, counting shortness.",
        rules=("Single raise", "Limit raise", "Opener after a raise"),
    ),
    Lesson(
        "jacoby_2nt",
        ["Over partner's 1♥ or 1♠, 2NT shows four or more cards in partner's major and 13+ points. "
         "It forces to game, so the two of you can look for slam below it.",
         "Opener describes the hand: three of a new suit shows a singleton or void there, three of "
         "the major shows 18+ without one, 3NT shows 15-17, and four of the major shows a minimum.",
         "With a singleton facing your low cards, slam can make on fewer points. Blackwood 4NT "
         "then checks for aces."],
        [("Minimum", ["1S", "P", "2N", "P", "4S", "P", "P", "P"]),
         ("Shortness", ["1H", "P", "2N", "P", "3C", "P", "4H", "P", "P", "P"])],
        opening=("1H", "1S"), quick=lambda o: max(o.len("H"), o.len("S")) >= 5,
        responder=lambda o, r: r.len(_longer_major(o)) >= 4 and r.hcp >= 11,
    ),
    Lesson(
        "negative_doubles",
        ["When partner opens one of a suit and the next player overcalls a suit, double is not for "
         "penalty. It shows the unbid major (exactly four cards), or both unbid majors, and 6+ "
         "points (8+ over a two-level overcall). Over 1♥-1♠ it shows both minors.",
         "With five cards in a major and enough to bid it, bid the suit instead. With length in "
         "their suit, pass: partner will often double again and you can defend.",
         "Opener answers like a takeout double: bid the major with four cards (jump with 16-18), "
         "rebid a six-card suit, or bid notrump with a stopper."],
        [("One major", ["1C", "1H", "X", "P", "1S", "P", "P", "P"]),
         ("Fit found", ["1D", "1S", "X", "P", "2H", "P", "4H", "P", "P", "P"])],
        opening=("1C", "1D", "1H", "1S"),
        responder=lambda o, r: r.hcp >= 6 and bool(r.four_card_majors()),
        dealer="N",
    ),
]}


def examples_for(engine: BiddingEngine, lesson: Lesson) -> list[dict]:
    out = []
    for title, calls in lesson.examples:
        a = Auction(lesson.dealer, list(calls))
        out.append({
            "title": title,
            "calls": [{"seat": s, "call": c, **engine.explain(a, i).to_dict()}
                      for i, (s, c) in enumerate(a.with_seats())],
        })
    return out


def uses_lesson(engine: BiddingEngine, hands: dict[str, Hand], dealer: str,
                lesson: Lesson) -> bool:
    """Bid the deal out with the engine: does North or South use what `lesson` teaches?"""
    a = Auction(dealer)
    while not a.is_complete():
        seat = a.next_to_call
        dec = engine.choose(hands[seat], a)
        if seat in "NS" and dec.rule and lesson.uses(dec.rule):
            return True
        a.add(dec.call)
    return False


def _deal_around(opener: str, o: Hand, responder: str, r: Hand,
                 rng: random.Random) -> dict[str, Hand]:
    rest = [c for c in full_deck() if c not in o.cards and c not in r.cards]
    rng.shuffle(rest)
    others = [s for s in SEATS if s not in (opener, responder)]
    return {opener: o, responder: r,
            others[0]: Hand.of(rest[:13]), others[1]: Hand.of(rest[13:])}


def lesson_title(lesson_id: str) -> str:
    from .conventions import BY_ID
    if lesson_id == SIGNALS:
        return SIGNALS_PAGE["title"]
    if lesson_id == LEADS:
        return LEADS_PAGE["title"]
    lesson = LESSONS[lesson_id]
    return lesson.title or BY_ID[lesson_id].title


def lesson_list() -> list[dict]:
    """Lessons on the base system (those on switchable conventions are listed with the conventions)."""
    return [{"id": l.id, "title": l.title, "description": l.description}
            for l in LESSONS.values() if l.conv is None]


def practice_deal(engine: BiddingEngine, conv: str, rng: random.Random,
                  budget: float = 3.0) -> tuple[dict[str, Hand], str]:
    """A deal (and dealer) where North or South uses what lesson `conv` teaches.

    The opener is dealt first by rejection on the engine's opening call, then
    the responder, then the opponents at random; the whole auction confirms
    it. If the time budget runs out, the last candidate is returned anyway.
    """
    lesson = LESSONS[conv]
    opener, responder = lesson.seats()
    start = time.monotonic()
    candidate: dict[str, Hand] | None = None
    while candidate is None or time.monotonic() - start < budget:
        o = _hand_where(rng, lambda h: engine.choose(h, Auction(opener)).call in lesson.opening,
                        exclude=())
        r = _hand_where(rng, lambda h: lesson.responder(Eval(o), Eval(h)), exclude=o.cards,
                        tries=3000)
        if r is None:
            continue
        candidate = _deal_around(opener, o, responder, r, rng)
        if uses_lesson(engine, candidate, opener, lesson):
            break
    return candidate, opener


def _hand_where(rng: random.Random, test: Callable[[Hand], bool], exclude,
                tries: int = 20000) -> Hand | None:
    deck = [c for c in full_deck() if c not in exclude]
    for _ in range(tries):
        h = Hand.of(rng.sample(deck, 13))
        if test(h):
            return h
    return None



# --- Signals: a lesson on defense, not bidding (bots/signals.py) -----------------------------------------------------

SIGNALS = "signals"
SIGNALS_PAGE = {
    "id": SIGNALS, "title": "Signals", "core": True, "lesson": True,
    "description": "Defenders tell partner about their cards with the spot cards they play.",
    "explainer": [
        "When you can't win a trick, the card you play can still talk to partner. A high spot card (like the 8) "
        "and a low one (the 2) say different things. Only spot cards from 2 to 9 signal.",
        "Attitude: when partner leads a suit, play high to say \"I like it, keep going\" (you hold the ace, king or "
        "queen), and low to say \"please switch.\"",
        "Count: when declarer leads a suit, play high then low with an even number of cards, and low then high with "
        "an odd number. It helps partner count declarer's cards.",
        "Suit preference: when liking the suit can't matter, the card asks for another suit. When you lead a card "
        "for partner to ruff, a high card asks partner to return the higher of the other two side suits, and a low "
        "card the lower one. The same goes when dummy has one card or none in the suit partner leads.",
        "Your first discard: a high card in a suit you like, or a low card in one you don't.",
        "Upside-down signals turn attitude and count around: low says \"I like it,\" and low then high shows an "
        "even number. Suit preference stays the same.",
        "The bots signal the first time a suit is played, never in trumps, from strength 3 up. They read your "
        "signals too.",
    ],
    "situations": [
        {"title": "Partner leads ♥K", "hand": "You hold ♥Q 8 2.",
         "standard": "Play ♥8: you like hearts.", "upside": "Play ♥2: you like hearts."},
        {"title": "Partner leads ♠A", "hand": "You hold ♠9 6 3.",
         "standard": "Play ♠3: please switch.", "upside": "Play ♠9: please switch."},
        {"title": "Declarer leads ♦K", "hand": "You hold ♦7 4.",
         "standard": "Play ♦7, then ♦4: an even number.", "upside": "Play ♦4, then ♦7: an even number."},
    ],
    "practice_note": "Practice deals are bid for you, with East or West declaring, so you start on defense with North.",
}


def signals_deal(engine: BiddingEngine, rng: random.Random, tries: int = 300,
                 declarers: str = "EW") -> tuple[dict[str, Hand], str]:
    """A deal (and dealer) the engine bids to a contract by East or West (`declarers`), so South defends."""
    from ..core.cards import deal_random
    hands, dealer = deal_random(rng), "N"
    for _ in range(tries):
        hands, dealer = deal_random(rng), rng.choice(SEATS)
        a = Auction(dealer)
        while not a.is_complete():
            a.add(engine.choose(hands[a.next_to_call], a).call)
        c = a.contract()
        if c and c.declarer in declarers:
            break
    return hands, dealer


# --- Opening leads: also a lesson on defense (bots/leads.py) ---------------------------------------------------------

LEADS = "leads"
LEADS_PAGE = {
    "id": LEADS, "title": "Opening leads", "core": True, "lesson": True,
    "description": "Which card to lead, once you've picked the suit.",
    "explainer": [
        "The opening lead is the first card of the hand, made before dummy goes down. First pick the suit: often "
        "partner's suit, or your longest. Then the card you lead in it tells partner about your cards. These are "
        "Standard leads, the same against a trump contract and no trump.",
        "Touching high cards: lead the top one. From ♠K Q 5 lead ♠K, from ♥J 10 3 lead ♥J. With a gap below the "
        "top honor, lead the top of the touching pair: from ♠K J 10 4 lead ♠J.",
        "Ace and king: lead the ace. Against a trump contract, lead an ace rather than a small card from that suit.",
        "Two cards: lead the top one. Three cards: low from three to an honor (♣K 7 3: lead ♣3), and the top of "
        "three small (♦8 6 2: lead ♦8).",
        "Four cards or more: lead the fourth one down, \"fourth best.\" From ♠K J 6 4 2 lead ♠4. Partner then knows "
        "you hold three cards higher than the 4.",
        "The bots lead this way at every level, and from strength 3 up they read your lead too, as partner and as "
        "declarer. With Opening leads off, they lead whichever card in the suit works best and don't read leads.",
    ],
    "situations": [
        {"title": "Against 4♥", "hand": "You lead ♠ from ♠K Q 5.", "play": "Lead ♠K: top of a sequence."},
        {"title": "Against 3NT", "hand": "You lead ♦ from ♦K J 6 4 2.", "play": "Lead ♦4: fourth best."},
        {"title": "Against 4♠", "hand": "You lead ♣ from ♣K 7 3.", "play": "Lead ♣3: low from three to an honor."},
        {"title": "Against 2♥", "hand": "You lead ♦ from ♦8 3.", "play": "Lead ♦8: top of two cards."},
    ],
    "practice_note": "Practice deals are bid for you, with East declaring, so you start by making the opening lead.",
}
