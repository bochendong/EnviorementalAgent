"""The town library: categorized / flat shelves, reading costs, notes, and the experiment conditions."""
import asyncio
import random

import pytest

from worldseeds.town import TownLaws, TownSeed, grow_town
from worldseeds.town.agents import TownHeuristicAgent, TownSeedMemory
from worldseeds.town.library import CATEGORIES, FLAT_PAGE, LibraryArchive, category_of_space
from worldseeds.town.seed import town_seeds_for, town_split


def _trained(u=1, n=30):
    laws = TownLaws.from_index(u)
    train, test = town_split(random.Random(u))
    seed = TownSeedMemory()
    for s in town_seeds_for(train, laws, n, random.Random(u + 100)):
        w = grow_town(s)
        TownHeuristicAgent(w, seed).run()
        seed.consolidate_events(w.events)
    return laws, seed, town_seeds_for(test, laws, 12, random.Random(u + 200))


def test_categories_of_spaces():
    assert category_of_space("soil.pumpkin") == "farming"
    assert category_of_space("season.melon") == "farming"
    assert category_of_space("likes.baker") == "gifting"
    assert category_of_space("gift_attr") == "gifting"
    assert category_of_space("midday_place") == "schedule"


def test_shelves_exist_and_reading_costs_an_action():
    lib = LibraryArchive(mode="categorized")
    w = grow_town(TownSeed(blocks=("farming",), surface_seed=3), library=lib)
    assert "library" in w.rooms
    for cat in CATEGORIES:
        assert f"shelf_{cat}" in w.objs
    msg, ok = w.act("read", "shelf_farming")
    assert not ok and "not here" in msg  # must walk to the library first
    w.act("go", "library")
    a = w.actions
    msg, ok = w.act("read", "shelf_farming")
    assert ok and "empty" in msg
    assert w.actions == a + 1 and lib.reads == 1


def test_consolidated_entries_are_correct_and_sorted():
    laws, seed, _ = _trained()
    lib = LibraryArchive()
    lib.update_from_seed(seed, episode=30)
    correct, scored = lib.accuracy(TownSeedMemory.truth(laws))
    assert scored >= 8 and correct == scored
    assert all(e.category == category_of_space(e.claims[0][0]) for e in lib.entries)
    lib.update_from_seed(seed, episode=31)  # rewrites, never duplicates
    assert sum(1 for e in lib.entries if e.source == "consolidated") == scored
    rt = LibraryArchive.from_dict(lib.to_dict())
    assert len(rt.entries) == len(lib.entries) and rt.entries[0].claims == lib.entries[0].claims


def test_flat_pile_pages_through_everything():
    laws, seed, tests = _trained()
    lib = LibraryArchive(mode="flat")
    lib.update_from_seed(seed, 30)
    w = grow_town(tests[0], library=lib)
    assert "shelf_pile" in w.objs and "shelf_farming" not in w.objs
    w.act("go", "library")
    seen = 0
    for _ in range(lib.pages()):
        msg, ok = w.act("read", "shelf_pile")
        assert ok
        seen += msg.count("\n- ")
    assert seen == len(lib.entries) and lib.pages() == -(-len(lib.entries) // FLAT_PAGE)


def test_notes_are_filed_on_the_shelf_written_to():
    lib = LibraryArchive()
    w = grow_town(TownSeed(blocks=("gifting",), surface_seed=5), library=lib)
    w.act("go", "library")
    msg, ok = w.act("write", "shelf_gifting", "Smiths love flowers.")
    assert ok and lib.entries[-1].category == "gifting" and lib.entries[-1].source == "note"
    msg, ok = w.act("read", "shelf_gifting")
    assert "Smiths love flowers." in msg


def test_library_helps_a_memoryless_agent():
    laws, seed, tests = _trained()
    lib = LibraryArchive()
    lib.update_from_seed(seed, 30)
    none = sum(TownHeuristicAgent(grow_town(s), None).run()["success"] for s in tests)
    lib.reads = 0
    with_lib = sum(TownHeuristicAgent(grow_town(s, library=lib), None, random.Random(0)).run()["success"]
                   for s in tests)
    assert lib.reads > 0
    assert with_lib > none


def test_experiment_library_condition(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="town", protocol="compgen", policy="heuristic", conditions=["library", "library_flat"],
                    universes=[1], n_train=6, n_test=3, out_dir=str(tmp_path))
    run_experiment(cfg)
    import json

    rows = [json.loads(line) for line in open(tmp_path / "episodes.jsonl")]
    assert {r["condition"] for r in rows} == {"library", "library_flat"}
    test_rows = [r for r in rows if r["phase"] == "test"]
    assert all("library_reads" in r and r["library_entries"] > 0 for r in test_rows)


def test_scripted_llm_reads_and_writes():
    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.agent import build_agent, EpisodeCtx, run_episode

    lib = LibraryArchive()
    w = grow_town(TownSeed(blocks=("farming",), surface_seed=3), library=lib)
    names = [t.name for t in build_agent(EpisodeCtx(world=w, condition="library"), None, ModelSettings()).tools]
    assert "write_note" in names
    steps = [[testing.function_call("act", {"verb": "go", "target": "library"}, call_id="g")],
             [testing.function_call("act", {"verb": "read", "target": "shelf_farming"}, call_id="r")],
             [testing.function_call("write_note", {"shelf": "shelf_farming", "text": "Pumpkins hate clay."},
                                    call_id="w")],
             [testing.assistant_message("done for now")]]
    model = testing.ScriptedModel(steps)
    metrics, ctx = asyncio.run(run_episode(w, "library", model, ModelSettings(), library=lib, max_nudges=0))
    assert metrics["notes_written"] == 1 and lib.reads == 1
    assert lib.entries[-1].text == "Pumpkins hate clay."
