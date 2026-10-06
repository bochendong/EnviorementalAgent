"""Privileged oracle solver: uses the true skeleton and laws to reach the goal.

Used to (1) verify every generated world is solvable, (2) give the optimal-ish step
count for normalising agent efficiency, (3) produce demonstration trajectories.
"""

from __future__ import annotations

from .world import World


class OracleError(RuntimeError):
    pass


class Oracle:
    def __init__(self, world: World, max_depth: int = 40):
        self.w = world
        self.max_depth = max_depth
        self.log: list[str] = []

    def _do(self, verb, target=None, instrument=None):
        msg, ok = self.w.act(verb, target, instrument)
        self.log.append(f"{verb}({target}{', ' + instrument if instrument else ''}) -> {ok}")
        if not ok and not msg.endswith("already open.") and "already" not in msg:
            raise OracleError(f"{verb} {target} {instrument}: {msg}")
        return msg

    def solve(self) -> int:
        start = self.w.actions
        goal = self.w.goal
        self.obtain(goal, 0)
        if not self.w.done:
            raise OracleError("goal not reached")
        return self.w.actions - start

    # ---------------------------------------------------------------- primitives
    def goto(self, room: str, depth: int) -> None:
        if depth > self.max_depth:
            raise OracleError("recursion too deep")
        for nxt, door in self.w.shortest_path(self.w.agent_room, room):
            if not door.state.get("open"):
                self.clear(door, depth + 1)
                self._do("open", door.id)
            self._do("go", nxt)

    def clear(self, door, depth: int) -> None:
        w = self.w
        here = w.agent_room
        b = door.state.get("blocked_by")
        if b and not w.objs[b].state.get("moved"):
            tool = next(o for o in w.objs.values() if o.kind == "tool" and o.name == w.laws.push_tool)
            self.obtain(tool.id, depth + 1)
            self.goto(w.room_of(b), depth + 1)
            self._do("push", b)
        if door.state.get("locked"):
            key = self._matching_key(door.lock)
            self.obtain(key, depth + 1)
            self.goto(here, depth + 1)
            self._do("unlock", door.id, key)
        if door.state.get("needs_power") and not door.state.get("powered"):
            sw = next(r[2] for r in w.requirements if r[0] == "press" and r[1] == door.id)
            self.goto(w.room_of(sw), depth + 1)
            self._do("press", sw)
        m = door.state.get("needs_machine")
        if m and not w.objs[m].state.get("running"):
            right = w.laws.tool_for[w.objs[m].fine["fault"]]
            tool = next(o for o in w.objs.values() if o.kind == "tool" and o.name == right)
            self.obtain(tool.id, depth + 1)
            self.goto(w.room_of(m), depth + 1)
            self._do("repair", m, tool.id)
        self.goto(here, depth + 1)

    def _matching_key(self, lock: dict) -> str:
        for o in self.w.objs.values():
            if o.kind == "key" and o.critical and self.w.would_unlock(o, lock):
                return o.id
        raise OracleError("no matching key")

    def obtain(self, oid: str, depth: int) -> None:
        w = self.w
        if oid in w.inventory:
            return
        o = w.objs[oid]
        holder = w.objs.get(o.location or "")
        if holder is not None:
            if holder.kind == "jar" and not holder.state.get("broken"):
                self.goto(w.room_of(holder.id), depth + 1)
                self._do("smash", holder.id)
            elif holder.kind in ("chest", "crate") and not holder.state.get("open"):
                if holder.state.get("locked"):
                    key = self._matching_key(holder.lock)
                    self.obtain(key, depth + 1)
                self.goto(w.room_of(holder.id), depth + 1)
                if holder.state.get("locked"):
                    self._do("unlock", holder.id, key)
                self._do("open", holder.id)
        self.goto(w.room_of(oid), depth + 1)
        self._do("take", oid)


def oracle_steps(world: World) -> int:
    """Number of actions the oracle needs on a fresh clone of ``world``."""
    w = world.clone()
    w.max_actions = 10_000
    return Oracle(w).solve()
