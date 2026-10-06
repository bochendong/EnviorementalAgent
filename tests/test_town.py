import asyncio
import itertools
import random

import pytest

from worldseeds.envs import get_env
from worldseeds.town import TOWN_BLOCKS, TownLaws, TownSeed, grow_town
from worldseeds.town.agents import TownHeuristicAgent, TownOracle, TownSeedMemory, town_oracle_steps
from worldseeds.town.seed import CROPS, town_seeds_for, town_split


def test_every_town_composition_is_solvable():
    rng = random.Random(0)
    for u in range(4):
        laws = TownLaws.from_index(u)
        for k in range(1, len(TOWN_BLOCKS) + 1):
            for combo in itertools.combinations(TOWN_BLOCKS, k):
                for _ in range(3):
                    s = TownSeed(laws=laws, blocks=combo, n_villagers=rng.randint(2, 4),
                                 n_goals=rng.randint(1, 3), surface_seed=rng.randrange(1 << 30))
                    w = grow_town(s)
                    while True:
                        assert town_oracle_steps(w) > 0
                        w.max_actions = 10_000
                        TownOracle(w).solve()
                        if not w.next_goal():
                            break


def test_town_growth_deterministic_and_lazy():
    s = TownSeed(blocks=("farming", "gifting"), n_distractors=4, surface_seed=5)
    a, b = grow_town(s), grow_town(s)
    assert a.observe() == b.observe()
    assert a.nodes_grown < grow_town(s, eager=True).nodes_grown


def _plant_and_wait(laws, soil_ok: bool, season_ok: bool):
    s = TownSeed(laws=laws, blocks=("farming",), surface_seed=1)
    w = grow_town(s)
    w.max_actions = 1000
    crops = [c for c in CROPS if (laws.season_for[c] == w.season) == season_ok]
    crop = crops[0]
    plot = next(o for o in w.objs.values() if o.kind == "plot" and
                (o.fine["soil"] == laws.soil_for[crop]) == soil_ok)
    seeds = next(o for o in w.objs.values() if o.kind == "seeds" and o.fine["crop"] == crop)
    can = next(o for o in w.objs.values() if o.name == "watering can")
    w.act("take", can.id)
    w.act("take", seeds.id)
    w.act("plant", plot.id, seeds.id)
    for _ in range(2):
        w.act("water", plot.id)
        w.act("sleep")
    return plot.state["status"]


def test_crop_laws():
    laws = TownLaws.from_index(3)
    assert _plant_and_wait(laws, True, True) == "ripe"
    assert _plant_and_wait(laws, False, True) == "withered"
    assert _plant_and_wait(laws, True, False) == "dormant"


def test_schedule_moves_villagers_at_midday():
    laws = TownLaws(midday_place="plaza")
    w = grow_town(TownSeed(laws=laws, blocks=("schedule",), surface_seed=2))
    v = w.objs["v1"]
    assert v.location == w.home_of["v1"]
    for _ in range(4):
        w.act("wait")
    assert w.phase == "midday" and v.location == "plaza"
    for _ in range(4):
        w.act("wait")
    assert v.location == w.home_of["v1"]


@pytest.mark.parametrize("u", [1, 5])  # u1: gifts by category, u5: gifts by colour
def test_town_seed_recovers_laws(u):
    laws = TownLaws.from_index(u)
    train, _ = town_split(random.Random(u))
    seed = TownSeedMemory()
    for s in town_seeds_for(train, laws, 40, random.Random(u + 100)):
        w = grow_town(s)
        TownHeuristicAgent(w, seed).run()
        seed.consolidate_events(w.events)
    rec = seed.recovery(laws)
    assert all(v in (True, None) for v in rec.values())
    assert rec["gift_attr"] is True
    assert sum(v is True for v in rec.values()) >= 8


def test_env_registry():
    for name in ("dungeon", "town"):
        env = get_env(name)
        laws = env.laws(1)
        train, test = env.split(random.Random(0))
        s = env.seeds_for(test, laws, 1, random.Random(0))[0]
        w = env.grow(s, eager=False, max_actions=60)
        assert env.oracle_steps(w) > 0
        assert "GOAL" not in w.prompt_spec()["goal"]


def test_scripted_town_episode():
    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.agent import run_episode

    seed = TownSeed(blocks=("farming", "gifting", "schedule"), surface_seed=4)
    w = grow_town(seed)
    w.max_actions = 1000
    TownOracle(w).solve()
    acts = [e for e in w.events if e.verb not in ("night", "see")]
    steps = [[testing.function_call("act", {"verb": e.verb, "target": e.target or "",
                                            **({"instrument": e.instrument} if e.instrument else {})},
                                    call_id=f"c{i}")] for i, e in enumerate(acts)]
    model = testing.ScriptedModel(steps)
    metrics, _ = asyncio.run(run_episode(grow_town(seed), "seed", model, ModelSettings(), seed=TownSeedMemory()))
    assert metrics["success"] and model.remaining_steps == 0
