"""Replays of CodeWorld sprints for the pixel client (web/codeworld.html).

A replay is JSON produced by the engine itself (so the client always shows what the engine did):

    {"kind": "codeworld", "title", "description", "mode", "team", "capacity", "walk", "budget",
     "world": Universe.layout(),                       districts, workshops, machines (public)
     "devs": [{"name", "owns", "home", "look"}],      apprentices and the workshops they keep
     "sprints": [{"index", "budget",
                  "projects": [{"id", "text", "in", "out", "examples", "target", "dev"}],
                  "start_notebooks": {dev: [function, ...]},
                  "events": [Org events: start, walk, learn, ask, submit, give_up],
                  "metrics": Org.metrics}]}
"""

from __future__ import annotations

import random

from .org import Org
from .world import Universe

LOOKS = [("Rosa", "red"), ("Tomas", "blue"), ("Ivy", "green"), ("Bram", "orange"), ("Lena", "purple"),
         ("Otto", "yellow"), ("Mira", "blue"), ("Finn", "red"), ("Hana", "green"), ("Leo", "purple"),
         ("Clara", "orange"), ("Abe", "yellow")]


def town_world(index: int = 1, districts: int = 1, machines: int = 6, shortcuts: bool = False) -> Universe:
    """The town-scale CodeWorld: 8 workshops per district, ``machines`` machines each."""
    return Universe(index, n_modules=8 * districts, fns_per_module=machines, levels=5,
                    types_per_level=3 if districts == 1 else 4, theme="town", shortcuts=shortcuts)


def record(world: Universe, mode: str, team: int, capacity: int | None, sprints: int = 3, budget: int = 120,
           projects_per_dev: int = 4, walk: bool = True, batch: bool = True, seed: int = 0, title: str = "",
           description: str = "", events=None, goals=None, goal_deadline: int = 4, fund: int | None = None,
           econ=None, **buildings) -> dict:
    """Run ``sprints`` sprints of one organisation and record everything. ``solo`` gets the team's budget.
    ``events`` (an EventRates) makes the town change: a copy of the world meets seeded events each sprint.
    ``goals`` (kinds, see goals.py) gives the town grand goals, worked on before the day's orders."""
    rng = random.Random(f"replay/{seed}/{world.index}/{world.n_functions}/{team}")
    sched = None
    if events is not None and events.any:
        import copy

        from .events import Schedule

        world, sched = copy.deepcopy(world), Schedule(events, seed)
        plan = [None] * sprints
    else:
        plan = [[world.project(rng) for _ in range(projects_per_dev * team)] for _ in range(sprints)]
    gl = None
    if goals:
        from .goals import make_goals

        gl = make_goals(world, goals, seed, deadline=goal_deadline, fund=fund)
    solo = mode in ("solo", "solo_unbounded")
    org = Org(world, 1 if solo else team, None if mode == "solo_unbounded" else capacity,
              "solo" if solo else mode, seed=seed, walk=walk, record=True, batch=batch, econ=econ, **buildings)
    per_dev = budget * (team if solo else 1)
    out = {"kind": "codeworld", "title": title or f"{mode}: {team if not solo else 1} apprentice(s)",
           "description": description, "mode": mode, "team": len(org.devs), "capacity": capacity, "walk": walk, "batch": batch,
           **{k: bool(v) for k, v in buildings.items() if k in ("board", "library", "post")},
           "shortcuts": bool(world.map and world.map.shortcuts),
           "money": org.econ is not None,
           "budget": per_dev, "world": world.layout(),
           "goals": [{**g.to_dict(), "parts": [{**p, "done": None} for p in g.to_dict()["parts"]]} for g in gl] if gl else [],
           "devs": [{"name": d.name, "owns": sorted(d.owns, key=world.modules.index), "home": d.home,
                     "look": list(LOOKS[i % len(LOOKS)]),
                     "generosity": org.generosity.get(d.name)} for i, d in enumerate(org.devs)],
           "sprints": []}
    for s, projects in enumerate(plan):
        happened = []
        if sched is not None:  # this sprint's events, then the orders customers place after them
            happened = sched.next(world, s + 1)
            projects = [world.project(rng) for _ in range(projects_per_dev * team)]
        start = len(org.events)
        books = {d.name: list(d.notebook.laws) for d in org.devs}
        purses = {d.name: d.coins for d in org.devs}
        reps = {d.name: d.rep for d in org.devs}
        treasury = org.treasury
        m = org.sprint(projects, per_dev, happened, goals=gl)
        n = len(org.devs)
        out["sprints"].append({
            "index": s + 1, "budget": per_dev,
            "projects": [{"id": p.id, "text": p.text(), "in": p.in_type, "out": p.out_type, "examples": p.examples,
                          "target": list(p.target), "dev": org.devs[k % n].name} for k, p in enumerate(projects)],
            "start_notebooks": books, "events": org.events[start:], "metrics": m,
            "world_events": happened, "broken": sorted(world.broken), "storm": sorted(world.storm),
            "demand": world.demand, "start_coins": purses, "start_rep": reps, "start_treasury": treasury,
            "goals": [g.to_dict() for g in gl] if gl else []})
    return out


def demo_replays(index: int = 1) -> list[dict]:
    """One town (8 workshops x 6 machines, apprentices who remember 12 laws, 4 of them) under four
    organisations, and a town of three districts with 12 apprentices."""
    town = town_world(index)
    reps = []
    for mode, title, desc in (
            ("solo", "One apprentice with the whole team's time",
             "48 machines, but one head holds only 12 laws: it keeps forgetting and studying again."),
            ("random", "Four apprentices asking whoever they meet",
             "Nobody knows who knows what: most questions go to someone who has no idea."),
            ("owners", "Four apprentices, each the master of two workshops",
             "Questions go to the workshop's master, who knows its machines: the team holds the whole town."),
            ("directory", "Four apprentices and a roster of who knows what",
             "Before asking, they look up who has the machine's rule in mind.")):
        reps.append(record(town, mode, 4, 12, sprints=4, title=title, description=desc))
    reps.append(record(town, "random", 4, 12, sprints=4, board=True, title="Four apprentices and a notice board",
                       description="Nobody is told who knows what, but the board on the plaza lists it: read it once a "
                                   "sprint, then ask the right person."))
    from .events import EventRates

    weather = EventRates(breakdown=.05, drift=.05, festival=.5, storm=.3, rumor=1.5)
    for mode, title, desc in (
            ("owners", "Four masters in a changing town",
             "Machines break down and get re-tuned, storms make walking slow, festivals change what is wanted. "
             "Each master notices what happens to its own machines."),
            ("random", "Four apprentices without masters in a changing town",
             "The same events, but nobody looks after a workshop: old rules go stale until an order fails.")):
        reps.append(record(town, mode, 4, 12, sprints=4, events=weather, title=title, description=desc))
    from .economy import EconConfig

    for mode, title, desc in (
            ("owners", "A town with money: four masters",
             "Customers pay for orders; masters earn a royalty when their machines are used; the treasury takes a "
             "tax and pays bounties for goal parts. Money buys overtime for goal work and wages for help. Goals: "
             "the harvest festival, the judges' prize and a clock tower the treasury must pay for."),
            ("random", "A town with money: four apprentices without masters",
             "The same money, goals and prices, but nobody knows who knows what.")):
        reps.append(record(town, mode, 4, 12, sprints=5, goals=["banquet", "prize", "fund"], goal_deadline=4,
                           econ=EconConfig(upkeep=10), title=title, description=desc))
    reps.append(record(town, "owners", 4, 12, sprints=4, events=EventRates(drift=.05), goals=["encyclopedia", "prize"],
                       goal_deadline=4, title="Four masters write the town encyclopedia",
                       description="Every machine's rule, written correctly at the library, and kept right as machines "
                                   "get re-tuned; and the judges' prize."))
    roads = town_world(index, districts=3, shortcuts=True)
    reps.append(record(roads, "owners", 12, 12, sprints=5, projects_per_dev=3, library=True, post=True,
                       title="Three districts with libraries, post offices and forest trails",
                       description="Masters write their machines down at the library; far questions go by letter; "
                                   "trails through the woods join each farm to its mountain and beach."))
    big = town_world(index, districts=3)
    festival = ["banquet", "prize", "recipe"]
    change = EventRates(breakdown=.03, drift=.03)
    for mode, team, title, desc in (
            ("owners", 12, "Three districts and the festival: twelve masters",
             "Grand goals: the harvest festival (four long recipes), the judges' prize (exact grades: run a recipe "
             "backwards) and old Martha's lost recipe (which raw good, which machines?). Machines break and get "
             "re-tuned now and then."),
            ("random", 12, "Three districts and the festival: twelve apprentices without masters",
             "The same goals and events, but nobody knows who knows what."),
            ("solo", 12, "Three districts and the festival: one apprentice",
             "The same goals and events for one head with the whole team's time.")):
        reps.append(record(big, mode, team, 12, sprints=5, projects_per_dev=3, events=change, goals=festival,
                           goal_deadline=4, title=title, description=desc))
    return reps
