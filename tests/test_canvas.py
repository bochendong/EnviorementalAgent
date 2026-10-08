"""Canvas memory: a fixed-size, multi-resolution context instead of a transcript."""
import asyncio

import pytest

from worldseeds.canvas import Canvas
from worldseeds.town import TownLaws, TownSeed, grow_town
from worldseeds.town.agents import TownOracle


def _walked():
    s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming", "gifting", "schedule"), board=4, surface_seed=5)
    w = grow_town(s, max_actions=500)
    o = TownOracle(w)
    for loc in ["plaza", "shop", "home1", "home2", "bakery", "forest"]:
        o.goto(loc)
    return w


def test_canvas_resolution_and_budget():
    w = _walked()
    big = Canvas(w, chars=4000).render()
    assert "<- you are here" in big and "MAP, not visited yet" in big and "NOTES" in big
    places = [ln for ln in big.splitlines() if ln.startswith("[")]
    assert places[0].startswith("[forest") and len(places) == 7
    assert "plot" in places[-1] and "{" not in places[-1]  # the farm, long ago: counts only
    small = Canvas(w, chars=1300).render()
    assert len(small) <= 1300 and small.count("\n[") < big.count("\n[") + 1


def test_canvas_only_shows_what_was_perceived():
    w = _walked()
    c = Canvas(w, chars=6000)
    soils = {o.fine["soil"] for o in w.objs.values() if o.kind == "plot"}
    assert not any(f"soil: {x}" in c.render() for x in soils)  # never zoomed into a plot
    w.agent_room, w.focus = "farm", ["farm"]
    plot = next(o for o in w.objs.values() if o.kind == "plot")
    w.zoom_in(plot.id)
    assert f"soil: {plot.fine['soil']}" in c.render()


def test_notes_are_rewritten_not_appended():
    c = Canvas(_walked())
    c.rewrite_notes("first plan")
    c.rewrite_notes("second plan")
    assert "second plan" in c.render() and "first plan" not in c.render()
    c.rewrite_notes("x" * 2000)
    assert len(c.notes) == 800


def test_scripted_llm_with_canvas_context():
    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.agent import run_episode

    s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming",), board=2, surface_seed=3)
    w = grow_town(s, max_actions=100)
    steps = [[testing.function_call("rewrite_notes", {"text": "try melon first"}, call_id="n")]]
    steps += [[testing.function_call("act", {"verb": v, "target": t}, call_id=f"a{i}")]
              for i, (v, t) in enumerate([("go", "plaza"), ("go", "farm"), ("wait", "")] * 4)]
    steps.append([testing.assistant_message("stop")])
    model = testing.ScriptedModel(steps)
    metrics, ctx = asyncio.run(run_episode(w, "none", model, ModelSettings(), context="canvas", canvas_chars=2500,
                                           max_nudges=0))
    assert metrics["context"] == "canvas" and ctx.canvas.notes == "try melon first"
    assert ctx.canvas.renders >= 10 and 0 < metrics["canvas_mean_chars"] <= 2500
