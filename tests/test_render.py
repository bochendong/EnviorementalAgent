"""Pictures for vision-language agents: views by zoom level, and the canvas as images."""
import asyncio
import base64
import io

import pytest
from PIL import Image

from worldseeds.canvas import Canvas
from worldseeds.render import canvas_content, render_view, text_pages
from worldseeds.town import TownLaws, TownSeed, grow_town


def _town(n_crops=4):
    s = TownSeed(laws=TownLaws.from_index(1, n_crops=n_crops), blocks=("farming", "gifting"), board=2, surface_seed=4)
    return grow_town(s, max_actions=200)


def test_resolution_grows_with_zoom():
    w = _town()
    plot = next(o.id for o in w.objs.values() if o.kind == "plot")
    w.focus = []
    a = render_view(w)
    w.focus = ["farm"]
    b = render_view(w)
    w.zoom_in(plot)
    c = render_view(w)
    assert a.size[0] < b.size[0] and c.size[1] >= 200
    w2 = _town(n_crops=12)  # crops without sprites still render
    w2.focus = ["farm"]
    assert render_view(w2).size[0] > 0


def test_canvas_pages_shrink_older_memories():
    w = _town()
    text = Canvas(w).render() + "\n[home1 (x)] a\n[home2 (x)] b\n[home3 (x)] c\n[home4 (x)] d\n[home5 (x)] e"
    pages = text_pages(text)
    assert pages and all(p.size[0] == 760 for p in pages)
    parts = canvas_content(w, Canvas(w).render())
    imgs = [p for p in parts if p["type"] == "input_image"]
    assert len(imgs) >= 2 and imgs[0]["image_url"].startswith("data:image/png;base64,")
    Image.open(io.BytesIO(base64.b64decode(imgs[0]["image_url"].split(",", 1)[1]))).verify()


def test_image_context_reaches_the_model():
    testing = pytest.importorskip("agents.testing")
    from types import SimpleNamespace as NS

    from agents import ModelSettings

    from worldseeds.agent import EpisodeCtx, _canvas_input, run_episode

    w = _town()
    ctx = EpisodeCtx(world=w, condition="none")
    ctx.canvas = Canvas(w)
    data = NS(model_data=NS(input=[{"role": "user", "content": "Begin"}], instructions="x"), context=ctx)
    out = _canvas_input(6, image=True)(data).input
    assert any(p["type"] == "input_image" for p in out[1]["content"])
    steps = [[testing.function_call("act", {"verb": "wait", "target": ""}, call_id="w")],
             [testing.assistant_message("stop")]]
    metrics, _ = asyncio.run(run_episode(_town(), "none", testing.ScriptedModel(steps), ModelSettings(),
                                         context="image", max_nudges=0))
    assert metrics["context"] == "image" and metrics["actions"] == 1
