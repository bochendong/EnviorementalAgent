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


def test_town_machines_follow_the_recipe_book():
    from worldseeds.codeworld.recipes import GOODS_BY_LEVEL, RECIPES
    from worldseeds.codeworld.replay import town_world

    u = town_world(2)
    for f in u.functions.values():  # every machine is one of its trade's recipes, one level up
        tool = f.name.split(".", 1)[1]
        assert (tool, f.in_type, f.out_type) in RECIPES[u.kind_of[f.module]]
        assert u.type_level[f.out_type] == u.type_level[f.in_type] + 1
    assert u.types_at[0] == GOODS_BY_LEVEL[0]
    m = u.layout()["districts"][0]["workshops"][0]["machines"][0]
    assert m["look"] and m["title"][0].isupper()


def test_town_buildings_and_shortcuts():
    from worldseeds.codeworld.replay import town_world

    plain, trails = town_world(1, 3), town_world(1, 3, shortcuts=True)
    assert trails.distance("oak_farm", "oak_mine") < plain.distance("oak_farm", "oak_mine")  # a forest trail
    rng = random.Random(4)
    plan = [[plain.project(rng) for _ in range(36)] for _ in range(4)]

    def run(u, mode, **kw):
        org = Org(u, 12, 12, mode, walk=True, batch=True, record=True, **kw)
        ms = [org.sprint(p, 120) for p in plan]
        return org, sum(m["done"] for m in ms)

    org, done = run(plain, "random", board=True)
    assert any(e["kind"] == "board" for e in org.events) and done > run(plain, "random")[1]
    org, done = run(plain, "owners", library=True)
    assert org.lib and any(e["kind"] == "read" for e in org.events) and any(e["kind"] == "deposit" for e in org.events)
    assert all(law.table == plain.functions[fn].law.table for fn, law in org.lib.items())
    assert done > run(plain, "owners")[1]
    org, _ = run(plain, "owners", post=True)
    letters = [e for e in org.events if e["kind"] == "ask" and e.get("by") == "post"]
    assert letters and sum(org.devs[0].spent.values()) >= 0


def test_town_events_are_seeded_and_noticed():
    import copy

    from worldseeds.codeworld.events import EventRates, Schedule
    from worldseeds.codeworld.replay import town_world

    rates = EventRates(breakdown=.1, drift=.1, festival=1, storm=.5, rumor=2)
    base = town_world(1)
    runs = []
    for _ in range(2):  # the same seed: the same events, whoever meets them
        w, s = copy.deepcopy(base), Schedule(rates, seed=7)
        runs.append([s.next(w, k) for k in range(1, 4)])
    assert runs[0] == runs[1] and any(e["kind"] == "drift" for e in runs[0][0])
    w, s = copy.deepcopy(base), Schedule(rates, seed=7)
    ev = s.next(w, 1)
    drifted = next(e["fn"] for e in ev if e["kind"] == "drift")
    assert w.functions[drifted].law.table != base.functions[drifted].law.table  # the copy changed, not the base
    assert {e["good"] for e in ev if e["kind"] == "festival"} == set(w.demand)
    rng = random.Random(1)
    orders = [w.project(rng) for _ in range(12)]
    assert not any(fn in w.broken for p in orders for fn in p.target)  # nobody orders what cannot be made
    org = Org(w, 4, 12, "owners", walk=True, batch=True)
    master = org.owner[w.functions[drifted].module]
    master.notebook.put(drifted, base.functions[drifted].law)  # the old law
    org.sprint(orders, 120, ev)
    assert drifted not in master.notebook or master.notebook.laws[drifted].table == w.functions[drifted].law.table
    broken = [e["fn"] for e in ev if e["kind"] == "breakdown"]
    assert all(fn in org.owner[w.functions[fn].module].broken for fn in broken)  # masters know their machines


def test_grand_goals():
    from worldseeds.codeworld.goals import check, make_goals
    from worldseeds.codeworld.replay import town_world

    u = town_world(1)
    gs = make_goals(u, ["banquet", "prize", "recipe", "encyclopedia"], seed=0, deadline=3)
    banquet, prize, recipe, ency = gs
    assert len(banquet.parts) == 4 and all(len(p["target"]) == 4 for p in banquet.parts)
    assert all(check(u, banquet, p, p["target"]) for p in banquet.parts)  # the remembered recipe fits
    p = prize.parts[0]  # an inverse problem: some recipe and some batch reach the grade
    hits = [(c, x) for c in u.candidates(p["in"], p["out"]) for x in range(101) if u.run(c, x) == p["grade"]]
    assert hits and check(u, prize, p, *hits[0]) and not check(u, prize, p, hits[0][0], (hits[0][1] + 1) % 101)
    r = recipe.parts[0]
    assert check(u, recipe, r, r["target"]) and len(ency.parts) == u.n_functions
    org = Org(u, 4, 12, "owners", walk=True, batch=True, record=True)
    rng = random.Random(0)
    for _ in range(3):
        m = org.sprint([u.project(rng) for _ in range(16)], 120, goals=gs)
    assert m["goals_done"] == 4 and all(g.done_at is not None and g.done_at <= 3 for g in gs)
    assert any(e["kind"] == "goal_part" for e in org.events) and org.lib  # the encyclopedia needs the library
    lone = Org(u, 1, 12, "solo", walk=True, batch=True)
    gs2 = make_goals(u, ["banquet", "prize", "recipe"], seed=0, deadline=3)
    for _ in range(3):
        lone.sprint([u.project(rng) for _ in range(16)], 120, goals=gs2)  # one head, a quarter of the time
    assert sum(g.done_at is not None for g in gs2) < 3


def test_money():
    from worldseeds.codeworld.economy import EconConfig, gini
    from worldseeds.codeworld.goals import make_goals
    from worldseeds.codeworld.replay import town_world

    assert gini([5, 5, 5]) == 0 and gini([0, 0, 9]) > .6
    u = town_world(1)
    rng = random.Random(3)
    orders = [[u.project(rng) for _ in range(16)] for _ in range(4)]

    def run(**kw):
        gs = make_goals(u, ["banquet", "prize", "fund"], seed=0, deadline=4, fund=300)
        org = Org(u, 4, 12, "owners", walk=True, batch=True, record=True, econ=EconConfig(**kw))
        total0 = sum(d.coins for d in org.devs) + org.treasury
        ms = [org.sprint(o, 120, goals=gs) for o in orders]
        return org, gs, ms, total0

    org, gs, ms, total0 = run(upkeep=10)
    pays = [e for e in org.events if e["kind"] == "pay"]
    outside = sum(e["amount"] for e in pays if e["frm"] == "customer")
    assert sum(d.coins for d in org.devs) + org.treasury == total0 + outside  # money is only made by customers
    assert {e["why"] for e in pays} >= {"order", "royalty", "tax", "bounty", "upkeep"}
    assert next(g for g in gs if g.kind == "fund").done_at is not None  # the clock tower got paid for
    assert all(d.coins >= 0 for d in org.devs) and org.treasury >= 0
    paid = run(answer_price=5)[0]
    assert any(e["why"] == "answer" for e in paid.events if e["kind"] == "pay")
