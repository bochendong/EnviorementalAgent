"""World seeds: compact causal descriptions that a world is grown from.

A ``WorldSeed`` is the *true* developmental code of a world: which causal blocks it
contains, under which universe laws, at what size, plus a surface seed that controls
only appearance/layout. ``grow(seed)`` (see ``world.py``) lazily expands it.

Seed operators implement sections 16-17 of the program seed:
  * ``mutate``     -> curriculum generation (z' = z + delta z)
  * ``crossover``  -> compositional world breeding (z_C = z_A (+) z_B)
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from dataclasses import dataclass, field, replace

from .laws import Laws

# Causal blocks. Door blocks create obstacles on the path; item blocks wrap items.
LOCKABLE = "lockable"
CONTAINER = "container"
POWERED = "powered"
PUSHABLE = "pushable"
FRAGILE = "fragile"
MACHINE = "machine"

ALL_BLOCKS = [LOCKABLE, CONTAINER, POWERED, PUSHABLE, FRAGILE, MACHINE]
DOOR_BLOCKS = [LOCKABLE, POWERED, PUSHABLE, MACHINE]


@dataclass(frozen=True)
class WorldSeed:
    laws: Laws = field(default_factory=Laws)
    blocks: tuple[str, ...] = (LOCKABLE, CONTAINER)
    n_rooms: int = 3  # rooms on the critical path (start ... goal)
    n_side_rooms: int = 1  # dead-end rooms with distractors / prerequisites
    n_distractors: int = 2  # lazily-grown distractor objects per room
    n_goals: int = 1  # number of gems (>1 for persistent-world experiments)
    surface_seed: int = 0

    def __post_init__(self):
        bad = [b for b in self.blocks if b not in ALL_BLOCKS]
        if bad:
            raise ValueError(f"unknown blocks {bad}")
        object.__setattr__(self, "blocks", tuple(sorted(set(self.blocks), key=ALL_BLOCKS.index)))

    # ------------------------------------------------------------ identity / io
    def to_dict(self) -> dict:
        return {
            "laws": self.laws.to_dict(),
            "blocks": list(self.blocks),
            "n_rooms": self.n_rooms,
            "n_side_rooms": self.n_side_rooms,
            "n_distractors": self.n_distractors,
            "n_goals": self.n_goals,
            "surface_seed": self.surface_seed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorldSeed":
        d = dict(d)
        d["laws"] = Laws.from_dict(d["laws"])
        d["blocks"] = tuple(d["blocks"])
        return cls(**d)

    @property
    def id(self) -> str:
        return hashlib.sha1(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:10]

    @property
    def composition(self) -> str:
        return "+".join(self.blocks)

    # ------------------------------------------------------------ operators
    def mutate(self, rng: random.Random, kind: str | None = None) -> "WorldSeed":
        """Structured mutation. ``kind`` in {add_block, drop_block, grow, distract, laws, surface}."""
        kind = kind or rng.choice(["add_block", "drop_block", "grow", "distract", "surface"])
        if kind == "add_block":
            missing = [b for b in ALL_BLOCKS if b not in self.blocks]
            if missing:
                return replace(self, blocks=self.blocks + (rng.choice(missing),))
            kind = "grow"
        if kind == "drop_block" and len(self.blocks) > 1:
            b = rng.choice(self.blocks)
            return replace(self, blocks=tuple(x for x in self.blocks if x != b))
        if kind in ("grow", "drop_block"):
            return replace(self, n_rooms=min(self.n_rooms + 1, 7))
        if kind == "distract":
            return replace(self, n_distractors=self.n_distractors + 1)
        if kind == "laws":
            return replace(self, laws=self.laws.mutate(rng))
        return replace(self, surface_seed=rng.randrange(1 << 30))

    def crossover(self, other: "WorldSeed", rng: random.Random | None = None) -> "WorldSeed":
        """Compose two seeds: union of causal blocks, larger of the two sizes.

        Laws are taken from ``self`` (worlds are bred *within* a universe)."""
        rng = rng or random.Random(self.surface_seed ^ other.surface_seed)
        return WorldSeed(
            laws=self.laws,
            blocks=tuple(set(self.blocks) | set(other.blocks)),
            n_rooms=max(self.n_rooms, other.n_rooms, 2),
            n_side_rooms=max(self.n_side_rooms, other.n_side_rooms),
            n_distractors=max(self.n_distractors, other.n_distractors),
            n_goals=max(self.n_goals, other.n_goals),
            surface_seed=rng.randrange(1 << 30),
        )


# ---------------------------------------------------------------- splits
def compositional_split(
    rng: random.Random, train_sizes=(1, 2), test_sizes=(3, 4), n_test_combos: int = 8
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    """Train on small block combinations, test on unseen larger ones (section 4).

    Every block appears during training, so laws are learnable; every test
    composition is unseen by construction."""
    train = [c for k in train_sizes for c in itertools.combinations(ALL_BLOCKS, k)]
    pool = [c for k in test_sizes for c in itertools.combinations(ALL_BLOCKS, k)]
    rng.shuffle(pool)
    test = pool[:n_test_combos]
    return train, test


def seeds_for(
    combos: list[tuple[str, ...]], laws: Laws, n: int, rng: random.Random, **kw
) -> list[WorldSeed]:
    out = []
    for i in range(n):
        combo = combos[i % len(combos)] if i < len(combos) else rng.choice(combos)
        n_rooms = kw.get("n_rooms") or max(2, min(len([b for b in combo if b in DOOR_BLOCKS]) + 1, 5))
        out.append(
            WorldSeed(
                laws=laws,
                blocks=combo,
                n_rooms=n_rooms,
                n_side_rooms=kw.get("n_side_rooms", 1),
                n_distractors=kw.get("n_distractors", 2),
                n_goals=kw.get("n_goals", 1),
                surface_seed=rng.randrange(1 << 30),
            )
        )
    return out
