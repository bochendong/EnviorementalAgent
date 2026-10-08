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
           description: str = "", **buildings) -> dict:
    """Run ``sprints`` sprints of one organisation and record everything. ``solo`` gets the team's budget."""
    rng = random.Random(f"replay/{seed}/{world.index}/{world.n_functions}/{team}")
    plan = [[world.project(rng) for _ in range(projects_per_dev * team)] for _ in range(sprints)]
    solo = mode in ("solo", "solo_unbounded")
    org = Org(world, 1 if solo else team, None if mode == "solo_unbounded" else capacity,
              "solo" if solo else mode, seed=seed, walk=walk, record=True, batch=batch, **buildings)
    per_dev = budget * (team if solo else 1)
    out = {"kind": "codeworld", "title": title or f"{mode}: {team if not solo else 1} apprentice(s)",
           "description": description, "mode": mode, "team": len(org.devs), "capacity": capacity, "walk": walk, "batch": batch,
           **{k: bool(v) for k, v in buildings.items() if k in ("board", "library", "post")},
           "shortcuts": bool(world.map and world.map.shortcuts),
           "budget": per_dev, "world": world.layout(),
           "devs": [{"name": d.name, "owns": sorted(d.owns, key=world.modules.index), "home": d.home,
                     "look": list(LOOKS[i % len(LOOKS)])} for i, d in enumerate(org.devs)],
           "sprints": []}
    for s, projects in enumerate(plan):
        start = len(org.events)
        books = {d.name: list(d.notebook.laws) for d in org.devs}
        m = org.sprint(projects, per_dev)
        n = len(org.devs)
        out["sprints"].append({
            "index": s + 1, "budget": per_dev,
            "projects": [{"id": p.id, "text": p.text(), "in": p.in_type, "out": p.out_type, "examples": p.examples,
                          "target": list(p.target), "dev": org.devs[k % n].name} for k, p in enumerate(projects)],
            "start_notebooks": books, "events": org.events[start:], "metrics": m})
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
    roads = town_world(index, districts=3, shortcuts=True)
    reps.append(record(roads, "owners", 12, 12, sprints=5, projects_per_dev=3, library=True, post=True,
                       title="Three districts with libraries, post offices and forest trails",
                       description="Masters write their machines down at the library; far questions go by letter; "
                                   "trails through the woods join each farm to its mountain and beach."))
    big = town_world(index, districts=3)
    for mode, title, desc in (
            ("solo", "Three districts, one apprentice", "144 machines for one head of 12 laws."),
            ("owners", "Three districts, twelve masters",
             "Each apprentice masters two workshops; asking across districts means a long walk, so one visit "
             "covers every machine of that master the order might need."),
            ("directory", "Three districts and a roster",
             "The roster sends each question to the nearest apprentice who knows.")):
        reps.append(record(big, mode, 12, 12, sprints=5, projects_per_dev=3, title=title, description=desc))
    return reps
