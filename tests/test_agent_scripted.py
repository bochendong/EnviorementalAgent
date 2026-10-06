"""Runs the real Agents-SDK episode loop with a scripted (offline) model."""
import asyncio

import pytest

pytest.importorskip("agents")
testing = pytest.importorskip("agents.testing")

from agents import ModelSettings  # noqa: E402

from worldseeds import WorldSeed, grow  # noqa: E402
from worldseeds.agent import run_episode  # noqa: E402
from worldseeds.memory import SeedMemory  # noqa: E402
from worldseeds.oracle import Oracle  # noqa: E402


def _oracle_calls(seed):
    w = grow(seed)
    w.max_actions = 1000
    o = Oracle(w)
    o.solve()
    calls = []
    for ev in w.events:
        args = {"verb": ev.verb, "target": ev.target}
        if ev.instrument:
            args["instrument"] = ev.instrument
        calls.append(args)
    return calls


def test_scripted_episode_reaches_goal_and_stops():
    seed = WorldSeed(blocks=("lockable", "container", "fragile"), n_rooms=3, surface_seed=11)
    calls = _oracle_calls(seed)
    steps = [[testing.function_call("zoom_in", {"target": "k1"}, call_id="z0")],
             [testing.function_call("predict", {"verb": "unlock", "target": "d1", "instrument": "k1"}, call_id="p0")]]
    steps += [[testing.function_call("act", c, call_id=f"c{i}")] for i, c in enumerate(calls)]
    model = testing.ScriptedModel(steps)
    world = grow(seed)
    metrics, ctx = asyncio.run(run_episode(world, "seed", model, ModelSettings(), seed=SeedMemory(),
                                           history_items=6))
    assert metrics["success"], ctx.trace[-3:]
    assert metrics["status"] == "finished"
    assert metrics["actions"] == len(calls)
    assert metrics["predict_calls"] == 1
    assert model.remaining_steps == 0  # stopped right after the goal, no extra LLM turn


def test_scripted_episode_max_turns():
    seed = WorldSeed(blocks=("lockable",), n_rooms=2, surface_seed=1)
    steps = [[testing.function_call("observe", {}, call_id=f"o{i}")] for i in range(5)]
    model = testing.ScriptedModel(steps)
    metrics, _ = asyncio.run(run_episode(grow(seed), "none", model, ModelSettings(), max_turns=3))
    assert not metrics["success"]
    assert metrics["status"] == "max_turns"


def test_nudge_after_plain_text_answer():
    seed = WorldSeed(blocks=("lockable",), n_rooms=2, surface_seed=1)
    calls = _oracle_calls(seed)
    steps = [[testing.assistant_message("I will now explore.")]]
    steps += [[testing.function_call("act", c, call_id=f"c{i}")] for i, c in enumerate(calls)]
    model = testing.ScriptedModel(steps)
    metrics, _ = asyncio.run(run_episode(grow(seed), "none", model, ModelSettings()))
    assert metrics["success"] and metrics["nudges"] == 1
