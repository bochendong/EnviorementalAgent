"""Skins: the same hidden laws under a different story (``--skin drug``).

A skin is a one-to-one word map applied at the agent's tool layer: everything the agent reads
(instructions, observations, the canvas) is translated forward, and the verbs and ids it sends
back are translated in reverse before they reach the world. The world, its laws, the heuristic
agents and the metrics are untouched, so a skinned run is directly comparable to a plain one.

The drug-discovery skin turns SeedVille into a research institute:

    crop (turnip, melon ...)   -> compound (AX-101, AX-102 ...)
    soil (loam, clay ...)      -> target (kinase, protease ...)
    season (spring ...)        -> protocol (alpha ...)
    plot / plant / water       -> well / dose / incubate
    harvest a ripe crop        -> assay an active compound
    villagers and their jobs   -> experts (chemist, engineer ...)
    the farm, the shop ...     -> the lab, the supplier ...
    screen (cheap noisy test)  -> dock (an in-silico docking run)

Which compound works against which target under which protocol is exactly the town's hidden law
of which crop grows in which soil in which season. Pictures (``--context image``) keep the farm
sprites: only text is reskinned.
"""

from __future__ import annotations

import re

from .town.seed import CROPS, EXTRA_CROPS

_DRUG = {
    # the farming law -> the drug-discovery law
    "plots": "wells", "plot": "well", "soils": "targets", "soil": "target", "seasons": "protocols",
    "season": "protocol", "spring": "alpha", "summer": "beta", "fall": "gamma", "winter": "delta",
    "loam": "kinase", "clay": "protease", "sand": "receptor", "peat": "channel",
    "crops": "compounds", "crop": "compound", "seeds": "samples", "packets": "vials", "packet": "vial",
    "watering can": "incubator", "watering cans": "incubators",
    "plant": "dose", "planted": "dosed", "planting": "dosing", "plants": "doses",
    "water": "incubate", "watered": "incubated", "watering": "incubating", "unwatered": "unincubated",
    "harvest": "assay", "harvested": "assayed", "harvests": "assays", "harvesting": "assaying",
    "ripe": "active", "withered": "toxic", "wither": "turn toxic", "dormant": "inert", "growing": "developing",
    "grow": "develop", "grows": "develops", "grew": "developed", "sprouted": "bound",
    "screen": "dock", "screens": "docks", "screening": "docking", "test kit": "docking model",
    "rained": "was humid", "rainy": "humid", "rain": "humidity", "sunny": "dry",
    # people and places
    "villagers": "experts", "villager": "expert", "friendship": "trust", "farmer": "scientist",
    "farm": "lab", "plaza": "atrium", "shop": "supplier", "general store": "supply room", "forest": "greenhouse",
    "baker": "chemist", "bakery": "chemlab", "smith": "engineer", "smithy": "workshop",
    "florist": "botanist", "flower shop": "botany lab", "miner": "crystallographer", "mine": "xray",
    "mine entrance": "x-ray room", "fisher": "oceanographer", "pier": "marine", "doctor": "clinician",
    "librarian": "archivist", "library": "archive", "innkeeper": "manager", "inn": "canteen",
    "home": "office", "house": "suite", "mountain": "server room", "beach": "cold room",
    "SeedVille": "PharmaVille", "town": "institute", "towns": "institutes", "houses": "suites", "trophy": "patent", "coins": "credits",
    "bed": "cot", "sleep": "rest", "talk": "consult", "buy": "order",
    # the shelves of the library (ids such as shelf_farming)
    "farming": "discovery", "gifting": "favors",
}
# crops become compound codes
_DRUG.update({c: f"AX-{101 + i}" for i, c in enumerate(CROPS + EXTRA_CROPS)})

SKINS = {"none": None, "drug": _DRUG}


def _pattern(words) -> re.Pattern:
    # longest first, so "turnip_greens" and "watering can" win over "turnip" and "watering";
    # whole words only, but digits and underscores may touch (home1, shelf_farming)
    alts = sorted(set(words), key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(w) for w in alts) + r")(?![A-Za-z])", re.IGNORECASE)


def _case(src: str, dst: str) -> str:
    if src.isupper() and len(src) > 1:
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


class Skin:
    def __init__(self, name: str):
        table = SKINS[name]
        if table is None:
            raise ValueError("no skin")
        self.name = name
        self.fwd = {k.lower(): v for k, v in table.items()}
        self.rev = {v.lower(): k for k, v in table.items()}
        if len(self.rev) != len(self.fwd):
            raise ValueError(f"skin {name!r} is not one-to-one")
        self._f, self._r = _pattern(self.fwd), _pattern(self.rev)

    def out(self, text: str) -> str:
        """World -> agent."""
        if not text:
            return text
        return self._f.sub(lambda m: _case(m.group(0), self.fwd[m.group(0).lower()]), text)

    def back(self, text: str | None) -> str | None:
        """Agent -> world (verbs, ids, queries)."""
        if not text:
            return text
        return self._r.sub(lambda m: self.rev[m.group(0).lower()], text)


def make_skin(name: str | None) -> Skin | None:
    return None if not name or name == "none" else Skin(name)
