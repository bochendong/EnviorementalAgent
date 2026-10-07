"""Record SeedVille episodes as replays for the pixel UI (ui/seedville.html).

A replay is JSON: {"title", "seed", "laws", "frames": [{"kind", "action", "message", "state"}]}
where ``state`` is ``TownWorld.snapshot()`` after the step. Sources:
  * a policy run here (oracle, heuristic explorer with or without a seed)
  * an LLM agent trace from an experiment (re-simulated from the episode's seed)
"""

from __future__ import annotations

import random

from .agents import TownHeuristicAgent, TownOracle, TownSeedMemory
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
    return {"title": title, "description": description, "seed": world.seed.to_dict(),
            "laws": world.laws.describe(list(world.seed.blocks)), "memory": seed_text}


def record_policy(seed: TownSeed, policy: str, memory: TownSeedMemory | None = None,
                  max_actions: int = 60, title: str = "", description: str = "") -> dict:
    """policy: oracle | explorer (heuristic, optionally with a learned seed ``memory``)."""
    w = grow_town(seed, max_actions=max_actions if policy != "oracle" else 10_000)
    rec = Recorder(w)
    if policy == "oracle":
        TownOracle(w).solve()
    else:
        TownHeuristicAgent(w, memory, random.Random(0)).run()
    rec.detach()
    out = _meta(w, title or policy, description, memory.render() if memory else "")
    out["frames"] = rec.frames
    out["success"] = w.done
    return out


def replay_trace(seed_dict: dict, trace: list[dict], title: str = "LLM agent", memory_text: str = "",
                 max_actions: int = 60) -> dict:
    """Re-simulate an Agents-SDK tool trace (from traces.jsonl) on the episode's seed."""
    w = grow_town(TownSeed.from_dict(seed_dict), max_actions=max_actions)
    frames = [{"kind": "start", "action": "", "message": w.observe(), "state": w.snapshot()}]
    for t in trace:
        tool, a = t["tool"], t.get("args", {})
        ok = None
        if tool == "act":
            _, ok = w.act(a.get("verb"), a.get("target"), a.get("instrument"))
            kind, action = "act", f"{a.get('verb')}({', '.join(x for x in (a.get('target'), a.get('instrument')) if x)})"
        elif tool == "zoom_in":
            w.zoom_in(a.get("target"))
            kind, action = "inspect", f"zoom_in({a.get('target')})"
        elif tool == "zoom_out":
            w.zoom_out()
            kind, action = "inspect", "zoom_out()"
        else:
            kind, action = "think", f"{tool}({', '.join(str(v) for v in a.values() if v)})"
        frames.append({"kind": kind, "action": action, "message": t.get("out", ""), "state": w.snapshot(),
                       **({"ok": ok} if ok is not None else {})})
    out = _meta(w, title, "Re-simulated from an experiment trace.", memory_text)
    out["frames"] = frames
    out["success"] = w.done
    return out


def demo_replays(universe: int = 2, n_train: int = 30, candidates: int = 40) -> list[dict]:
    """Three runs on the same town: oracle, explorer without memory, explorer with a learned seed.

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
    best, best_gap = None, -1e9
    rng = random.Random(7)
    pool = [c for c in test if {"farming", "gifting"} <= set(c)] or test
    for s in town_seeds_for(pool, laws, candidates, rng):
        a = TownHeuristicAgent(grow_town(s), None).run()
        b = TownHeuristicAgent(grow_town(s), memory).run()
        gap = (b["success"] - a["success"]) * 100 + (a["actions"] - b["actions"])
        if b["success"] and gap > best_gap:
            best, best_gap = s, gap
    seed = best
    return [
        record_policy(seed, "explorer", None, title="Explorer, no memory",
                      description="Tries things until they work. It has never seen another town."),
        record_policy(seed, "explorer", memory, title="Explorer with a learned seed",
                      description=f"Same explorer, carrying laws consolidated from {n_train} earlier towns."),
        record_policy(seed, "oracle", None, title="Oracle",
                      description="Knows the hidden laws. Shows the shortest sensible route."),
    ]
