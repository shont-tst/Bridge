"""Rule-based bidding engine driven by switchable convention modules."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from ..core.auction import Auction, is_bid
from ..core.cards import Hand
from .context import Ctx
from .evaluation import Eval
from .rules import Convention, Rule
from .shows import UNKNOWN, HandInference, Shows, shows

if TYPE_CHECKING:
    from .partscore import Score
    from .vul import Vul


@dataclass
class Decision:
    call: str
    rule: Rule | None
    meaning: Shows
    note: str | None = None  # why the score changed the system's call (rubber part scores, see partscore.py)
    note_only: bool = False  # the note says it all, so a hint shows just the note (#171)

    @property
    def text(self) -> str:
        """The call's meaning and note as a hint or the review says it: one short sentence each (#171)."""
        if not self.note:
            return self.meaning.text
        if self.note_only:
            return self.note
        return self.meaning.text.rstrip(".") + ". " + self.note

    def to_dict(self) -> dict:
        return {"call": self.call, "rule": self.rule.name if self.rule else None,
                "module": self.rule.module if self.rule else None,
                "meaning": self.meaning.to_dict()}


def natural_meaning(call: str) -> Shows:
    if is_bid(call) and call[1] != "N":
        return shows(f"Natural (no system meaning found): {call[1]} suit", **{call[1]: 4})
    if is_bid(call):
        return shows("Natural (no system meaning found): to play in notrump")
    return UNKNOWN


class BiddingEngine:
    def __init__(self, conventions: list[Convention], enabled: set[str] | None = None):
        self.conventions = conventions
        ids = {c.id for c in conventions}
        if enabled is None:
            enabled = {c.id for c in conventions if c.default_on}
        enabled = set(enabled) | {c.id for c in conventions if c.core}
        self.enabled = frozenset(enabled & ids)
        rules: list[Rule] = []
        for conv in conventions:
            if conv.id not in self.enabled:
                continue
            for r in conv.rules:
                if any(m in self.enabled for m in r.only_if_off):
                    continue
                if not all(m in self.enabled for m in r.needs):
                    continue
                rules.append(r)
        # stable sort keeps registration order among equal priorities
        self.rules = sorted(rules, key=lambda r: -r.priority)
        self._explain = lru_cache(maxsize=20000)(self._explain_uncached)
        self._explain_rule = lru_cache(maxsize=20000)(self._explain_rule_uncached)

    # --- choosing a call ----------------------------------------------------------
    def candidates(self, hand: Hand, auction: Auction, bonus: int = 0, vul: str | None = None) -> list[Decision]:
        """All qualifying calls, best first (one per rule). `bonus` counts that many extra points. `vul` tells the
        rules who is vulnerable (some judge risk by it, see vul.py); None bids as if nobody were told."""
        ctx = Ctx(auction, self, vul)
        ev = Eval(hand, bonus)
        out: list[Decision] = []
        seen: set[str] = set()
        for rule in self.rules:
            if not rule.when(ctx):
                continue
            try:
                calls = [c for c in rule.candidate_calls(ctx) if rule.hand(ev, ctx, c)]
            except (IndexError, KeyError, TypeError, ValueError):
                continue  # a rule that doesn't expect this auction (e.g. no room left to bid)
            if not calls:
                continue
            if rule.prefer is not None:
                calls.sort(key=lambda c: rule.prefer(ev, ctx, c))
            c = calls[0]
            if c in seen:
                continue
            seen.add(c)
            out.append(Decision(c, rule, rule.meaning(ctx, c)))
        return out

    def choose(self, hand: Hand, auction: Auction, score: "Score | None" = None,
               vul: "str | Vul | None" = None) -> Decision:
        """The system's call. With a rubber `score`, a part score can change it (see partscore.py). `vul` is who is
        vulnerable (a string, or a `Vul` saying which of vul.py's changes to use): see vul.py."""
        from .vul import Vul
        if isinstance(vul, str):
            vul = Vul(vul)
        cands = self.candidates(hand, auction, vul=vul.vulnerability if vul else None)
        dec = cands[0] if cands else Decision("P", None, UNKNOWN)
        if score is not None and score.matters:
            from .partscore import adjust
            dec = adjust(self, hand, auction, dec, score)
        elif vul is not None and vul.use:
            from .vul import adjust as vul_adjust
            dec = vul_adjust(self, hand, auction, dec, vul)
        return dec

    def fits(self, hand: Hand, auction: Auction, call: str) -> bool:
        """Whether some rule of the system allows `call` with this hand here (not necessarily its first choice)."""
        ctx = Ctx(auction, self)
        ev = Eval(hand)
        return any(rule.when(ctx) and call in rule.candidate_calls(ctx) and rule.hand(ev, ctx, call)
                   for rule in self.rules)

    # --- understanding calls --------------------------------------------------------
    def explain(self, auction: Auction, index: int) -> Shows:
        """Meaning of the call at `index`, given the calls before it."""
        return self._explain(auction.dealer, tuple(auction.calls[:index + 1]))

    def _explain_uncached(self, dealer: str, calls: tuple[str, ...]) -> Shows:
        prefix = Auction(dealer, list(calls[:-1]))
        call = calls[-1]
        ctx = Ctx(prefix, self)
        for rule in self.rules:
            if rule.when(ctx) and call in rule.candidate_calls(ctx):
                try:
                    return rule.meaning(ctx, call)
                except (IndexError, KeyError, TypeError, ValueError):
                    break  # a meaning function that doesn't expect this call
        return natural_meaning(call)

    def explain_rule(self, auction: Auction, index: int) -> Rule | None:
        return self._explain_rule(auction.dealer, tuple(auction.calls[:index + 1]))

    def _explain_rule_uncached(self, dealer: str, calls: tuple[str, ...]) -> Rule | None:
        prefix = Auction(dealer, list(calls[:-1]))
        call = calls[-1]
        ctx = Ctx(prefix, self)
        for rule in self.rules:
            if rule.when(ctx) and call in rule.candidate_calls(ctx):
                return rule
        return None

    def infer(self, auction: Auction, seat: str) -> HandInference:
        """Everything `seat`'s calls so far have shown."""
        inf = HandInference()
        for i, (s, _) in enumerate(auction.with_seats()):
            if s == seat:
                inf.add(self.explain(auction, i))
        return inf

    def explain_next(self, auction: Auction, call: str) -> Shows:
        """Meaning of `call` if made now by the seat to act (for hints/UI)."""
        a = auction.copy()
        a.calls.append(call)
        return self.explain(a, len(a.calls) - 1)
