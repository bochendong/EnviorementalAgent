"""The CodeWorld world and its town: projects, the recipe book, maps, events, goals, money (no agents)."""

import copy
import random

from worldseeds.codeworld import Universe
from worldseeds.codeworld.world import town_world


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


def test_town_machines_follow_the_recipe_book():
    from worldseeds.codeworld.recipes import GOODS_BY_LEVEL, RECIPES

    u = town_world(2)
    for f in u.functions.values():  # every machine is one of its trade's recipes, one level up
        tool = f.name.split(".", 1)[1]
        assert (tool, f.in_type, f.out_type) in RECIPES[u.kind_of[f.module]]
        assert u.type_level[f.out_type] == u.type_level[f.in_type] + 1
    assert u.types_at[0] == GOODS_BY_LEVEL[0]
    m = u.layout()["districts"][0]["workshops"][0]["machines"][0]
    assert m["look"] and m["title"][0].isupper()


def test_town_maps_routes_and_shortcuts():
    plain, trails = town_world(1, 3), town_world(1, 3, shortcuts=True)
    assert trails.distance("oak_farm", "oak_mine") < plain.distance("oak_farm", "oak_mine")  # a forest trail
    path = plain.route("oak_bakery", "library:1")
    assert path[0] == plain.where("oak_bakery") and path[-1] == plain.where("library:1")
    assert plain.map.steps(path) > 0 and plain.distance("oak_bakery", "oak_bakery") == 0
    legs = plain.map.legs(path)
    assert legs and all(leg["path"] for leg in legs)


def test_town_events_are_seeded():
    from worldseeds.codeworld.events import EventRates, Schedule

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


def test_grand_goals():
    from worldseeds.codeworld.goals import check, make_goals

    u = town_world(1)
    banquet, prize, recipe, ency = make_goals(u, ["banquet", "prize", "recipe", "encyclopedia"], seed=0, deadline=3)
    assert len(banquet.parts) == 4 and all(len(p["target"]) == 4 for p in banquet.parts)
    assert all(check(u, banquet, p, p["target"]) for p in banquet.parts)  # the remembered recipe fits
    p = prize.parts[0]  # an inverse problem: some recipe and some batch reach the grade
    hits = [(c, x) for c in u.candidates(p["in"], p["out"]) for x in range(101) if u.run(c, x) == p["grade"]]
    assert hits and check(u, prize, p, *hits[0]) and not check(u, prize, p, hits[0][0], (hits[0][1] + 1) % 101)
    r = recipe.parts[0]
    assert check(u, recipe, r, r["target"]) and len(ency.parts) == u.n_functions


def test_money_rules():
    from worldseeds.codeworld.economy import EconConfig, gini

    assert gini([5, 5, 5]) == 0 and gini([0, 0, 9]) > .6
    e = EconConfig()
    assert e.price(3) == e.base_price + 3 * e.machine_price and e.price(3, demand=2) == 2 * e.price(3)
    g = e.generosity(["a", "b"])
    assert g == EconConfig().generosity(["a", "b"]) and all(0 <= v <= 1 for v in g.values())
