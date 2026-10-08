"""Science realism: noisy experiments, cheap screens, a confounder, publication bias, the drug skin."""
import asyncio
import json

import pytest

from worldseeds.skin import Skin, make_skin
from worldseeds.town import TownLaws, TownSeed, grow_town
from worldseeds.town.agents import TownSeedMemory
from worldseeds.town.seed import SOILS


def _town(**kw):
    s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming",), surface_seed=3)
    return grow_town(s, max_actions=400, **kw)


def _good_plot_and_seeds(w):
    """A plot whose soil suits one of the town's crops, and that crop's seed packet."""
    laws = w.laws
    for s in (o for o in w.objs.values() if o.kind == "seeds"):
        crop = s.fine["crop"]
        for p in (o for o in w.objs.values() if o.kind == "plot"):
            if p.fine["soil"] == laws.soil_for[crop]:
                return p, s, crop
    return None


def _grow_once(w, p, s, crop):
    """Plant crop in p in its season, water it and sleep one night; return the plot's status."""
    w.act("take", s.id)
    w.act("take", next(o.id for o in w.objs.values() if o.kind == "tool"))
    w.act("plant", p.id, s.id)
    w.act("water", p.id)
    w.act("sleep", "bed")
    return p.state["status"]


def test_noise_flips_some_outcomes_and_is_reproducible():
    def outcomes(noise):
        out = []
        for surf in range(16):
            s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming",), surface_seed=surf)
            w = grow_town(s, max_actions=400, noise=noise)
            found = _good_plot_and_seeds(w)
            if found is not None:
                out.append(_grow_once(w, *found))
        return out

    clean, noisy = outcomes(0.0), outcomes(0.5)
    assert outcomes(0.5) == noisy  # the same town under the same noise gives the same results
    flipped = sum(a != b for a, b in zip(clean, noisy))
    assert 0 < flipped < len(clean)


def test_screen_takes_no_time_and_is_sometimes_wrong():
    w = _town(screen_error=0.3)
    assert "screen <plot> with <seeds>" in w.verbs_text()
    seeds = [o for o in w.objs.values() if o.kind == "seeds"]
    plots = [o for o in w.objs.values() if o.kind == "plot"]
    for s in seeds:
        w.act("take", s.id)
    tick, said, truth = w.tick, [], []
    for _ in range(5):
        for p in plots:
            for s in seeds:
                msg, ok = w.act("screen", p.id, s.id)
                assert ok
                crop = s.fine["crop"]
                said.append("do well" in msg)
                truth.append(p.fine["soil"] == w.laws.soil_for[crop] and w.laws.season_for[crop] == w.season)
    assert w.tick == tick and w.screens == len(said)
    wrong = sum(a != b for a, b in zip(said, truth)) / len(said)
    assert 0.1 < wrong < 0.5
    plain = _town()
    plain.act("take", seeds[0].id)
    assert "no test kit" in plain.act("screen", plots[0].id, seeds[0].id)[0]


def test_confounder_rain_waters_and_floods():
    w = _town(confounder=True)
    days = [w.weather]
    for _ in range(12):
        w.act("sleep", "bed")
        days.append(w.weather)
    assert "rainy" in days and "sunny" in days
    assert w.flood_soil in SOILS
    assert _town().weather == "fair"
    # a rainy night: an unwatered plot in the flood soil withers, other plots get watered by the rain
    w = _town(confounder=True)
    while w.weather != "rainy":
        w.act("sleep", "bed")
    for p in (o for o in w.objs.values() if o.kind == "plot"):
        crop = next(c for c, soil in w.laws.soil_for.items() if soil == p.fine["soil"]) \
            if p.fine["soil"] in w.laws.soil_for.values() else None
        if crop is None:
            continue
        p.state.update(crop=crop, status="planted", stage=0, watered=False)
    w.act("sleep", "bed")
    for p in (o for o in w.objs.values() if o.kind == "plot" and o.state.get("crop")):
        # nothing is too dry after rain; whatever stands in the flooded soil dies
        assert p.state["status"] != "planted"
        assert (p.state["status"] == "withered") == (p.fine["soil"] == w.flood_soil), (w.flood_soil, p.state)


def test_deconfounding_learner_ignores_rainy_nights():
    w = _town(confounder=True)
    while w.weather != "rainy":
        w.act("sleep", "bed")
    for p in (o for o in w.objs.values() if o.kind == "plot"):
        crop = next(iter(w.laws.soil_for))
        p.state.update(crop=crop, status="planted", stage=0, watered=False)
    w.act("sleep", "bed")
    naive, careful = TownSeedMemory(), TownSeedMemory()
    careful.deconfound = True
    assert naive.consolidate_events(w.events) > careful.consolidate_events(w.events)


def test_publication_bias_library_only_hears_successes(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    rows = {}
    for bias in (False, True):
        out = tmp_path / f"b{bias}"
        cfg = ExpConfig(env="board", protocol="compgen", policy="heuristic", conditions=["library"], universes=[1],
                        n_train=8, n_test=1, max_actions=150, noise=0.25, publication_bias=bias, out_dir=str(out))
        run_experiment(cfg)
        rows[bias] = [json.loads(x) for x in (out / "episodes.jsonl").read_text().splitlines()]
    wrong = {b: rows[b][-1]["library_claims"] - rows[b][-1]["library_claims_correct"] for b in rows}
    # positives only: lucky (noise) successes are never contradicted by the failures that were not published
    assert wrong[True] > wrong[False]


# ------------------------------------------------------------------ the drug-discovery skin
def test_skin_is_one_to_one_and_round_trips():
    k = Skin("drug")
    assert make_skin("none") is None and make_skin(None) is None
    for src in ("farm", "home1", "shelf_farming", "plant", "water", "harvest", "screen", "trophy1", "bed", "mine"):
        assert k.back(k.out(src)) == src
    w = _town(screen_error=0.1, confounder=True)
    text = w.view_world() + w.observe() + w.verbs_text() + w.prompt_spec()["intro"]
    skinned = k.out(text)
    for word in ("turnip", "melon", "pumpkin", "berry", "soil", "plot", "farm", "villager", "harvest"):
        assert word not in skinned.lower(), word
    assert "AX-" in skinned and "well" in skinned and "lab" in skinned


def test_scripted_llm_in_the_drug_skin():
    pytest.importorskip("agents")
    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.agent import build_instructions, run_episode

    w = _town()
    seeds = next(o for o in w.objs.values() if o.kind == "seeds")
    plot = next(o for o in w.objs.values() if o.kind == "plot")
    steps = [[testing.function_call("act", {"verb": "take", "target": seeds.id}, call_id="a")],
             [testing.function_call("act", {"verb": "dose", "target": plot.id, "instrument": seeds.id}, call_id="b")],
             [testing.function_call("act", {"verb": "go", "target": "atrium"}, call_id="c")],
             [testing.function_call("act", {"verb": "go", "target": "lab"}, call_id="d")]]
    model = testing.ScriptedModel(steps)
    metrics, ctx = asyncio.run(run_episode(w, "none", model, ModelSettings(), max_turns=4, skin="drug"))
    assert metrics["skin"] == "drug"
    assert plot.state["status"] == "planted" and w.agent_room == "farm"
    assert all("turnip" not in t["out"] and "plot" not in t["out"] for t in ctx.trace)
    instr = build_instructions(ctx, None, None, False)
    assert "PharmaVille" in instr and "SeedVille" not in instr


def test_screen_policy_and_weight_options(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    rows = {}
    for pol, w in (("off", None), ("use", 0.0), ("ignore", 0.3)):
        out = tmp_path / f"{pol}{w}"
        run_experiment(ExpConfig(env="board", protocol="compgen", policy="heuristic", conditions=["seed"],
                                 universes=[1], n_train=3, n_test=1, max_actions=150, screen_error=0.25,
                                 screen_policy=pol, screen_weight=w, out_dir=str(out)))
        rows[pol] = [json.loads(x) for x in open(out / "episodes.jsonl")]
        seed = json.load(open(next((out / "seeds").glob("*.json"))))
        if w is not None:  # a default weight (0.3) is not written out
            assert seed.get("tuning", {}).get("w_screen", 0.3) == w
    assert all(r["screens"] == 0 and r["screen_policy"] == "off" for r in rows["off"])
    assert any(r["screens"] > 0 for r in rows["use"]) and all("plantings" in r for r in rows["use"])
