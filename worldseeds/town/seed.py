"""SeedVille universe laws and world seeds."""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from dataclasses import asdict, dataclass, field, replace

CROPS = ["turnip", "melon", "pumpkin", "berry"]
SOILS = ["loam", "clay", "sand", "peat"]
SEASONS = ["spring", "summer", "fall", "winter"]
JOBS = ["baker", "smith", "florist", "miner", "fisher", "doctor", "librarian", "innkeeper"]
# every job has a workplace in town (location id, display name)
WORKPLACE = {"baker": ("bakery", "the bakery"), "smith": ("smithy", "the smithy"),
             "florist": ("florist", "the flower shop"), "miner": ("mine", "the mine entrance"),
             "fisher": ("pier", "the pier"), "doctor": ("clinic", "the clinic"),
             "librarian": ("library", "the library"), "innkeeper": ("inn", "the inn")}
CATEGORIES = ["food", "metal", "flower", "gem"]
GIFT_ATTRS = ["color", "category"]
MIDDAY_PLACES = ["plaza", "shop", "home", "work"]
COLORS = ["red", "blue", "green", "yellow", "purple", "orange"]
ITEM_NAMES = {
    "food": ["bread", "pie", "cheese"],
    "metal": ["ingot", "bell", "horseshoe"],
    "flower": ["rose", "tulip", "daisy"],
    "gem": ["ruby", "opal", "quartz"],
}

FARMING = "farming"
GIFTING = "gifting"
SHOP = "shop"
SCHEDULE = "schedule"
TOWN_BLOCKS = [FARMING, GIFTING, SHOP, SCHEDULE]


@dataclass(frozen=True)
class TownLaws:
    """Hidden causal parameters of a SeedVille universe."""

    crop_soil: tuple[tuple[str, str], ...] = field(
        default=(("turnip", "loam"), ("melon", "sand"), ("pumpkin", "clay"), ("berry", "peat")))
    crop_season: tuple[tuple[str, str], ...] = field(
        default=(("turnip", "spring"), ("melon", "summer"), ("pumpkin", "fall"), ("berry", "winter")))
    gift_attr: str = "category"  # villagers like gifts matching their shirt COLOR, or their job's CATEGORY
    job_likes: tuple[tuple[str, str], ...] = field(
        default=(("baker", "food"), ("smith", "metal"), ("florist", "flower"), ("miner", "gem"),
                 ("fisher", "food"), ("doctor", "flower"), ("librarian", "gem"), ("innkeeper", "metal")))
    midday_place: str = "plaza"  # where villagers spend middays (with the schedule block)

    @property
    def soil_for(self) -> dict[str, str]:
        return dict(self.crop_soil)

    @property
    def season_for(self) -> dict[str, str]:
        return dict(self.crop_season)

    @property
    def likes(self) -> dict[str, str]:
        return dict(self.job_likes)

    @classmethod
    def sample(cls, rng: random.Random) -> "TownLaws":
        soils, seasons = SOILS[:], SEASONS[:]
        rng.shuffle(soils)
        rng.shuffle(seasons)
        cats = CATEGORIES * 2  # every category is liked by exactly two jobs
        rng.shuffle(cats)
        return cls(
            crop_soil=tuple(zip(CROPS, soils)),
            crop_season=tuple(zip(CROPS, seasons)),
            gift_attr=rng.choice(GIFT_ATTRS),
            job_likes=tuple(zip(JOBS, cats)),
            midday_place=rng.choice(MIDDAY_PLACES),
        )

    @classmethod
    def from_index(cls, idx: int) -> "TownLaws":
        """Universe 0 is the 'common-sense' one (bakers like food, ...); others are shuffled."""
        if idx == 0:
            return cls()
        return cls.sample(random.Random(20_000 + idx))

    def mutate(self, rng: random.Random, n: int = 1) -> "TownLaws":
        d = asdict(self)
        for k in rng.sample(["crop_soil", "crop_season", "gift_attr", "job_likes", "midday_place"], n):
            if k == "gift_attr":
                d[k] = [a for a in GIFT_ATTRS if a != self.gift_attr][0]
            elif k == "midday_place":
                d[k] = rng.choice([p for p in MIDDAY_PLACES if p != self.midday_place])
            elif k == "job_likes":
                pairs = self.job_likes
                vals = [v for _, v in pairs]
                d[k] = tuple(zip([c for c, _ in pairs], vals[2:] + vals[:2]))
            else:
                pairs = getattr(self, k)
                vals = [v for _, v in pairs]
                d[k] = tuple(zip([c for c, _ in pairs], vals[1:] + vals[:1]))
        for k in ("crop_soil", "crop_season", "job_likes"):
            d[k] = tuple(tuple(x) for x in d[k])
        return TownLaws(**d)

    def to_dict(self) -> dict:
        return {"crop_soil": self.soil_for, "crop_season": self.season_for, "gift_attr": self.gift_attr,
                "job_likes": self.likes, "midday_place": self.midday_place}

    @classmethod
    def from_dict(cls, d: dict) -> "TownLaws":
        return cls(crop_soil=tuple(d["crop_soil"].items()), crop_season=tuple(d["crop_season"].items()),
                   gift_attr=d["gift_attr"], job_likes=tuple(d["job_likes"].items()),
                   midday_place=d["midday_place"])

    def describe(self, blocks=None) -> list[str]:
        lines = {
            FARMING: [
                "Each crop only survives in one soil: " + ", ".join(f"{c}->{s}" for c, s in self.crop_soil) + ".",
                "Each crop only grows in one season: " + ", ".join(f"{c}->{s}" for c, s in self.crop_season) + ".",
            ],
            GIFTING: [
                ("Villagers love gifts whose COLOR matches their shirt." if self.gift_attr == "color" else
                 "Villagers love gifts of the CATEGORY their job prefers: "
                 + ", ".join(f"{j}->{c}" for j, c in self.job_likes) + "."),
            ],
            SCHEDULE: [("At midday villagers go to their WORKPLACE" if self.midday_place == "work" else
                        f"At midday villagers go to the {self.midday_place.upper()}")
                       + "; mornings and evenings they are home."],
        }
        blocks = blocks or list(lines)
        return [x for b in blocks for x in lines.get(b, [])]


@dataclass(frozen=True)
class TownSeed:
    laws: TownLaws = field(default_factory=TownLaws)
    blocks: tuple[str, ...] = (FARMING,)
    n_villagers: int = 8  # 2..12; each villager has a home and a workplace
    n_distractors: int = 2
    n_goals: int = 1
    surface_seed: int = 0
    # town board mode: > 0 means the episode goal is a board of this many villager requests
    # (harvest / friendship / fetch / buy), to finish within ``days`` days, instead of one trophy
    board: int = 0
    days: int = 7

    def __post_init__(self):
        bad = [b for b in self.blocks if b not in TOWN_BLOCKS]
        if bad or not self.blocks:
            raise ValueError(f"bad town blocks {self.blocks}")
        object.__setattr__(self, "blocks", tuple(sorted(set(self.blocks), key=TOWN_BLOCKS.index)))

    @property
    def n_rooms(self) -> int:  # locations, for logging parity with the dungeon
        jobs = min(len(JOBS), self.n_villagers)
        return 4 + self.n_villagers + jobs

    @property
    def season(self) -> str:
        return random.Random(self.surface_seed ^ 0x5EA5).choice(SEASONS)

    def to_dict(self) -> dict:
        return {"env": "town", "laws": self.laws.to_dict(), "blocks": list(self.blocks),
                "n_villagers": self.n_villagers, "n_distractors": self.n_distractors,
                "n_goals": self.n_goals, "surface_seed": self.surface_seed,
                **({"board": self.board, "days": self.days} if self.board else {})}

    @classmethod
    def from_dict(cls, d: dict) -> "TownSeed":
        d = {k: v for k, v in d.items() if k != "env"}
        d["laws"] = TownLaws.from_dict(d["laws"])
        d["blocks"] = tuple(d["blocks"])
        return cls(**d)

    @property
    def id(self) -> str:
        return hashlib.sha1(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:10]

    @property
    def composition(self) -> str:
        return "+".join(self.blocks)

    def mutate(self, rng: random.Random, kind: str | None = None) -> "TownSeed":
        kind = kind or rng.choice(["add_block", "drop_block", "grow", "distract", "surface"])
        if kind == "add_block":
            missing = [b for b in TOWN_BLOCKS if b not in self.blocks]
            if missing:
                return replace(self, blocks=self.blocks + (rng.choice(missing),))
            kind = "grow"
        if kind == "drop_block" and len(self.blocks) > 1:
            b = rng.choice(self.blocks)
            return replace(self, blocks=tuple(x for x in self.blocks if x != b))
        if kind in ("grow", "drop_block"):
            return replace(self, n_villagers=min(self.n_villagers + 2, 12))
        if kind == "distract":
            return replace(self, n_distractors=self.n_distractors + 1)
        if kind == "laws":
            return replace(self, laws=self.laws.mutate(rng))
        return replace(self, surface_seed=rng.randrange(1 << 30))

    def crossover(self, other: "TownSeed", rng: random.Random | None = None) -> "TownSeed":
        rng = rng or random.Random(self.surface_seed ^ other.surface_seed)
        return TownSeed(laws=self.laws, blocks=tuple(set(self.blocks) | set(other.blocks)),
                        n_villagers=max(self.n_villagers, other.n_villagers),
                        n_distractors=max(self.n_distractors, other.n_distractors),
                        n_goals=max(self.n_goals, other.n_goals), surface_seed=rng.randrange(1 << 30),
                        board=max(self.board, other.board), days=max(self.days, other.days))


def town_split(rng: random.Random, train_sizes=(1, 2), test_sizes=(3, 4), n_test_combos: int = 5):
    train = [c for k in train_sizes for c in itertools.combinations(TOWN_BLOCKS, k)]
    pool = [c for k in test_sizes for c in itertools.combinations(TOWN_BLOCKS, k)]
    rng.shuffle(pool)
    return train, pool[:n_test_combos]


def town_seeds_for(combos, laws: TownLaws, n: int, rng: random.Random, **kw) -> list[TownSeed]:
    out = []
    for i in range(n):
        combo = combos[i % len(combos)] if i < len(combos) else rng.choice(combos)
        out.append(TownSeed(laws=laws, blocks=combo, n_villagers=kw.get("n_villagers", 8),
                            n_distractors=kw.get("n_distractors", 2), n_goals=kw.get("n_goals", 1),
                            surface_seed=rng.randrange(1 << 30), board=kw.get("board", 0), days=kw.get("days", 7)))
    return out
