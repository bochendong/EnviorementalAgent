"""The town board: several villager requests, finished within a season."""
import asyncio
import itertools
import random

import pytest

from worldseeds.envs import get_env
from worldseeds.town import TOWN_BLOCKS, TownLaws, TownSeed, grow_town
from worldseeds.town.agents import BoardHeuristicAgent, TownHeuristicAgent, TownOracle, TownSeedMemory
from worldseeds.town.seed import town_seeds_for, town_split


def _board(blocks, ss=3, u=1, n=4, **kw):
    return grow_town(TownSeed(laws=TownLaws.from_index(u), blocks=tuple(blocks), board=n, surface_seed=ss), **kw)


def test_every_board_is_solvable_in_time():
    for u in (0, 2):
        for k in (1, 2, 4):
            for combo in itertools.combinations(TOWN_BLOCKS, k):
                for ss in range(3):
                    w = _board(combo, ss, u, max_actions=10_000)
                    TownOracle(w).solve()
                    assert w.done and w.day <= w.seed.days


def test_board_text_and_kinds():
    w = _board(TOWN_BLOCKS, ss=5)
    assert len(w.requests) == 4 and "board" in w.objs and w.objs["board"].location == "plaza"
    assert {r["kind"] for r in w.requests} == {"harvest", "friends", "fetch", "buy"}
    assert len({r["villager"] for r in w.requests}) == 4
    assert "TOWN BOARD" in w.board_text() and "town board" in w.prompt_spec()["goal"]
    w.act("go", "plaza")
    msg, ok = w.act("read", "board")
    assert ok and "0/4 done" in msg


def test_holder_needs_friendship_with_gifting():
    w = _board(("gifting",), ss=1)
    r = next(r for r in w.requests if r["kind"] == "fetch")
    h = w.objs[r["holder"]]
    w.max_actions = 1000
    o = TownOracle(w)
    o.meet(h.id)
    msg, ok = w.act("talk", h.id)
    assert not ok and "know each other" in msg
    h.state["friendship"] = 1
    msg, ok = w.act("talk", h.id)
    assert ok and r["item"] in w.inventory


def test_rewards_pay_and_count():
    w = _board(("shop",), ss=2, max_actions=1000)
    start = w.coins
    TownOracle(w).solve()
    buys = sum(r["kind"] == "buy" for r in w.requests)
    assert w.coins == start + 4 * len(w.requests) - 4 * buys
    m = w.board_metrics()
    assert m["board_done"] == m["board_total"] == 4


def test_season_ends_the_episode():
    w = _board(("farming",), max_actions=1000)
    for _ in range(w.seed.days):
        w.act("sleep")
    assert w.out_of_time and w.out_of_budget and not w.done
    assert "board closes" in w.act("wait")[0] or w.out_of_budget


def test_seed_helps_on_the_board():
    laws = TownLaws.from_index(1)
    train, test = town_split(random.Random(1))
    seed = TownSeedMemory()
    for s in town_seeds_for(train, laws, 30, random.Random(101)):
        w = grow_town(s)
        TownHeuristicAgent(w, seed).run()
        seed.consolidate_events(w.events)
    te = town_seeds_for(test, laws, 12, random.Random(201), board=4)

    def share(sd):
        tot = 0
        for s in te:
            w = grow_town(s, max_actions=200)
            m = BoardHeuristicAgent(w, sd).run()
            tot += m["board_done"] / m["board_total"]
        return tot / len(te)

    assert share(seed) > share(None) + 0.2


def test_board_env_and_scripted_llm():
    env = get_env("board")
    s = env.seeds_for([("farming", "gifting")], env.laws(1), 1, random.Random(0))[0]
    assert s.board == 4
    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.agent import run_episode

    w = grow_town(s, max_actions=1000)
    TownOracle(w).solve()
    acts = [e for e in w.events if e.verb not in ("night", "see")]
    steps = [[testing.function_call("act", {"verb": e.verb, "target": e.target or "",
                                            **({"instrument": e.instrument} if e.instrument else {})},
                                    call_id=f"c{i}")] for i, e in enumerate(acts)]
    model = testing.ScriptedModel(steps)
    metrics, _ = asyncio.run(run_episode(grow_town(s, max_actions=1000), "seed", model, ModelSettings(),
                                         seed=TownSeedMemory(), max_turns=len(steps) + 5))
    assert metrics["success"] and metrics["board_done"] == 4 and model.remaining_steps == 0
