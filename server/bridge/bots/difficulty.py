"""Fixed difficulty slider for Phase 1 (adaptive tuning comes in Phase 3).

Level 1 is a beginner that misjudges often; level 10 is a strong double-dummy
Monte Carlo player. Knobs:
  samples      — deals sampled per decision (more = better inference)
  temperature  — softmax temperature over card scores (0 = always best card)
  blunder      — chance of playing a random legal card
  inference    — whether to use the auction when sampling hidden hands
  group        — whether the softened pick counts cards of a suit that do the same in every layout as one choice
  notice       — chance it also skips a card another beats in every layout (a free ruff, a sure winner)
  forget       — chance it has lost track of a small side-suit card played earlier, or of a hand showing out
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Difficulty:
    level: int
    samples: int
    temperature: float
    blunder: float
    inference: bool
    group: bool = False
    notice: float = 0.0
    forget: float = 0.0

    def to_dict(self) -> dict:
        return {"level": self.level, "samples": self.samples, "temperature": self.temperature,
                "blunder": self.blunder, "inference": self.inference,
                "group": self.group, "notice": self.notice, "forget": self.forget}


# Tuned (2026-11-12) so each level up gives away about a fifth fewer tricks as declarer, from about 3.9 a hand at
# level 1 to about 0.4 at level 10: measured against published play, a club player sits near level 6, regional
# tournament players near 7 and national to world-class players near 8 (docs/bots.md). Re-measure with
# scripts.calibrate after changing any of these.
_SAMPLES = [4, 6, 8, 10, 12, 16, 20, 24, 32, 48]
_TEMP = [1.5, 0.8, 0.65, 0.85, 0.4, 0.38, 0.33, 0.26, 0.08, 0.0]
# From level 3, cards that do the same count as one choice. From level 4 a free ruff or sure winner is never passed
# up (a ruff is an obvious move that intermediate players don't miss); levels 1 to 3 still miss them.
GROUP_FROM = 3
_NOTICE = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
_BLUNDER = [0.15, 0.08, 0.07, 0.085, 0.04, 0.04, 0.03, 0.02, 0.005, 0.0]
# What the middle levels get wrong instead is keeping track of the side suits (sampler.misremembered): the chance
# that a small card played earlier, or a hand showing out, has slipped the bot's mind. Levels 1 to 3 err enough
# already, and levels 8 to 10 remember everything.
_FORGET = [0.0, 0.0, 0.0, 1.0, 0.8, 0.2, 0.05, 0.0, 0.0, 0.0]


def difficulty(level: int) -> Difficulty:
    level = max(1, min(10, int(level)))
    i = level - 1
    return Difficulty(level, _SAMPLES[i], _TEMP[i], _BLUNDER[i], inference=level >= 3,
                      group=level >= GROUP_FROM, notice=_NOTICE[i], forget=_FORGET[i])
