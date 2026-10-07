"""Several agents in one town working the same board."""
import asyncio
import json

import pytest

from worldseeds.town import TownLaws, TownSeed, grow_town
from worldseeds.town.agents import TownSeedMemory
from worldseeds.town.team import Team, Teammate, run_heuristic_team


def _board(ss=4, **kw):
    s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming", "gifting", "shop", "schedule"), board=4,
                 surface_seed=ss)
    return grow_town(s, max_actions=200, **kw)


def test_bodies_are_separate_and_town_is_shared():
    w = _board()
    team = Team(w, 2)
    a, b = Teammate(team, 0), Teammate(team, 1)
    a.act("go", "plaza")
    assert a.agent_room == "plaza" and b.agent_room == "farm"
    item = next(o for o in w.objs.values() if o.location == "farm" and o.kind in ("seeds", "tool"))
    assert b.act("take", item.id)[1]
    assert item.id in b.inventory and item.id not in a.inventory
    assert not a.act("give", "v1", item.id)[1]  # not a's to give
    assert a.actions == 2 and b.actions == 1  # invalid actions count too


def test_clock_moves_one_tick_per_round():
    w = _board()
    team = Team(w, 2)
    a, b = Teammate(team, 0), Teammate(team, 1)
    a.act("wait")
    assert w.tick == 0
    b.act("wait")
    assert w.tick == 1


def test_night_waits_for_everyone():
    w = _board()
    team = Team(w, 2)
    a, b = Teammate(team, 0), Teammate(team, 1)
    msg, ok = a.act("sleep")
    assert ok and a.asleep and w.day == 1
    assert "asleep" in a.act("wait")[0]
    b.act("go", "plaza")
    b.act("go", "farm")
    b.act("sleep")
    assert w.day == 2 and not a.asleep and not b.asleep
    assert a.agent_room == b.agent_room == "farm"


def test_messages_are_delivered_once():
    w = _board()
    team = Team(w, 2, messages=True)
    a, b = Teammate(team, 0), Teammate(team, 1)
    assert a.tell("Bo", "I take the farm")[1]
    assert "Message from Ana: I take the farm" in b.observe()
    assert "Message from Ana" not in b.observe()
    assert not a.tell("Zed", "hi")[1]


def test_heuristic_team_is_faster_than_solo():
    laws = TownLaws.from_index(1)
    seed = TownSeedMemory.certain_of(laws)
    solo = team = 0
    for ss in range(8):
        m1 = run_heuristic_team(Team(_board(ss), 1), [seed])
        m3 = run_heuristic_team(Team(_board(ss), 3), [seed] * 3)
        assert m3["board_done"] >= m1["board_done"]
        solo += m1["days_used"]
        team += m3["days_used"]
    assert team < solo


def test_experiment_team_protocol(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="board", protocol="team", policy="heuristic", conditions=["seed"], universes=[1],
                    n_train=4, n_test=2, n_agents=2, max_actions=200, out_dir=str(tmp_path))
    run_experiment(cfg)
    rows = [json.loads(line) for line in open(tmp_path / "episodes.jsonl")]
    test = [r for r in rows if r["phase"] == "test"]
    assert {r["variant"] for r in test} == {"solo", "independent", "library", "messages", "merged"}
    assert all(r["team_size"] == (1 if r["variant"] == "solo" else 2) for r in test)


def test_scripted_llm_team_sleeps_and_talks():
    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.agent import run_episode

    w = _board()
    team = Team(w, 2, messages=True)
    a_steps = [[testing.function_call("tell", {"teammate": "Bo", "message": "I sleep first"}, call_id="t")],
               [testing.function_call("act", {"verb": "sleep", "target": ""}, call_id="s")],
               [testing.assistant_message("done")]]
    b_steps = [[testing.function_call("act", {"verb": "go", "target": "plaza"}, call_id="g")],
               [testing.function_call("act", {"verb": "go", "target": "farm"}, call_id="f")],
               [testing.function_call("act", {"verb": "sleep", "target": ""}, call_id="s")],
               [testing.assistant_message("done")]]

    async def go():
        return await asyncio.gather(
            run_episode(Teammate(team, 0), "seed", testing.ScriptedModel(a_steps), ModelSettings(),
                        seed=TownSeedMemory(), max_nudges=0),
            run_episode(Teammate(team, 1), "seed", testing.ScriptedModel(b_steps), ModelSettings(),
                        seed=TownSeedMemory(), max_nudges=0))

    (ma, ca), (mb, cb) = asyncio.run(asyncio.wait_for(go(), 60))
    assert w.day == 2
    assert "A new day begins" in ca.trace[1]["out"]
    assert any("Message from Ana" in t["out"] for t in cb.trace)
