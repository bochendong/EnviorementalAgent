"""Record SeedVille episodes as replays for the pixel UI (ui/seedville.html).

A replay is JSON: {"title", "seed", "laws", "frames": [{"kind", "action", "message", "state", "who"?}]}
where ``state`` is ``TownWorld.snapshot()`` after the step (in a team: seen through the acting
teammate, ``who``, with every teammate in ``state.team``). Optional ``skin`` = {"name", "words"}: the
agent read the town in another story, and the client shows the same words. Sources:
  * a policy run here (oracle, heuristic explorer with or without a seed, a heuristic team)
  * an LLM agent trace from an experiment, re-simulated from the episode's seed and world switches
  * an LLM team's traces (teammates' tool calls in the order they happened)
"""

from __future__ import annotations

import random

from .agents import BoardHeuristicAgent, TownHeuristicAgent, TownOracle, TownSeedMemory
from .library import LibraryArchive, entry_line
from .seed import TownSeed, town_seeds_for, town_split
from .world import TownWorld, grow_town


class Recorder:
    """Wraps a world's act/zoom so every step becomes a frame."""

    def __init__(self, world: TownWorld):
        self.w = world
        self.frames: list[dict] = [self._frame("start", "", world.observe())]
        self._act, self._zoom_in = world.act, world.zoom_in
        world.act = self.act  # type: ignore[method-assign]
        world.zoom_in = self.zoom_in  # type: ignore[method-assign]

    def _frame(self, kind: str, action: str, message: str, ok: bool | None = None) -> dict:
        f = {"kind": kind, "action": action, "message": message, "state": self.w.snapshot()}
        team = getattr(self.w, "team_ref", None)
        if team is not None and team.cur is not None:
            f["who"] = team.bodies[team.cur].name
        if ok is not None:
            f["ok"] = ok
        return f

    def act(self, verb, target=None, instrument=None):
        msg, ok = self._act(verb, target, instrument)
        args = ", ".join(x for x in (target, instrument) if x)
        self.frames.append(self._frame("act", f"{verb}({args})", msg, ok))
        return msg, ok

    def zoom_in(self, target):
        out = self._zoom_in(target)
        if target in self.w.objs:  # inspecting an object; plain location zooms are not interesting
            self.frames.append(self._frame("inspect", f"zoom_in({target})", out))
        return out

    def detach(self) -> None:
        self.w.act, self.w.zoom_in = self._act, self._zoom_in  # type: ignore[method-assign]


def _meta(world: TownWorld, title: str, description: str, seed_text: str = "") -> dict:
    laws = world.laws.describe(list(world.seed.blocks))
    if getattr(world, "testimony", None) is not None:
        names = sorted(world.objs[v].name for v in world.liars)
        laws.append("Villagers who are always wrong: " + (", ".join(names) if names else "none") + ".")
    return {"title": title, "description": description, "seed": world.seed.to_dict(),
            "laws": laws, "memory": seed_text}


def library_text(lib: LibraryArchive) -> str:
    if lib.mode == "flat":
        return "Unsorted pile:\n" + "\n".join(entry_line(e) for e in lib.entries)
    cats = dict.fromkeys(e.category for e in lib.entries)
    return "\n".join(f"{c.capitalize()} shelf:\n" + "\n".join(entry_line(e) for e in lib.shelf(c)) for c in cats)


def record_policy(seed: TownSeed, policy: str, memory: TownSeedMemory | None = None,
                  max_actions: int = 60, title: str = "", description: str = "",
                  library: LibraryArchive | None = None, testimony: float | None = None,
                  trust: str = "blind", world_opts: dict | None = None) -> dict:
    """policy: oracle | explorer (heuristic, optionally with a learned seed ``memory``, or with an
    empty head and a town ``library`` to read)."""
    if seed.board and max_actions == 60:
        max_actions = 200
    w = grow_town(seed, max_actions=max_actions if policy != "oracle" else 10_000, library=library,
                  testimony=testimony, **dict(world_opts or {}))
    rec = Recorder(w)
    if policy == "oracle":
        TownOracle(w).solve()
    else:
        (BoardHeuristicAgent if w.requests else TownHeuristicAgent)(w, memory, random.Random(0), trust=trust).run()
    rec.detach()
    text = memory.render() if memory else (library_text(library) if library else "")
    out = _meta(w, title or policy, description, text)
    out["frames"] = rec.frames
    out["success"] = w.done
    return out


def _skin_meta(skin: str | None) -> dict:
    from ..skin import SKINS

    return {"skin": {"name": skin, "words": SKINS[skin]}} if skin and SKINS.get(skin) else {}


def replay_trace(seed_dict: dict, trace: list[dict], title: str = "LLM agent", memory_text: str = "",
                 max_actions: int = 60, library: LibraryArchive | None = None,
                 testimony: float | None = None, world_opts: dict | None = None, skin: str | None = None) -> dict:
    """Re-simulate an Agents-SDK tool trace (from traces.jsonl) on the episode's seed, with the world's
    switches (``world_opts``: noise, screens, weather, festival, perception budget, testimony) as in the
    run. For library conditions pass the archive as it was when the episode started. With a ``skin`` the
    agent's words (verbs, ids) are translated back before they reach the world."""
    from ..skin import make_skin

    opts = dict(world_opts or {})
    if testimony is not None:
        opts["testimony"] = testimony
    w = grow_town(TownSeed.from_dict(seed_dict), max_actions=max_actions, library=library, **opts)
    sk = make_skin(skin)
    back = sk.back if sk is not None else (lambda x: x)
    frames = [{"kind": "start", "action": "", "message": sk.out(w.observe()) if sk else w.observe(),
               "state": w.snapshot()}]
    for t in trace:
        tool, a = t["tool"], t.get("args", {})
        ok = None
        if tool == "act":
            _, ok = w.act(back(a.get("verb")), back(a.get("target")), back(a.get("instrument")))
            kind, action = "act", f"{a.get('verb')}({', '.join(x for x in (a.get('target'), a.get('instrument')) if x)})"
        elif tool == "write_note":
            _, ok = w.act("write", a.get("shelf"), a.get("text"))
            kind, action = "act", f"write({a.get('shelf')})"
        elif tool == "zoom_in":
            w.zoom_in(back(a.get("target")))
            kind, action = "inspect", f"zoom_in({a.get('target')})"
        elif tool == "zoom_out":
            w.zoom_out()
            kind, action = "inspect", "zoom_out()"
        else:
            kind, action = "think", f"{tool}({', '.join(str(v) for v in a.values() if v)})"
        frames.append({"kind": kind, "action": action, "message": t.get("out", ""), "state": w.snapshot(),
                       **({"ok": ok} if ok is not None else {})})
    out = _meta(w, title, "Re-simulated from an experiment trace.", memory_text)
    out.update(_skin_meta(skin))
    out["frames"] = frames
    out["success"] = w.done
    return out


def replay_team_trace(seed_dict: dict, agent_traces: list[dict], title: str = "LLM team", max_actions: int = 200,
                      world_opts: dict | None = None, roles: bool = False, messages: bool = False,
                      skin: str | None = None) -> dict:
    """Re-simulate a team's traces (``[{"agent", "trace"}]`` from traces.jsonl): every teammate's tool
    calls in the order they happened (their ``t`` stamps), through that teammate's body."""
    from ..skin import make_skin
    from .team import TEAM_NAMES, Team

    w = grow_town(TownSeed.from_dict(seed_dict), max_actions=max_actions, **dict(world_opts or {}))
    team = Team(w, len(agent_traces), messages=messages, roles=roles)
    idx = {name: i for i, name in enumerate(TEAM_NAMES)}
    sk = make_skin(skin)
    back = sk.back if sk is not None else (lambda x: x)
    calls = sorted(((e.get("t", k), idx[at["agent"]], e) for at in agent_traces
                    for k, e in enumerate(at["trace"])), key=lambda x: x[0])
    last = {}
    for k, (_, i, _e) in enumerate(calls):
        last[i] = k
    team.activate(0)
    frames = [{"kind": "start", "action": "", "message": w.observe(), "state": w.snapshot(), "who": "team"}]
    for k, (_, i, t) in enumerate(calls):
        team.activate(i)
        tool, a = t["tool"], t.get("args", {})
        ok = None
        if tool == "act":
            _, ok = team.act(i, back(a.get("verb")), back(a.get("target")), back(a.get("instrument")))
            kind, action = "act", f"{a.get('verb')}({', '.join(x for x in (a.get('target'), a.get('instrument')) if x)})"
            team._maybe_night()
        elif tool == "tell":
            _, ok = team.tell(i, a.get("teammate"), a.get("message"))
            kind, action = "act", f"tell({a.get('teammate')})"
        elif tool == "zoom_in":
            w.zoom_in(back(a.get("target")))
            kind, action = "inspect", f"zoom_in({a.get('target')})"
        else:
            kind, action = "think", f"{tool}({', '.join(str(v) for v in a.values() if v)})"
        team.activate(i)
        frames.append({"kind": kind, "action": action, "message": t.get("out", ""), "state": w.snapshot(),
                       "who": team.bodies[i].name, **({"ok": ok} if ok is not None else {})})
        if last.get(i) == k:  # this teammate stopped here (as in the run: never waited for at night again)
            team.finish(i)
    out = _meta(w, title, "Re-simulated from a team's traces.", "")
    out.update(_skin_meta(skin))
    out["frames"] = frames
    out["success"] = w.done
    return out


def record_team(seed: TownSeed, n: int = 3, roles: bool = True, festival: bool = True, memories=None,
                title: str = "", description: str = "", messages: bool = True) -> dict:
    """A heuristic team on one town board (festival requests, private-perception roles)."""
    from .team import Team, run_heuristic_team

    w = grow_town(seed, max_actions=200, festival=festival)
    team = Team(w, n, messages=messages, roles=roles)
    rec = Recorder(w)
    run_heuristic_team(team, list(memories or [None] * n), rng_seed=0, messages=messages)
    rec.detach()
    out = _meta(w, title or "heuristic team", description)
    out["frames"] = rec.frames
    out["success"] = w.done
    return out


def demo_replays(universe: int = 2, n_train: int = 30, candidates: int = 40) -> list[dict]:
    """Runs on the same town: explorer without memory, explorer with a learned seed, explorer that
    carries nothing but reads the town library (filled from the same earlier towns), and the oracle.

    The town is chosen where the learned seed makes the clearest difference."""
    from .seed import TownLaws

    laws = TownLaws.from_index(universe)
    train, test = town_split(random.Random(universe))
    memory = TownSeedMemory()
    for s in town_seeds_for(train, laws, n_train, random.Random(universe + 100)):
        w = grow_town(s)
        TownHeuristicAgent(w, memory).run()
        memory.consolidate_events(w.events)
        memory.worlds_seen += 1
    library = LibraryArchive()
    library.update_from_seed(memory, n_train, author="librarian")
    best, best_gap = None, -1e9
    rng = random.Random(7)
    pool = [c for c in test if {"farming", "gifting"} <= set(c)] or test
    for s in town_seeds_for(pool, laws, candidates, rng):
        if s.season == "winter":  # the demo should show the town in leaf
            continue
        a = TownHeuristicAgent(grow_town(s), None).run()
        b = TownHeuristicAgent(grow_town(s), memory).run()
        c = TownHeuristicAgent(grow_town(s, library=LibraryArchive.from_dict(library.to_dict())), None,
                               random.Random(0)).run()
        gap = (b["success"] - a["success"]) * 100 + (a["actions"] - b["actions"])
        if b["success"] and c["success"] and gap > best_gap:
            best, best_gap = s, gap
    seed = best
    return [
        record_policy(seed, "explorer", None, title="Explorer, no memory",
                      description="Tries things until they work. It has never seen another town."),
        record_policy(seed, "explorer", memory, title="Explorer with a learned seed",
                      description=f"Same explorer, carrying laws consolidated from {n_train} earlier towns."),
        record_policy(seed, "explorer", None, title="Explorer reading the library",
                      description=f"Carries no memory, but walks to the library and reads the shelves its task "
                                  f"needs. The shelves were written from {n_train} earlier towns.",
                      library=library),
        record_policy(seed, "oracle", None, title="Oracle",
                      description="Knows the hidden laws. Shows the shortest sensible route."),
    ] + board_replays(laws, test, memory, library, n_train)


def board_replays(laws, test, memory, library, n_train: int, candidates: int = 30) -> list[dict]:
    """The town board (four villager requests in one week), with and without what earlier towns taught."""
    rng = random.Random(11)
    pool = [c for c in test if len(c) >= 3 and "farming" in c] or test
    best, best_gap = None, -1e9
    for s in town_seeds_for(pool, laws, candidates, rng, board=4):
        if s.season == "winter":
            continue
        done = []
        for sd, kw in ((None, {}), (memory, {}), (None, {"testimony": 0.25})):
            w = grow_town(s, max_actions=200, **kw)
            m = BoardHeuristicAgent(w, sd, random.Random(0), trust="calibrated").run()
            done.append(m["board_done"])
        if done[1] < 4 or done[2] < 3:  # the seeded run finishes; asking around gets most of it
            continue
        gap = (done[1] - done[0]) + (done[2] - done[0])
        if gap > best_gap:
            best, best_gap = s, gap
    return [
        record_policy(best, "explorer", None, title="Town board: explorer, no memory",
                      description="Four villagers post requests. One week to finish them, no idea how this "
                                  "universe works."),
        record_policy(best, "explorer", memory, title="Town board: explorer with a learned seed",
                      description=f"The same week, carrying laws consolidated from {n_train} earlier towns."),
        record_policy(best, "explorer", None, title="Town board: asking villagers (a quarter are wrong)",
                      description="No memory, but it asks the villagers it meets what their trade taught them. "
                                  "Two of them are consistently wrong; it trusts a source only as far as what it "
                                  "sees agrees.", testimony=0.25, trust="calibrated"),
        record_policy(best, "explorer", memory, title="Town board: rainy nights (a confounder)",
                      description="The same seeded explorer, but some nights it rains: rain waters every plot and "
                                  "floods one hidden soil, killing what grows there.",
                      world_opts={"confounder": True}),
        record_team(_festival_town(laws, pool, memory), 3, roles=True, festival=True, memories=[memory] * 3,
                    title="Festival: a team of three with private perception",
                    description="Ana tells soils apart, Bo reads people, Cy knows goods. Besides the board: a dish "
                                "cooked from a fresh crop, and a villager who wants two of them to visit at once."),
    ]


def _festival_town(laws, pool, memory, candidates: int = 30):
    """A board town whose festival a three-agent team finishes (the shortest such week)."""
    from .team import Team, run_heuristic_team

    best, best_days = None, 99
    for s in town_seeds_for(pool, laws, candidates, random.Random(13), board=3):
        if s.season == "winter":
            continue
        w = grow_town(s, max_actions=200, festival=True)
        m = run_heuristic_team(Team(w, 3, messages=True, roles=True), [memory] * 3, rng_seed=0, messages=True)
        if m["success"] and m["days_used"] < best_days:
            best, best_days = s, m["days_used"]
    return best or s

