"""A lazily-grown, zoomable, persistent symbolic world.

Hierarchy (section 5, "object at level L = environment at level L+1"):

    level 0  world      rooms + doors (the map)
    level 1  room       objects in the room (coarse: name, colour, open/closed)
    level 2  object     fine attributes (shape, material, glyph, lock, components)
    level 3  component  detail of a machine part (e.g. "a blown fuse")

Laziness (section 11): only the causal *skeleton* (the objects the task depends on)
is built when the world is grown. Room distractors are instantiated the first time a
room is seen, and object components the first time an object is zoomed into, both
deterministically from (surface_seed, path). ``nodes_grown`` measures that cost; the
``eager=True`` (flat) mode grows everything up front as a baseline.

Persistence (section 2): every state change (open doors, broken jars, moved boulders,
dropped items) stays in the world, so the world itself is a causal memory of the
agent's past interventions.
"""

from __future__ import annotations

import copy
import hashlib
import random
from collections import deque
from dataclasses import dataclass, field

from .laws import (
    COLORS,
    FRAGILE_CANDIDATES,
    GLYPHS,
    PART_FAULTS,
    PARTS,
    PUSH_TOOLS,
    REPAIR_TOOLS,
    SHAPES,
)
from .seed import CONTAINER, FRAGILE, LOCKABLE, MACHINE, POWERED, PUSHABLE, WorldSeed

ROOM_NAMES = [
    "Hall", "Library", "Vault", "Workshop", "Cellar", "Gallery", "Armory",
    "Study", "Greenhouse", "Observatory", "Kitchen", "Chapel", "Attic", "Forge",
]
KEY_MATERIALS = ["brass", "iron", "wood", "stone"]
DECOR = ["vase", "painting", "rug", "lamp", "statue", "book", "candle", "clock"]
JUNK = ["pebble", "coin", "feather", "button"]
TAKEABLE = {"key", "tool", "gem", "junk"}


def _h(*parts) -> int:
    return int(hashlib.sha1("/".join(map(str, parts)).encode()).hexdigest()[:12], 16)


@dataclass
class Component:
    id: str
    name: str
    status: str  # "ok" | "faulty"
    detail: str
    part: str | None = None


@dataclass
class Obj:
    id: str
    kind: str  # door key chest crate jar switch machine boulder tool gem junk decor
    name: str
    color: str
    fine: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    location: str | None = None  # room id | "inv" | container obj id | None (doors)
    rooms: tuple[str, ...] = ()  # doors only
    lock: dict | None = None  # {"color","shape","material"}
    components: list[Component] | None = None
    critical: bool = False

    def label(self) -> str:
        return f"{self.id} {self.color} {self.name}" if self.color else f"{self.id} {self.name}"


@dataclass
class Room:
    id: str
    name: str
    visited: bool = False
    grown: bool = False


@dataclass
class Event:
    step: int
    verb: str
    target: str | None
    instrument: str | None
    success: bool
    valid: bool
    message: str
    target_attrs: dict = field(default_factory=dict)
    instr_attrs: dict = field(default_factory=dict)
    inventory: list[str] = field(default_factory=list)  # kinds/names held
    effects: list[dict] = field(default_factory=list)  # e.g. doors whose power changed

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    def line(self) -> str:
        args = ", ".join(x for x in (self.target, self.instrument) if x)
        attrs = ""
        if self.target_attrs:
            attrs += " target{" + ", ".join(f"{k}={v}" for k, v in self.target_attrs.items() if k not in ("id",)) + "}"
        if self.instr_attrs:
            attrs += " with{" + ", ".join(f"{k}={v}" for k, v in self.instr_attrs.items() if k not in ("id",)) + "}"
        msg = self.message.split("\n")[0]
        return f"{self.verb}({args}) -> {'OK' if self.success else 'FAIL'}: {msg}{attrs}"


class World:
    """One growable, zoomable, persistent world instance."""

    def __init__(self, seed: WorldSeed, eager: bool = False, max_actions: int = 60):
        self.seed = seed
        self.laws = seed.laws
        self.eager = eager
        self.max_actions = max_actions
        self.rooms: dict[str, Room] = {}
        self.objs: dict[str, Obj] = {}
        self.inventory: list[str] = []
        self.agent_room: str = ""
        self.focus: list[str] = []  # zoom stack; [] = world level
        self.seen_fine: set[str] = set()  # object ids whose fine attributes the agent has seen
        self.seen_parts: set[str] = set()  # machine ids whose faulty part the agent has seen
        self.events: list[Event] = []
        self.gems: list[str] = []
        self.goal_index = 0
        self.actions = 0
        self.invalid_actions = 0
        self.zoom_ops = 0
        self.nodes_grown = 0
        self.requirements: list[tuple] = []  # ground-truth causal skeleton (for oracle/analysis)
        self._counter: dict[str, int] = {}
        self._rng = random.Random(seed.surface_seed)
        self._build_skeleton()
        self._enter(self.start_room)
        if eager:
            for r in self.rooms:
                self._grow_room(r)
            for o in list(self.objs.values()):
                self._grow_components(o)

    # ================================================================ building
    def _new_id(self, prefix: str) -> str:
        n = self._counter.get(prefix, 0) + 1
        self._counter[prefix] = n
        return f"{prefix}{n}"

    def _add(self, obj: Obj) -> Obj:
        self.objs[obj.id] = obj
        self.nodes_grown += 1
        return obj

    def _build_skeleton(self) -> None:
        rng, s = self._rng, self.seed
        names = ROOM_NAMES[:]
        rng.shuffle(names)
        path = [f"r{i}" for i in range(s.n_rooms)]
        side = [f"s{i}" for i in range(s.n_side_rooms)]
        for i, rid in enumerate(path + side):
            self.rooms[rid] = Room(rid, names[i % len(names)])
            self.nodes_grown += 1
        self.start_room = path[0]
        self.path = path

        # doors along the path
        path_doors = []
        for i in range(len(path) - 1):
            d = self._door(path[i], path[i + 1])
            path_doors.append(d)
        # side rooms hang off early path rooms through plain doors
        side_parent: dict[str, str] = {}
        for sr in side:
            parent = path[rng.randrange(max(1, len(path) - 1))]
            side_parent[sr] = parent
            self._door(parent, sr)

        def reachable_before(path_idx: int) -> list[str]:
            """Rooms reachable without passing door path_idx (i.e. r0..r_idx + their side rooms)."""
            rs = path[: path_idx + 1]
            return rs + [sr for sr, p in side_parent.items() if p in rs]

        # assign door blocks to doors
        door_blocks = [b for b in s.blocks if b in (LOCKABLE, POWERED, PUSHABLE, MACHINE)]
        if door_blocks and not path_doors:
            raise ValueError("door blocks need n_rooms >= 2")
        order = list(range(len(path_doors)))
        rng.shuffle(order)
        assignments: dict[int, list[str]] = {i: [] for i in order}
        for j, b in enumerate(door_blocks):
            assignments[order[j % len(order)]].append(b)

        used_power: dict[str, set] = {"glyph": set(), "color": set()}
        # Placement of prerequisite items is recorded so FRAGILE can wrap one of them.
        items_placed: list[tuple[Obj, list[str]]] = []

        def place(obj: Obj, allowed: list[str]) -> Obj:
            obj.location = rng.choice(allowed)
            self._add(obj)
            items_placed.append((obj, allowed))
            return obj

        for i, d in enumerate(path_doors):
            allowed = reachable_before(i)
            for b in assignments.get(i, []):
                if b == LOCKABLE:
                    d.lock = self._random_lock()
                    d.state["locked"] = True
                    good, bad = self._keys_for(d.lock)
                    place(good, allowed)
                    place(bad, allowed)
                    self.requirements.append(("unlock", d.id, good.id))
                elif b == POWERED:
                    glyph = rng.choice([g for g in GLYPHS if g not in used_power["glyph"]] or GLYPHS)
                    color = rng.choice([c for c in COLORS if c not in used_power["color"]] or COLORS)
                    used_power["glyph"].add(glyph)
                    used_power["color"].add(color)
                    d.color, d.fine["glyph"] = color, glyph
                    d.state["needs_power"], d.state["powered"] = True, False
                    good, bad = self._switches_for(d, used_power)
                    place(good, allowed)
                    place(bad, allowed)
                    self.requirements.append(("press", d.id, good.id))
                elif b == PUSHABLE:
                    boulder = self._add(Obj(self._new_id("b"), "boulder", "boulder", "grey",
                                            fine={"material": "stone", "blocks": d.id},
                                            location=path[i], critical=True))
                    d.state["blocked_by"] = boulder.id
                    tool = Obj(self._new_id("t"), "tool", self.laws.push_tool, rng.choice(COLORS), critical=True)
                    decoy = Obj(self._new_id("t"), "tool",
                                [t for t in PUSH_TOOLS if t != self.laws.push_tool][0], rng.choice(COLORS),
                                critical=True)
                    place(tool, allowed)
                    place(decoy, allowed)
                    self.requirements.append(("push", boulder.id, tool.id))
                elif b == MACHINE:
                    part = rng.choice(PARTS)
                    m = self._add(Obj(self._new_id("m"), "machine", rng.choice(["generator", "winch", "pump"]),
                                      rng.choice(COLORS), fine={"drives": d.id, "fault": part},
                                      state={"running": False}, location=path[i], critical=True))
                    d.state["needs_machine"] = m.id
                    right = self.laws.tool_for[part]
                    wrong = rng.choice([t for t in REPAIR_TOOLS if t != right])
                    place(Obj(self._new_id("t"), "tool", right, rng.choice(COLORS), critical=True), allowed)
                    place(Obj(self._new_id("t"), "tool", wrong, rng.choice(COLORS), critical=True), allowed)
                    self.requirements.append(("repair", m.id, part))

        # gems
        all_rooms = list(self.rooms)
        for k in range(s.n_goals):
            idx = len(path) - 1 if k == s.n_goals - 1 else max(1, round((k + 1) * (len(path) - 1) / s.n_goals))
            idx = min(idx, len(path) - 1)
            gem = self._add(Obj(self._new_id("g"), "gem", "gem", rng.choice(COLORS), location=path[idx],
                                fine={"material": "crystal"}, critical=True))
            self.gems.append(gem.id)
            if CONTAINER in s.blocks and k == s.n_goals - 1:
                chest = self._add(Obj(self._new_id("c"), "chest", "chest", rng.choice(COLORS),
                                      fine={"material": rng.choice(KEY_MATERIALS)},
                                      state={"open": False}, location=path[idx], critical=True))
                gem.location = chest.id
                self.requirements.append(("open", chest.id, None))
                if LOCKABLE in s.blocks:
                    chest.lock = self._random_lock()
                    chest.state["locked"] = True
                    good, bad = self._keys_for(chest.lock)
                    place(good, reachable_before(idx))
                    place(bad, reachable_before(idx))
                    self.requirements.append(("unlock", chest.id, good.id))
            items_placed.append((gem, [path[idx]]))

        if CONTAINER in s.blocks and len(items_placed) > 1 and rng.random() < 0.5:
            # tuck one prerequisite into an (unlocked) crate
            cands = [o for o, _ in items_placed[:-1] if o.kind in TAKEABLE and o.location in self.rooms]
            obj = rng.choice(cands) if cands else None
            if obj is not None:
                crate = self._add(Obj(self._new_id("c"), "crate", "crate", rng.choice(COLORS),
                                      fine={"material": "wood"}, state={"open": False},
                                      location=obj.location, critical=True))
                obj.location = crate.id

        if FRAGILE in s.blocks:
            candidates = [o for o, _ in items_placed if o.kind in TAKEABLE and o.location in self.rooms]
            target = rng.choice(candidates) if candidates else None
            room = target.location if target else rng.choice(all_rooms)
            jar = self._add(Obj(self._new_id("j"), "jar", "jar", rng.choice(COLORS),
                                fine={"material": self.laws.fragile_material}, state={"sealed": True},
                                location=room, critical=True))
            if target:
                target.location = jar.id
            self.requirements.append(("smash", jar.id, target.id if target else None))
            for m in FRAGILE_CANDIDATES:
                if m == self.laws.fragile_material:
                    continue
                decoy = self._add(Obj(self._new_id("j"), "jar", "jar", rng.choice(COLORS),
                                      fine={"material": m}, state={"sealed": True},
                                      location=room, critical=True))
                self._add(Obj(self._new_id("x"), "junk", rng.choice(JUNK), rng.choice(COLORS),
                              location=decoy.id))

    def _door(self, a: str, b: str) -> Obj:
        d = self._add(Obj(self._new_id("d"), "door", "door", "", state={"open": False}, rooms=(a, b),
                          fine={"material": self._rng.choice(["oak", "iron", "pine"])}, critical=True))
        return d

    def _random_lock(self) -> dict:
        r = self._rng
        return {"color": r.choice(COLORS), "shape": r.choice(SHAPES), "material": r.choice(KEY_MATERIALS)}

    def _differs(self, v, pool):
        return self._rng.choice([x for x in pool if x != v])

    def _keys_for(self, lock: dict) -> tuple[Obj, Obj]:
        """A key matching only on the law attribute, and a decoy matching on all the others."""
        law = self.laws.key_match
        pools = {"color": COLORS, "shape": SHAPES, "material": KEY_MATERIALS}
        good = {a: (lock[a] if a == law else self._differs(lock[a], pools[a])) for a in pools}
        bad = {a: (self._differs(lock[a], pools[a]) if a == law else lock[a]) for a in pools}
        mk = lambda at: Obj(self._new_id("k"), "key", "key", at["color"],
                            fine={"shape": at["shape"], "material": at["material"]}, critical=True)
        return mk(good), mk(bad)

    def _switches_for(self, door: Obj, used: dict) -> tuple[Obj, Obj]:
        law = self.laws.link_attr
        other = "color" if law == "glyph" else "glyph"
        pools = {"glyph": GLYPHS, "color": COLORS}
        tgt = {"glyph": door.fine["glyph"], "color": door.color}
        good = {law: tgt[law], other: self._differs(tgt[other], pools[other])}
        # decoy shares the non-law attribute; its law value must not match ANY powered door
        free = [v for v in pools[law] if v not in used[law] and v != tgt[law]] or [self._differs(tgt[law], pools[law])]
        bad = {other: tgt[other], law: self._rng.choice(free)}
        mk = lambda at: Obj(self._new_id("w"), "switch", "switch", at["color"], fine={"glyph": at["glyph"]},
                            state={"on": False}, critical=True)
        return mk(good), mk(bad)

    # ================================================================ lazy growth
    def _grow_room(self, rid: str) -> None:
        room = self.rooms[rid]
        if room.grown:
            return
        room.grown = True
        r = random.Random(_h(self.seed.surface_seed, "room", rid))
        for _ in range(self.seed.n_distractors):
            roll = r.random()
            if roll < 0.15:
                o = Obj(self._new_id("k"), "key", "key", r.choice(COLORS),
                        fine={"shape": r.choice(SHAPES), "material": r.choice(KEY_MATERIALS)}, location=rid)
            elif roll < 0.35:
                o = Obj(self._new_id("c"), "crate", "crate", r.choice(COLORS), fine={"material": "wood"},
                        state={"open": False}, location=rid)
                self._add(o)
                o = Obj(self._new_id("x"), "junk", r.choice(JUNK), r.choice(COLORS), location=o.id)
            else:
                o = Obj(self._new_id("o"), "decor", r.choice(DECOR), r.choice(COLORS),
                        fine={"material": r.choice(["glass", "clay", "wood", "brass", "stone"])}, location=rid)
            self._add(o)

    def _grow_components(self, o: Obj) -> None:
        if o.components is not None:
            return
        r = random.Random(_h(self.seed.surface_seed, "obj", o.id))
        comps: list[Component] = []
        if o.kind == "machine":
            fault = o.fine["fault"]
            comps.append(Component(f"{o.id}.casing", "casing", "ok", "a dented but intact casing"))
            comps.append(Component(f"{o.id}.core", "core", "ok" if o.state.get("running") else "faulty",
                                   PART_FAULTS[fault] if not o.state.get("running") else "working smoothly",
                                   part=fault))
            comps.append(Component(f"{o.id}.wiring", "wiring", "ok", f"cables run to door {o.fine['drives']}"))
            r.shuffle(comps)
        elif o.kind == "decor":
            comps.append(Component(f"{o.id}.surface", "surface", "ok",
                                   r.choice(["dusty", "scratched", "polished", "faded"])))
        o.components = comps
        self.nodes_grown += len(comps)

    # ================================================================ queries
    def room_objects(self, rid: str) -> list[Obj]:
        out = []
        for o in self.objs.values():
            if o.kind == "door":
                if rid in o.rooms:
                    out.append(o)
            elif o.location == rid:
                out.append(o)
        return out

    def contents(self, cid: str) -> list[Obj]:
        return [o for o in self.objs.values() if o.location == cid]

    def accessible(self, oid: str) -> bool:
        """Is object ``oid`` physically reachable by the agent right now?"""
        o = self.objs.get(oid)
        if o is None:
            return False
        if o.kind == "door":
            return self.agent_room in o.rooms
        loc = o.location
        if loc == "inv" or loc == self.agent_room:
            return True
        holder = self.objs.get(loc or "")
        if holder and holder.kind in ("chest", "crate") and holder.state.get("open"):
            return self.accessible(holder.id)
        return False

    def room_of(self, oid: str) -> str | None:
        o = self.objs[oid]
        while o.location in self.objs:
            o = self.objs[o.location]
        return o.location if o.location in self.rooms else (self.agent_room if o.location == "inv" else None)

    def neighbors(self, rid: str) -> list[tuple[str, Obj]]:
        out = []
        for o in self.objs.values():
            if o.kind == "door" and rid in o.rooms:
                other = o.rooms[1] if o.rooms[0] == rid else o.rooms[0]
                out.append((other, o))
        return out

    @property
    def goal(self) -> str | None:
        return self.gems[self.goal_index] if self.goal_index < len(self.gems) else None

    @property
    def done(self) -> bool:
        return self.goal is not None and self.goal in self.inventory

    @property
    def out_of_budget(self) -> bool:
        return self.actions >= self.max_actions

    def visible_attrs(self, oid: str | None) -> dict:
        """Attributes of ``oid`` the agent has perceived (coarse always, fine if zoomed)."""
        if not oid or oid not in self.objs:
            return {}
        o = self.objs[oid]
        d = {"id": o.id, "kind": o.kind, "name": o.name}
        if o.color:
            d["color"] = o.color
        if oid in self.seen_fine:
            for k, v in o.fine.items():
                if k in ("fault", "drives", "blocks"):
                    continue
                d[k] = v
            if o.lock:
                d.update({f"lock_{k}": v for k, v in o.lock.items()})
        if o.kind == "machine" and oid in self.seen_parts:
            d["fault"] = o.fine["fault"]
        return d

    # ================================================================ views
    def _state_str(self, o: Obj) -> str:
        bits = []
        if o.kind in ("door", "chest", "crate"):
            bits.append("open" if o.state.get("open") else "closed")
        if o.kind == "jar":
            bits.append("shattered" if o.state.get("broken") else "sealed")
        if o.kind == "switch":
            bits.append("ON" if o.state.get("on") else "off")
        if o.kind == "machine":
            bits.append("running" if o.state.get("running") else "not running")
        if o.kind == "boulder":
            bits.append(f"blocking {o.fine['blocks']}" if not o.state.get("moved") else "pushed aside")
        if o.kind == "door" and o.state.get("needs_power"):
            bits.append("powered" if o.state.get("powered") else "unpowered")
        return ", ".join(bits)

    def _obj_line(self, o: Obj, here: str) -> str:
        if o.kind == "door":
            other = o.rooms[1] if o.rooms[0] == here else o.rooms[0]
            name = self.rooms[other].name if self.rooms[other].visited else "unexplored"
            line = f"{o.id} {o.color + ' ' if o.color else ''}door to {other} ({name}) [{self._state_str(o)}]"
        else:
            st = self._state_str(o)
            line = f"{o.label()}" + (f" [{st}]" if st else "")
        if self.eager:
            line += self._fine_str(o)
        if o.kind in ("chest", "crate") and o.state.get("open"):
            inner = self.contents(o.id)
            line += " contains: " + (", ".join(x.label() for x in inner) if inner else "nothing")
        return line

    def _fine_str(self, o: Obj) -> str:
        self._grow_components(o)
        parts = [f"{k}={v}" for k, v in o.fine.items() if k not in ("fault", "drives", "blocks")]
        if o.lock:
            parts.append("lock(" + ", ".join(f"{k}={v}" for k, v in o.lock.items()) +
                         (", locked" if o.state.get("locked") else ", unlocked") + ")")
        for c in o.components or []:
            parts.append(f"{c.name}:{c.status}:{c.detail}")
        self.seen_fine.add(o.id)
        if o.kind == "machine":
            self.seen_parts.add(o.id)
        return " {" + "; ".join(parts) + "}" if parts else ""

    def view_world(self) -> str:
        lines = [f"[WORLD] You are in {self.agent_room} ({self.rooms[self.agent_room].name})."]
        for rid, room in self.rooms.items():
            if not room.visited and not any(self.rooms[n].visited for n, _ in self.neighbors(rid)):
                continue
            here = " (you are here)" if rid == self.agent_room else ""
            if room.visited:
                doors = [f"{d.id}->{n} [{self._state_str(d)}]" for n, d in self.neighbors(rid)]
                lines.append(f"  {rid} {room.name}{here}: doors {', '.join(doors)}")
            else:
                lines.append(f"  {rid} unexplored")
        lines.append(self.status_line())
        return "\n".join(lines)

    def view_room(self, rid: str) -> str:
        self._grow_room(rid)
        objs = self.room_objects(rid)
        lines = [f"[ROOM {rid} {self.rooms[rid].name}]" + (" (you are here)" if rid == self.agent_room else
                                                            " (remote view, remembered)")]
        for o in objs:
            lines.append("  " + self._obj_line(o, rid))
        lines.append(self.status_line())
        return "\n".join(lines)

    def view_obj(self, oid: str) -> str:
        o = self.objs[oid]
        self._grow_components(o)
        self.seen_fine.add(oid)
        lines = [f"[OBJECT {o.label()}] state: {self._state_str(o) or '-'}"]
        for k, v in o.fine.items():
            if k in ("fault",):
                continue
            if k == "drives":
                continue  # revealed via the wiring component
            if k == "blocks":
                lines.append(f"  blocks door {v}")
                continue
            lines.append(f"  {k}: {v}")
        if o.lock:
            lines.append("  lock: " + ", ".join(f"{k}={v}" for k, v in o.lock.items()) +
                         (" (locked)" if o.state.get("locked") else " (unlocked)"))
        if o.kind == "door":
            if o.state.get("needs_power"):
                lines.append("  a power socket is set into the frame (" +
                             ("live" if o.state.get("powered") else "dead") + ")")
            if o.state.get("needs_machine"):
                lines.append("  heavy gears connect the door to some machine")
            if o.state.get("blocked_by") and not self.objs[o.state["blocked_by"]].state.get("moved"):
                lines.append(f"  a boulder ({o.state['blocked_by']}) blocks it")
        if o.kind == "jar":
            inner = self.contents(o.id)
            lines.append("  something rattles inside" if inner and not o.state.get("broken") else "  feels empty")
        for c in o.components or []:
            lines.append(f"  component {c.id}: {c.name} ({c.status})")
        if o.kind in ("chest", "crate") and o.state.get("open"):
            lines.append("  contains: " + (", ".join(x.label() for x in self.contents(o.id)) or "nothing"))
        lines.append(self.status_line())
        return "\n".join(lines)

    def view_component(self, cid: str) -> str:
        oid = cid.split(".")[0]
        o = self.objs[oid]
        c = next(c for c in o.components or [] if c.id == cid)
        if c.part:
            self.seen_parts.add(oid)
        return f"[COMPONENT {cid}] {c.name} ({c.status}): {c.detail}\n" + self.status_line()

    def prompt_spec(self) -> dict:
        return {
            "intro": "You are an embodied agent exploring a symbolic world made of rooms, doors and objects.",
            "goal": f"obtain (take) the gem {self.goal}. It may be behind closed, locked, unpowered or blocked "
                    "doors, or inside containers.",
            "levels": "world map -> rooms -> objects -> components",
            "details": "(shape, material, glyph, lock, components)",
            "verbs": "go <room>, take <obj>, drop <obj>, open <door/chest/crate>, unlock <door/chest> with <key>, "
                     "press <switch>, push <boulder>, smash <jar>, repair <machine> with <tool>",
            "notes": "You can only act on things in your current room (or items you hold). Things you change "
                     "stay changed (opened doors stay open, shattered jars stay shattered).",
            "laws_hint": "Laws of this universe (which key fits which lock, what breaks, what powers what, which "
                         "tool fixes what) are consistent across worlds but NOT necessarily what you would expect.",
            "done_text": "When you hold the gem the episode ends automatically.",
        }

    def status_line(self) -> str:
        inv = ", ".join(self.objs[i].label() for i in self.inventory) or "nothing"
        return (f"(holding: {inv} | goal: obtain {self.goal} | actions used {self.actions}/{self.max_actions} "
                f"| zoom: {'/'.join(['world'] + self.focus)})")

    def observe(self) -> str:
        if self.eager:
            return self.view_world() + "\n" + self.view_room(self.agent_room)
        if not self.focus:
            return self.view_world()
        f = self.focus[-1]
        if f in self.rooms:
            return self.view_room(f)
        if f in self.objs:
            return self.view_obj(f)
        return self.view_component(f)

    # ================================================================ zoom
    def zoom_in(self, target: str) -> str:
        self.zoom_ops += 1
        target = target.strip()
        cur = self.focus[-1] if self.focus else None
        if cur is None:
            if target not in self.rooms:
                return f"Cannot zoom into '{target}' from the world view; choose a room id.\n" + self.observe()
            if not self.rooms[target].visited:
                return f"Room {target} is unexplored; you must go there first.\n" + self.observe()
            self.focus = [target]
            return self.observe()
        if cur in self.rooms:
            ids = {o.id for o in self.room_objects(cur)}
            for o in self.room_objects(cur):
                if o.kind in ("chest", "crate") and o.state.get("open"):
                    ids |= {x.id for x in self.contents(o.id)}
            ids |= set(self.inventory)
            if target not in ids:
                return f"No object '{target}' visible in {cur}.\n" + self.observe()
            self.focus.append(target)
            return self.observe()
        if cur in self.objs:
            o = self.objs[cur]
            comp_ids = {c.id for c in o.components or []}
            if target not in comp_ids:
                return f"'{target}' is not a component of {cur}.\n" + self.observe()
            self.focus.append(target)
            return self.observe()
        return "You are already at the finest level of detail.\n" + self.observe()

    def zoom_out(self) -> str:
        self.zoom_ops += 1
        if self.focus:
            self.focus.pop()
        return self.observe()

    # ================================================================ dynamics
    def _enter(self, rid: str) -> None:
        self.agent_room = rid
        self.rooms[rid].visited = True
        self._grow_room(rid)
        self.focus = [rid]

    def _recompute_power(self) -> list[str]:
        changed = []
        law = self.laws.link_attr
        switches = [o for o in self.objs.values() if o.kind == "switch" and o.state.get("on")]
        for d in self.objs.values():
            if d.kind != "door" or not d.state.get("needs_power"):
                continue
            val = d.fine["glyph"] if law == "glyph" else d.color
            new = any((s.fine["glyph"] if law == "glyph" else s.color) == val for s in switches)
            if new != d.state.get("powered"):
                d.state["powered"] = new
                changed.append(d.id)
        return changed

    # pure transition predicates (also used for interventional similarity probes)
    def would_unlock(self, key: Obj, lock: dict) -> bool:
        a = self.laws.key_match
        kv = key.color if a == "color" else key.fine.get(a)
        return kv == lock[a]

    def would_shatter(self, jar: Obj) -> bool:
        return jar.fine.get("material") == self.laws.fragile_material

    def would_repair(self, machine: Obj, tool: Obj) -> bool:
        return self.laws.tool_for[machine.fine["fault"]] == tool.name

    def can_push(self, tool_names: list[str]) -> bool:
        return self.laws.push_tool in tool_names

    def act(self, verb: str, target: str | None = None, instrument: str | None = None) -> tuple[str, bool]:
        verb = (verb or "").strip().lower()
        target = (target or "").strip() or None
        instrument = (instrument or "").strip() or None
        if self.out_of_budget:
            return "Out of action budget.", False
        self.actions += 1
        ev = Event(self.actions, verb, target, instrument, False, True, "",
                   target_attrs=self.visible_attrs(target), instr_attrs=self.visible_attrs(instrument),
                   inventory=[self.objs[i].name for i in self.inventory])
        msg, ok, valid = self._dispatch(verb, target, instrument, ev)
        ev.success, ev.valid, ev.message = ok, valid, msg
        if not valid:
            self.invalid_actions += 1
        self.events.append(ev)
        if self.done:
            msg += f" GOAL COMPLETE: you hold {self.goal}."
        elif self.out_of_budget:
            msg += " You have run out of actions."
        return msg, ok

    def _dispatch(self, verb, target, instrument, ev) -> tuple[str, bool, bool]:
        O = self.objs
        if verb == "go":
            if target not in self.rooms:
                return f"No room '{target}'.", False, False
            for n, d in self.neighbors(self.agent_room):
                if n == target:
                    if not d.state.get("open"):
                        return f"Door {d.id} is closed.", False, True
                    self._enter(target)
                    return f"You walk into {target} ({self.rooms[target].name}).\n" + self.view_room(target), True, True
            return f"{target} is not adjacent to {self.agent_room}.", False, False

        if target is None or target not in O:
            return f"Unknown object '{target}'.", False, False
        o = O[target]
        if not self.accessible(target):
            return f"{target} is not within reach (you are in {self.agent_room}).", False, False
        tool = None
        if instrument:
            if instrument not in O or instrument not in self.inventory:
                return f"You are not holding '{instrument}'.", False, False
            tool = O[instrument]

        if verb == "take":
            if o.kind not in TAKEABLE:
                return f"The {o.name} cannot be taken.", False, True
            if o.location == "inv":
                return f"You already hold {o.id}.", False, False
            o.location = "inv"
            self.inventory.append(o.id)
            return f"You take {o.label()}.", True, True
        if verb == "drop":
            if o.id not in self.inventory:
                return f"You are not holding {o.id}.", False, False
            self.inventory.remove(o.id)
            o.location = self.agent_room
            return f"You drop {o.label()}.", True, True
        if verb == "open":
            if o.kind == "door":
                if o.state.get("open"):
                    return f"{o.id} is already open.", True, True
                b = o.state.get("blocked_by")
                if b and not O[b].state.get("moved"):
                    return f"A boulder ({b}) blocks door {o.id}.", False, True
                if o.state.get("locked"):
                    return f"Door {o.id} is locked.", False, True
                if o.state.get("needs_power") and not o.state.get("powered"):
                    return f"Door {o.id} will not budge; its mechanism seems dead.", False, True
                m = o.state.get("needs_machine")
                if m and not O[m].state.get("running"):
                    return f"Door {o.id}'s gears are jammed; something must drive them.", False, True
                o.state["open"] = True
                return f"Door {o.id} swings open.", True, True
            if o.kind in ("chest", "crate"):
                if o.state.get("open"):
                    return f"{o.id} is already open.", True, True
                if o.state.get("locked"):
                    return f"The {o.name} {o.id} is locked.", False, True
                o.state["open"] = True
                inner = self.contents(o.id)
                return f"You open {o.id}. Inside: " + (", ".join(x.label() for x in inner) or "nothing") + ".", True, True
            if o.kind == "jar":
                return f"Jar {o.id} is sealed tight; it cannot be opened normally.", False, True
            return f"The {o.name} cannot be opened.", False, True
        if verb == "unlock":
            if not o.lock:
                return f"{o.id} has no lock.", False, False
            if tool is None or tool.kind != "key":
                return "You need to hold a key to unlock something.", False, False
            if not o.state.get("locked"):
                return f"{o.id} is already unlocked.", True, True
            if self.would_unlock(tool, o.lock):
                o.state["locked"] = False
                return f"Click. {o.id} is unlocked.", True, True
            return f"The key {tool.id} does not fit the lock of {o.id}.", False, True
        if verb == "press":
            if o.kind != "switch":
                return f"The {o.name} is not something you can press.", False, False
            o.state["on"] = not o.state.get("on")
            changed = self._recompute_power()
            ev.effects = [dict(self.visible_attrs(d), powered=O[d].state["powered"]) for d in changed]
            hum = " Somewhere, machinery hums." if changed else ""
            return f"Click. Switch {o.id} is now {'ON' if o.state['on'] else 'off'}.{hum}", True, True
        if verb == "push":
            if o.kind != "boulder":
                return f"Pushing the {o.name} achieves nothing.", False, True
            if o.state.get("moved"):
                return "The boulder has already been moved.", True, True
            if self.can_push([O[i].name for i in self.inventory]):
                o.state["moved"] = True
                return f"With effort you shift boulder {o.id} aside. Door {o.fine['blocks']} is clear.", True, True
            return f"Boulder {o.id} will not budge with what you are holding.", False, True
        if verb == "smash":
            if o.kind != "jar":
                return f"You decide not to smash the {o.name}.", False, False
            if o.state.get("broken"):
                return "It is already shattered.", True, True
            if self.would_shatter(o):
                o.state["broken"] = True
                room = self.room_of(o.id)
                inner = self.contents(o.id)
                for x in inner:
                    x.location = room
                return f"Jar {o.id} shatters, spilling: " + (", ".join(x.label() for x in inner) or "nothing") + ".", True, True
            return f"You strike jar {o.id}, but it does not break.", False, True
        if verb == "repair":
            if o.kind != "machine":
                return f"The {o.name} does not need repair.", False, False
            if o.state.get("running"):
                return "The machine is already running.", True, True
            if tool is None or tool.kind != "tool":
                return "You need to hold a tool to repair something.", False, False
            ev.target_attrs = self.visible_attrs(o.id)
            if self.would_repair(o, tool):
                o.state["running"] = True
                for c in o.components or []:
                    if c.part:
                        c.status, c.detail = "ok", "working smoothly"
                return f"You repair {o.id} with the {tool.name}. The {o.name} roars to life.", True, True
            return f"The {tool.name} is of no use on {o.id}'s fault.", False, True
        return f"Unknown verb '{verb}'. Valid: go, take, drop, open, unlock, press, push, smash, repair.", False, False

    # ================================================================ episodes / persistence
    def next_goal(self, reset_agent: bool = True) -> bool:
        """Advance to the next gem (persistent-world protocol). Returns False if none left."""
        if self.goal_index + 1 >= len(self.gems):
            return False
        self.goal_index += 1
        self.actions = self.invalid_actions = self.zoom_ops = 0
        self.events = []
        if reset_agent:
            self._enter(self.start_room)
        return True

    def clone(self) -> "World":
        return copy.deepcopy(self)

    def shortest_path(self, src: str, dst: str) -> list[tuple[str, Obj]]:
        """Room path (ignoring door states) as [(next_room, door), ...]."""
        prev: dict[str, tuple[str, Obj] | None] = {src: None}
        q = deque([src])
        while q:
            r = q.popleft()
            if r == dst:
                break
            for n, d in self.neighbors(r):
                if n not in prev:
                    prev[n] = (r, d)
                    q.append(n)
        out = []
        cur = dst
        while prev.get(cur):
            p, d = prev[cur]
            out.append((cur, d))
            cur = p
        return out[::-1]


def grow(seed: WorldSeed, **kw) -> World:
    """Grow (lazily) a world from a seed: E_0 = G(z_0)."""
    return World(seed, **kw)
