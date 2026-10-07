"""Second-hand knowledge with controlled reliability: authored notes and villager testimony."""
import json
import random

from worldseeds.town import TownLaws, TownSeed, grow_town
from worldseeds.town.agents import BoardHeuristicAgent, TownHeuristicAgent, TownOracle, TownSeedMemory
from worldseeds.town.library import LibraryArchive
from worldseeds.town.seed import town_seeds_for, town_split
from worldseeds.town.sources import NOTE_AUTHORS, maybe_corrupt, wrong_value


def _learned(u=1, n=30):
    laws = TownLaws.from_index(u)
    train, test = town_split(random.Random(u))
    seed = TownSeedMemory()
    for s in town_seeds_for(train, laws, n, random.Random(u + 100)):
        w = grow_town(s)
        TownHeuristicAgent(w, seed).run()
        seed.consolidate_events(w.events)
    return laws, seed, test


def test_errors_are_consistent_and_wrong():
    assert wrong_value("soil.melon", "clay", "Ben") != "clay"
    assert wrong_value("soil.melon", "clay", "Ben") == wrong_value("soil.melon", "clay", "Ben")
    assert maybe_corrupt("gift_attr", "color", 0.0, "x") == ("color", False)
    assert maybe_corrupt("gift_attr", "color", 1.0, "x") == ("category", True)


def test_note_error_rate():
    laws, seed, _ = _learned()
    truth = TownSeedMemory.truth(laws)
    for rate in (0.0, 0.5, 1.0):
        lib = LibraryArchive()
        wrong = lib.write_notes(seed, 30, {a: rate for a in NOTE_AUTHORS})
        correct, scored = lib.accuracy(truth)
        assert scored - correct == wrong
        assert {e.author for e in lib.entries} == set(NOTE_AUTHORS)
        if rate == 0.0:
            assert wrong == 0
        if rate == 1.0:
            assert correct == 0
    a = LibraryArchive()
    a.write_notes(seed, 30, {"Ben": 0.5})
    b = LibraryArchive()
    b.write_notes(seed, 31, {"Ben": 0.5})
    assert [e.claims for e in a.entries] == [e.claims for e in b.entries]  # same author, same lies


def test_testimony_liars_and_truth():
    s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming", "gifting", "schedule"), board=4, surface_seed=5)
    truth = TownSeedMemory.truth(s.laws)
    for rate in (0.0, 0.25, 0.5):
        w = grow_town(s, max_actions=1000, testimony=rate)
        assert len(w.liars) == round(rate * 8)
        o = TownOracle(w)
        for v in [x for x in w.objs.values() if x.kind == "villager"]:
            o.meet(v.id)
            msg, ok = w.act("ask", v.id)
            assert ok and v.name in msg
            ev = [e for e in w.events if e.verb == "ask"][-1]
            claims = ev.effects[0]["claims"]
            bad = sum(truth[sp] != val for sp, val in claims)
            assert bad == ev.effects[0]["wrong"]
            assert (bad > 0) == (v.id in w.liars)
    w = grow_town(s, max_actions=1000)
    TownOracle(w).meet("v1")
    assert not w.act("ask", "v1")[1]  # no testimony in this town


def test_calibrated_trust_resists_bad_sources():
    laws, seed, test = _learned()
    te = town_seeds_for(test, laws, 12, random.Random(201), board=4)

    def share(rate, trust):
        tot = 0
        for s in te:
            lib = LibraryArchive()
            lib.write_notes(seed, 30, {a: rate for a in NOTE_AUTHORS})
            m = BoardHeuristicAgent(grow_town(s, max_actions=200, library=lib), None, random.Random(0), trust=trust).run()
            tot += m["board_done"] / m["board_total"]
        return tot / len(te)

    assert share(0.0, "blind") > share(0.5, "blind") + 0.2
    assert share(0.5, "calibrated") >= share(0.5, "blind")


def test_experiment_source_variants(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="board", protocol="compgen", policy="heuristic", conditions=["testimony", "library"],
                    universes=[1], n_train=4, n_test=2, max_actions=200, source_errors=[0.0, 0.5],
                    trusts=["blind"], out_dir=str(tmp_path))
    run_experiment(cfg)
    rows = [json.loads(line) for line in open(tmp_path / "episodes.jsonl")]
    assert {r["variant"] for r in rows} == {"err0-blind", "err0.5-blind"}
    t = [r for r in rows if r["condition"] == "testimony"]
    assert t and all(r["phase"] == "test" and "heard_wrong" in r for r in t)
    assert all(r["heard_wrong"] == 0 for r in t if r["source_error"] == 0)
    lib = [r for r in rows if r["condition"] == "library" and r["phase"] == "test"]
    assert all(r["library_claims_correct"] == r["library_claims"] for r in lib if r["source_error"] == 0)


def test_scripted_llm_asks_villagers():
    import asyncio

    import pytest

    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.agent import EpisodeCtx, build_instructions, run_episode

    s = TownSeed(laws=TownLaws.from_index(1), blocks=("gifting",), board=2, surface_seed=3)
    w = grow_town(s, max_actions=200, testimony=0.5)
    assert "VILLAGERS" in build_instructions(EpisodeCtx(world=w, condition="testimony"), None, None, False)
    v = next(o for o in w.objs.values() if o.kind == "villager" and o.location == w.home_of[o.id])
    steps = [[testing.function_call("act", {"verb": "go", "target": w.home_of[v.id]}, call_id="g")],
             [testing.function_call("act", {"verb": "ask", "target": v.id}, call_id="a")],
             [testing.assistant_message("ok")]]
    metrics, ctx = asyncio.run(run_episode(w, "testimony", testing.ScriptedModel(steps), ModelSettings(),
                                           max_nudges=0))
    assert v.id in w.asked and v.fine["job"] in ctx.trace[1]["out"]
