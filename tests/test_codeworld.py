"""CodeWorld: hidden laws, projects, notebooks of limited capacity, and how developers are organised."""
import json
import random

import pytest

from worldseeds.codeworld import Law, Notebook, Org, P, Universe, fit
from worldseeds.codeworld.knowledge import study_inputs


def test_laws_and_learning_them():
    aff, br = Law("affine", 5, 7), Law("branch", 5, 7, 3, 11, 2)
    assert aff(2) == 17 and br(2) == 17 and br(3) == (11 * 3 + 2) % P and br(0) == 2
    for law in (aff, br, Law("branch", 9, 1, 2, 4, 0), Law("branch", 3, 3, 5, 8, 8)):
        assert fit({x: law(x) for x in study_inputs()}).table == law.table  # the study design pins every law
    # points that never touch the edge case look affine: a law that passes what was seen, wrong elsewhere
    seen = {x: br(x) for x in (1, 2, 4, 5)}
    wrong = fit(seen)
    assert wrong is not None and wrong.kind == "affine" and wrong.table != br.table
    assert fit({1: 3, 2: 5}) is None  # too few points


def test_universe_and_projects():
    u = Universe(1, n_modules=8, fns_per_module=4)
    assert u.n_functions == 32 and len(set(u.functions)) == 32
    assert Universe(1, n_modules=8).signatures_text() == u.signatures_text()  # deterministic
    rng = random.Random(0)
    for _ in range(20):
        p = u.project(rng)
        assert u.type_checks(p.target, p.in_type, p.out_type)
        assert len({u.functions[n].module for n in p.target}) >= 2  # projects cross modules
        cands = u.candidates(p.in_type, p.out_type)
        fitting = [c for c in cands if all(u.run(c, x) == y for x, y in p.examples)]
        assert fitting and all(u.table(c) == u.table(p.target) for c in fitting)  # examples single it out
        assert p.n_candidates == len(cands) and p.text().startswith(f"Project {p.id}")


def test_notebook_capacity_and_specialists():
    nb = Notebook(2)
    for k in range(3):
        nb.put(f"m.f{k}", Law("affine", 2, k))
    assert list(nb.laws) == ["m.f1", "m.f2"] and nb.evictions == 1
    nb.put("m.f0", Law("affine", 2, 0))
    assert nb.relearned == 1
    keep = Notebook(2, keep=lambda n: n.startswith("mine."))
    keep.put("mine.a", Law("affine", 2, 1))
    keep.put("other.b", Law("affine", 2, 2))
    keep.put("other.c", Law("affine", 2, 3))
    assert "mine.a" in keep and "other.b" not in keep  # a specialist forgets foreign laws first


def test_organisations():
    u = Universe(1, n_modules=8, fns_per_module=4)
    rng = random.Random(1)
    projects = [u.project(rng) for _ in range(8)]
    solo = Org(u, 1, None, "solo")
    m = solo.sprint(projects, 10_000)
    assert m["done"] == 8 and m["spent_ask"] == 0 and m["wrong_laws"] == 0
    owners = Org(u, 4, 8, "owners")
    m = owners.sprint(projects, 10_000)
    assert m["done"] == 8 and m["spent_ask"] > 0 and m["spent_answer"] == m["spent_ask"]
    for d in owners.devs:  # owners only ever studied their own modules
        assert all(n.split(".")[0] in d.owns for n in d.notebook.ever)
    pooled = Org(u, 4, 8, "pooled")
    assert pooled.devs[0].notebook is pooled.devs[3].notebook
    poor = Org(u, 1, 4, "solo")
    m = poor.sprint(projects, 30)
    assert m["out_of_budget"] > 0 and m["done"] < 8
    with pytest.raises(ValueError):
        Org(u, 2, 8, "telepathy")


def test_core_experiment_network_beats_equal_compute_solo(tmp_path):
    from worldseeds.codeworld.experiment import CWConfig, run

    run(CWConfig(universes=[1], modules=[8], capacities=[8], team_sizes=[4], sprints=6,
                 variants=["solo", "solo_unbounded", "owners", "random"], out_dir=str(tmp_path)))
    rows = [json.loads(x) for x in open(tmp_path / "codeworld.jsonl")]
    late = {v: sum(r["done"] for r in rows if r["variant"] == v and r["sprint"] > 3) for v in
            ("solo", "solo_unbounded", "owners", "random")}
    # 32 functions, 8 laws per head: one head is too small, four heads with owners hold the world
    assert late["owners"] > late["solo"] and late["owners"] >= late["random"]
    assert late["solo_unbounded"] >= late["owners"]
    assert all(r["budget_total"] == 4 * 120 for r in rows)  # every organisation spends the same compute


def test_law_parser():
    from worldseeds.codeworld.llm_agent import parse_law

    assert parse_law("3*x + 5") == Law("affine", 3, 5) and parse_law("7x+1 (mod 101)") == Law("affine", 7, 1)
    assert parse_law("12*x - 3") == Law("affine", 12, P - 3) and parse_law("x + 4") == Law("affine", 1, 4)
    assert parse_law("7*x + 1 if x % 3 == 0 else 2*x + 9") == Law("branch", 2, 9, 3, 7, 1)
    assert parse_law("nonsense") is None and parse_law("4*x if x % 1 == 0 else x") is None


def test_scripted_llm_developers():
    import asyncio

    pytest.importorskip("agents")
    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.codeworld.llm_agent import llm_sprint

    u = Universe(1, n_modules=8, fns_per_module=4)
    p = u.project(random.Random(3))
    calls = []
    for fn in p.target:  # study each function of the answer, write its law down, check, submit
        calls.append(("study", {"function": fn}))
        calls.append(("remember", {"function": fn, "law": u.functions[fn].law.describe().replace(" (mod 101)", "")}))
    x, y = p.examples[0]
    calls += [("compute", {"program": list(p.target), "x": x}), ("submit", {"program": list(p.target)})]
    model = testing.ScriptedModel([[testing.function_call(t, a, call_id=f"c{k}")] for k, (t, a) in enumerate(calls)])
    org = Org(u, 1, 8, "solo")
    res = asyncio.run(llm_sprint(org, [p], 200, model, ModelSettings(), max_turns=len(calls) + 2))
    m, trace = res["metrics"], res["traces"][0]["trace"]
    assert m["done"] == 1 and m["known_union"] == len(set(p.target)) and m["wrong_laws"] == 0
    assert trace[-2]["out"].startswith(f"{' -> '.join(p.target)} on {x}: {y}") and "Accepted" in trace[-1]["out"]
    assert m["spent_study"] == 8 * len(p.target) and m["spent_submit"] == 1

    # a team with owners: dev1 asks dev0 about a function dev0 has in its notebook
    org = Org(u, 2, 8, "owners")
    fn = p.target[0]
    org.devs[0].notebook.put(fn, u.functions[fn].law)
    model = testing.ScriptedModel([[testing.function_call("ask", {"teammate": "dev0", "function": fn}, call_id="a")],
                                   [testing.function_call("compute", {"program": [fn], "x": 5}, call_id="b")]])
    from worldseeds.codeworld.llm_agent import Session, run_dev

    org.devs[0].budget = org.devs[1].budget = 50
    s1 = Session(org, org.devs[1], [p])
    out = asyncio.run(run_dev(s1, model, ModelSettings(), max_turns=2))
    assert s1.trace[0]["out"].startswith(f"dev0: {fn} is ")
    assert f"on 5: {u.functions[fn].law(5)}" in s1.trace[1]["out"]  # the explained law works for this project
    assert org.devs[0].spent["answer"] == 1 and org.devs[1].spent["ask"] == 1 and out["dev"] == "dev1"


def test_town_districts_walking_and_batched_questions():
    from worldseeds.codeworld.replay import town_world

    town = town_world(1)
    assert town.n_functions == 48 and town.modules[:2] == ["bakery", "smithy"] and town.n_districts == 1
    big = town_world(1, districts=3)
    assert big.n_functions == 144 and big.n_districts == 3 and big.modules[0] == "oak_bakery"
    a, b, c = big.modules[0], big.modules[1], big.modules[8]
    assert big.distance(a, a) == 0 and 1 <= big.distance(a, b) < big.distance(a, c)  # walking, across maps
    path = big.route(a, c)
    assert path[0] == big.where(a) and path[-1] == big.where(c)
    areas = big.map.areas
    assert all(areas[t[0]].walkable(t[1], t[2]) for t in path)
    assert all(p[0] != q[0] or abs(p[1] - q[1]) + abs(p[2] - q[2]) == 1 for p, q in zip(path, path[1:]))
    assert len({p[0] for p in path}) >= 3  # oak's bakery is in oak's town; river's is two maps away
    # every workshop is a room in the map of its kind, with one machine per function along its walls
    for m in big.modules:
        ai, room = big.room[m]
        assert areas[ai].theme == {"bakery": "town", "clinic": "town", "inn": "beach", "shop": "beach",
                                   "farm": "farm", "florist": "farm", "mine": "mountain", "smithy": "mountain"}[big.kind_of[m]]
        assert sum(areas[ai].g[y][x] == "m" for x, y in (t for t, _ in room["machines"])) == 6
    for a in areas:  # maps touch at their exits: the tiles on both sides are neighbours in one world grid
        for e in a.exits:
            (ax, ay), (bx, by) = big.map.offset[a.name], big.map.offset[areas[e["to"]].name]
            assert abs(ax + e["at"][0] - bx - e["arrive"][0]) + abs(ay + e["at"][1] - by - e["arrive"][1]) == 1
    lay = town.layout()
    assert {a["theme"] for a in lay["map"]["areas"]} == {"town", "farm", "beach", "mountain"}
    for w in lay["districts"][0]["workshops"]:
        grid = next(a["grid"] for a in lay["map"]["areas"] if a["name"] == w["area"])
        assert all(grid[mc["tile"][1]][mc["tile"][0]] == "m" and grid[mc["stand"][1]][mc["stand"][0]] == "i"
                   for mc in w["machines"])
    rng = random.Random(2)
    plan = [[big.project(rng) for _ in range(36)] for _ in range(6)]
    done = {}
    for batch in (False, True):
        org = Org(big, 12, 12, "owners", walk=True, batch=batch)
        ms = [org.sprint(p, 120) for p in plan]
        assert all(m["spent_walk"] > 0 for m in ms)
        done[batch] = sum(m["done"] for m in ms)
    assert done[True] > done[False]  # one visit explains every relevant machine of that master
    assert {d.name: sorted(d.owns) for d in org.devs}["dev0"] == ["oak_bakery", "oak_clinic"]  # one map each


def test_replay_is_what_the_engine_did():
    """The web client (web/codeworld.js) replays these fields; keep them in sync with it."""
    from worldseeds.codeworld.replay import record, town_world

    town = town_world(1)
    rep = json.loads(json.dumps(record(town, "owners", 4, 12, sprints=2)))
    assert rep["kind"] == "codeworld" and rep["team"] == 4 and len(rep["sprints"]) == 2
    assert [w["module"] for w in rep["world"]["districts"][0]["workshops"]] == town.modules
    assert all({"name", "owns", "home", "look"} <= set(d) for d in rep["devs"])
    for sp in rep["sprints"]:
        books = {k: list(v) for k, v in sp["start_notebooks"].items()}
        done = 0
        for e in sp["events"]:
            assert {"kind", "dev", "loc", "budget", "project"} <= set(e)
            if e["kind"] == "learn":  # the client rebuilds notebooks from learn events
                b = [f for f in books[e["dev"]] if f != e["fn"]] + [e["fn"]]
                books[e["dev"]] = [f for f in b if f not in e["forgot"]]  # it may forget what it just learned
            if e["kind"] == "walk":  # the shortest way along the roads, which the client draws
                end = town.where(e["to"])
                assert e["to"] in town.modules and e["legs"][-1]["path"][-1] == list(end[1:])
                assert e["legs"][-1]["area"] == town.map.areas[end[0]].name
                assert e["steps"] == len(town.route(e["frm"], e["to"])) - 1
            if e["kind"] == "ask":
                assert e["to"] in books and "answered" in e
            done += e["kind"] == "submit" and e["ok"]
        assert done == sp["metrics"]["done"]
        assert sum(map(len, books.values())) == round(sp["metrics"]["known_per_dev"] * 4)
    org = Org(town, 2, 12, "owners", walk=True)
    org.sprint([town.project(random.Random(5)) for _ in range(6)], 120)
    assert all(d.routes for d in org.devs)  # apprentices remember the ways they walked
    solo = record(town, "solo", 4, 12, sprints=1)
    assert solo["team"] == 1 and solo["budget"] == 4 * 120  # the same compute as the team
