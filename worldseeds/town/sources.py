"""Second-hand knowledge with controlled reliability: notes by other agents and villager testimony.

Both kinds of source make *claims* about the hidden laws, ``(hypothesis space, value)`` pairs
in the same spaces as ``TownSeedMemory``. A source is wrong at a controlled rate, and its
errors are *consistent* (the same author or villager is always wrong about the same law),
so a careful agent can learn whom to trust by checking claims against its own experience.

    notes       LibraryArchive.write_notes: several authors write what they learned; each
                claim is corrupted with the author's error rate
    testimony   ``ask <villager>``: villagers say what their job tells them (the baker knows
                seasons, the florist soil, the innkeeper where people spend middays) and
                what gifts they love; a fixed share of villagers are unreliable
"""

from __future__ import annotations

from ..world import _h
from .seed import CATEGORIES, CROPS, GIFT_ATTRS, MIDDAY_PLACES, SEASONS, SOILS

NOTE_AUTHORS = ["Ada", "Ben", "Cleo"]

# what each job can tell you about (besides their own taste in gifts)
JOB_TOPIC = {"baker": "season", "doctor": "season", "florist": "soil", "librarian": "soil",
             "innkeeper": "midday", "fisher": "midday", "smith": "gift", "miner": "gift"}

_VALUES = {"soil": SOILS, "season": SEASONS, "gift_attr": GIFT_ATTRS, "likes": CATEGORIES,
           "midday_place": MIDDAY_PLACES}


def values_of(space: str) -> list[str]:
    return _VALUES[space.split(".")[0]]


def unit(*parts) -> float:
    """Deterministic uniform number in [0, 1) from any key."""
    return _h(*parts) / float(16 ** 12)


def wrong_value(space: str, value: str, *salt) -> str:
    """A consistent wrong value for ``space`` (same salt -> same lie)."""
    others = [v for v in values_of(space) if v != value]
    return others[_h("wrong", space, *salt) % len(others)]


def maybe_corrupt(space: str, value: str, rate: float, *salt) -> tuple[str, bool]:
    if rate > 0 and unit("err", space, *salt) < rate:
        return wrong_value(space, value, *salt), True
    return value, False


def describe(space: str, value: str, speaker_job: str | None = None) -> str:
    if space.startswith("soil."):
        return f"{space[5:]} only does well in {value} soil"
    if space.startswith("season."):
        return f"{space[7:]} only grows in {value}"
    if space == "midday_place":
        return {"home": "at midday everyone stays home", "work": "at midday everyone is at work"}.get(
            value, f"at midday everyone goes to the {value}")
    if space == "gift_attr":
        return ("we all love gifts that match the colour of our shirt" if value == "color"
                else "what we love depends on our trade")
    if space.startswith("likes."):
        job = space[6:]
        return f"I love {value} things" if job == speaker_job else f"a {job} loves {value} things"
    return f"{space} = {value}"


def testimony(world, v, k: int) -> list[tuple[str, str]]:
    """True claims villager ``v`` would make on their ``k``-th question (before any lying)."""
    L, job = world.laws, v.fine["job"]
    claims = [("gift_attr", L.gift_attr)]
    if L.gift_attr == "category":
        claims.append((f"likes.{job}", L.likes[job]))
    topic = JOB_TOPIC[job]
    for j in range(2):  # two crops per answer, a different pair each time you ask
        crop = CROPS[(2 * k + j + _h(v.id)) % len(CROPS)]
        if topic == "season":
            claims.append((f"season.{crop}", L.season_for[crop]))
        elif topic == "soil":
            claims.append((f"soil.{crop}", L.soil_for[crop]))
    if topic == "midday":
        claims.append(("midday_place", L.midday_place))
    return claims
