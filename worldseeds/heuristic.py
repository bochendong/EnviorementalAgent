"""A non-LLM exploring agent.

Purposes: (1) CPU-only smoke tests of the full Seed -> Grow -> Zoom -> Act ->
Consolidate loop, (2) a cheap baseline that isolates the value of the learned seed
from LLM reasoning ability. With a seed it zooms only where the seed's ``predict``
says it is uncertain, and skips actions the seed predicts will fail.
"""

from __future__ import annotations

import random
from collections import deque

from .laws import Laws
from .memory import SeedMemory
from .world import TAKEABLE, World


def seed_from_laws(laws: Laws, strength: float = 50.0) -> SeedMemory:
    """A SeedMemory that is certain of the true laws (oracle condition for the heuristic)."""
    return SeedMemory.certain_of(laws, strength)


class HeuristicAgent:
    def __init__(self, world: World, seed: SeedMemory | None = None, rng: random.Random | None = None):
        self.w = world
        self.seed = seed
        self.rng = rng or random.Random(0)
        self.tried: set[tuple] = set()

    # ---------------------------------------------------------------- helpers
    def _do(self, verb, target=None, instrument=None) -> bool:
        self.tried.add((verb, target, instrument))
        before = self._state_sig()
        _, ok = self.w.act(verb, target, instrument)
        if self.seed is not None and not ok and verb == "open" and target in self.w.objs:
            self._zoom(target)  # inspect after a surprising failure
        if ok and self._state_sig() != before:
            # world changed: previously failing door/open attempts may now work
            self.tried = {t for t in self.tried if t[0] not in ("open", "go")}
        return ok

    def _state_sig(self):
        return tuple(sorted((o.id, tuple(sorted(o.state.items()))) for o in self.w.objs.values()))

    def _zoom(self, oid: str) -> None:
        """Inspect an object (and a machine's faulty component) from the agent's room."""
        w = self.w
        w.focus = [w.agent_room]
        w.zoom_in(oid)
        o = w.objs[oid]
        if o.kind == "machine":
            for c in o.components or []:
                if c.part:
                    w.zoom_in(c.id)
                    w.zoom_out()
        w.zoom_out()

    def _predict_ok(self, verb, target, instr=None) -> bool | None:
        """True/False from the seed; None if unknown.

        A seed-carrying agent "inspects before it intervenes": it zooms into the objects
        involved (free) when the seed is uncertain, so that (a) a known law can be
        applied and (b) the outcome becomes evidence the consolidator can learn from."""
        if self.seed is None:
            return None
        for oid in (target, instr):
            if oid and oid not in self.w.seen_fine and (self.w.accessible(oid) or oid in self.w.inventory):
                p = self.seed.predict(self.w, verb, target, instr)
                if not p.startswith("PREDICT"):
                    self._zoom(oid)
        p = self.seed.predict(self.w, verb, target, instr)
        if p.startswith("PREDICT SUCCESS"):
            return True
        if p.startswith("PREDICT FAIL"):
            return False
        return None

    def _here(self):
        w = self.w
        out = []
        for o in w.room_objects(w.agent_room):
            out.append(o)
            if o.kind in ("chest", "crate") and o.state.get("open"):
                out += w.contents(o.id)
        return out

    def _held(self, kind):
        return [i for i in self.w.inventory if self.w.objs[i].kind == kind]

    # ---------------------------------------------------------------- policy
    def candidates(self) -> list[tuple]:
        w = self.w
        cands: list[tuple] = []
        here = self._here()
        goal = w.goal
        for o in here:
            if o.id == goal and w.accessible(o.id):
                return [("take", o.id, None)]
        for o in here:
            if o.kind in TAKEABLE and o.kind != "junk" and o.location != "inv" and w.accessible(o.id):
                cands.append(("take", o.id, None))
            if o.kind in ("chest", "crate") and not o.state.get("open"):
                if o.state.get("locked"):
                    cands += self._unlock_options(o)
                cands.append(("open", o.id, None))
            if o.kind == "jar" and not o.state.get("broken"):
                if self._predict_ok("smash", o.id) is not False:
                    cands.append(("smash", o.id, None))
            if o.kind == "switch":
                cands.append(("press", o.id, None))
            if o.kind == "boulder" and not o.state.get("moved"):
                if self._predict_ok("push", o.id) is not False:
                    for t in self._held("tool") or [None]:
                        cands.append(("push", o.id, t))
            if o.kind == "machine" and not o.state.get("running"):
                for t in self._held("tool"):
                    if self._predict_ok("repair", o.id, t) is not False:
                        cands.append(("repair", o.id, t))
            if o.kind == "door" and not o.state.get("open"):
                if o.state.get("locked"):
                    cands += self._unlock_options(o)
                cands.append(("open", o.id, None))
        return [c for c in cands if c not in self.tried]

    def _unlock_options(self, o) -> list[tuple]:
        opts = []
        for k in self._held("key"):
            if self._predict_ok("unlock", o.id, k) is not False:
                opts.append(("unlock", o.id, k))
        return opts

    def _frontier_room(self) -> str | None:
        """Nearest room (through open doors) that is unexplored or has untried actions."""
        w = self.w
        start = w.agent_room
        seen = {start}
        q = deque([(start, [])])
        while q:
            r, path = q.popleft()
            for n, d in w.neighbors(r):
                if n in seen or not d.state.get("open"):
                    continue
                seen.add(n)
                p = path + [n]
                if not w.rooms[n].visited or self._room_has_work(n):
                    return p[0]
                q.append((n, p))
        return None

    def _room_has_work(self, rid: str) -> bool:
        cur = self.w.agent_room
        self.w.agent_room = rid  # peek (no side effects besides lazy growth of a visited room)
        try:
            return bool(self.candidates())
        finally:
            self.w.agent_room = cur

    def step(self) -> bool:
        w = self.w
        cands = self.candidates()
        if cands:
            order = {"take": 0, "smash": 1, "open": 2, "unlock": 3, "repair": 4, "push": 5, "press": 6}
            cands.sort(key=lambda c: order.get(c[0], 9))
            self._do(*cands[0])
            return True
        nxt = self._frontier_room()
        if nxt is not None:
            self._do("go", nxt)
            return True
        # nothing new to try: re-allow presses (toggle back) and wander
        opts = [n for n, d in w.neighbors(w.agent_room) if d.state.get("open")]
        self.tried = {t for t in self.tried if t[0] not in ("press",)}
        if opts:
            self._do("go", self.rng.choice(opts))
            return True
        return False

    def run(self) -> dict:
        w = self.w
        stalls = 0
        while not w.done and not w.out_of_budget and stalls < 3:
            stalls = 0 if self.step() else stalls + 1
        return {
            "success": w.done,
            "status": "finished",
            "error": None,
            "actions": w.actions,
            "invalid_actions": w.invalid_actions,
            "zoom_ops": w.zoom_ops,
            "nodes_grown": w.nodes_grown,
            "tool_calls": w.actions + w.zoom_ops,
            "predict_calls": 0,
            "recall_calls": 0,
            "llm_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "wall_s": 0.0,
        }
