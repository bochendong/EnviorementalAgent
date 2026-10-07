"""Environment registry: everything the experiment runner needs to know about a world family.

    dungeon  rooms, doors, keys, jars, switches, machines, boulders  (worldseeds.world)
    town     SeedVille: farm, villagers, shop, day/night schedule    (worldseeds.town)
    board    SeedVille with the town board: several villager requests to finish within a season
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Any, Callable


@dataclass(frozen=True)
class EnvSpec:
    name: str
    blocks: list[str]
    laws: Callable[[int], Any]  # universe index -> laws
    split: Callable[[random.Random], tuple[list, list]]  # -> (train combos, test combos)
    seeds_for: Callable[..., list]  # (combos, laws, n, rng, **kw) -> seeds
    make_seed: Callable[..., Any]  # (laws, blocks, rng, n_goals=1, n_distractors=2, big=False) -> seed
    normalize: Callable[[Any], Any]  # fix size fields after a mutation
    grow: Callable[..., Any]  # (seed, eager=, max_actions=) -> world
    seed_cls: type  # learned-seed class (LawSeed subclass)
    oracle_steps: Callable[[Any], int]
    heuristic: Callable[..., Any]  # (world, seed_memory | None, rng) -> agent with .run()


def _dungeon() -> EnvSpec:
    from .heuristic import HeuristicAgent
    from .laws import Laws
    from .memory import SeedMemory
    from .oracle import oracle_steps
    from .seed import ALL_BLOCKS, DOOR_BLOCKS, WorldSeed, compositional_split, seeds_for
    from .world import grow

    def n_rooms_for(blocks) -> int:
        return max(2, min(len([b for b in blocks if b in DOOR_BLOCKS]) + 1, 5))

    def make_seed(laws, blocks, rng, n_goals=1, n_distractors=2, big=False):
        return WorldSeed(laws=laws, blocks=tuple(blocks), n_rooms=5 if big else n_rooms_for(blocks),
                         n_side_rooms=1, n_goals=n_goals, n_distractors=n_distractors,
                         surface_seed=rng.randrange(1 << 30))

    return EnvSpec(
        name="dungeon", blocks=ALL_BLOCKS, laws=Laws.from_index, split=compositional_split,
        seeds_for=seeds_for, make_seed=make_seed,
        normalize=lambda s: replace(s, n_rooms=n_rooms_for(s.blocks)),
        grow=grow, seed_cls=SeedMemory, oracle_steps=oracle_steps, heuristic=HeuristicAgent,
    )


def _town() -> EnvSpec:
    from .town.agents import TownHeuristicAgent, TownSeedMemory, town_oracle_steps
    from .town.seed import TOWN_BLOCKS, TownLaws, TownSeed, town_seeds_for, town_split
    from .town.world import grow_town

    def make_seed(laws, blocks, rng, n_goals=1, n_distractors=2, big=False):
        return TownSeed(laws=laws, blocks=tuple(blocks), n_villagers=10 if big else 8, n_goals=n_goals,
                        n_distractors=n_distractors, surface_seed=rng.randrange(1 << 30))

    return EnvSpec(
        name="town", blocks=TOWN_BLOCKS, laws=TownLaws.from_index, split=town_split,
        seeds_for=town_seeds_for, make_seed=make_seed, normalize=lambda s: s,
        grow=grow_town, seed_cls=TownSeedMemory, oracle_steps=town_oracle_steps, heuristic=TownHeuristicAgent,
    )


def _board(n_requests: int = 4, days: int = 7) -> EnvSpec:
    """SeedVille whose goal is the town board (worldseeds.town.world, board mode)."""
    from .town.agents import BoardHeuristicAgent

    town = _town()

    def make_seed(laws, blocks, rng, n_goals=1, n_distractors=2, big=False):
        return replace(town.make_seed(laws, blocks, rng, n_goals, n_distractors, big), board=n_requests, days=days)

    def seeds_for(combos, laws, n, rng, **kw):
        return town.seeds_for(combos, laws, n, rng, **{"board": n_requests, "days": days, **kw})

    return replace(town, name="board", make_seed=make_seed, seeds_for=seeds_for, heuristic=BoardHeuristicAgent)


_FACTORIES = {"dungeon": _dungeon, "town": _town, "board": _board}
ENV_NAMES = list(_FACTORIES)


def get_env(name: str) -> EnvSpec:
    if name not in _FACTORIES:
        raise ValueError(f"unknown env {name!r}; choose from {ENV_NAMES}")
    return _FACTORIES[name]()
