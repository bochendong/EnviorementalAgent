"""Universe laws (the hidden causal parameters theta shared by every world in a universe).

A *universe* fixes how causal blocks behave (e.g. "keys fit locks of the same SHAPE").
Individual worlds sampled in that universe differ in surface details (names, colours,
layout, which blocks are present), so laws can only be separated from accidents by
looking across many worlds. This is the "variation reveals invariance" premise of the
program (section 3 of the program seed).
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

COLORS = ["red", "blue", "green", "yellow", "purple", "orange"]
SHAPES = ["star", "moon", "square", "triangle", "circle", "hex"]
MATERIALS = ["brass", "iron", "glass", "clay", "wood", "ice", "stone"]
FRAGILE_CANDIDATES = ["glass", "clay", "ice"]
GLYPHS = ["sun", "eye", "wave", "spiral", "tree"]
PARTS = ["fuse", "gear", "pipe", "valve"]
REPAIR_TOOLS = ["pliers", "wrench", "tape", "hammer"]
PUSH_TOOLS = ["lever", "rope"]

KEY_ATTRS = ["color", "shape", "material"]
LINK_ATTRS = ["glyph", "color"]

# Natural-language part descriptions shown when the agent zooms into a faulty component.
PART_FAULTS = {
    "fuse": "a blown fuse",
    "gear": "a gear with sheared teeth",
    "pipe": "a cracked pipe",
    "valve": "a seized valve",
}


@dataclass(frozen=True)
class Laws:
    """Hidden causal parameters of a universe."""

    key_match: str = "color"  # attribute a key must share with a lock
    fragile_material: str = "glass"  # sealed jars of this material shatter when smashed
    link_attr: str = "glyph"  # switches power doors sharing this attribute
    tool_map: tuple[tuple[str, str], ...] = field(
        default=(("fuse", "pliers"), ("gear", "wrench"), ("pipe", "tape"), ("valve", "hammer"))
    )
    push_tool: str = "lever"  # tool needed to move a boulder

    # ------------------------------------------------------------------ helpers
    @property
    def tool_for(self) -> dict[str, str]:
        return dict(self.tool_map)

    @classmethod
    def sample(cls, rng: random.Random) -> "Laws":
        tools = REPAIR_TOOLS[:]
        rng.shuffle(tools)
        return cls(
            key_match=rng.choice(KEY_ATTRS),
            fragile_material=rng.choice(FRAGILE_CANDIDATES),
            link_attr=rng.choice(LINK_ATTRS),
            tool_map=tuple(zip(PARTS, tools)),
            push_tool=rng.choice(PUSH_TOOLS),
        )

    @classmethod
    def from_index(cls, idx: int) -> "Laws":
        """Deterministic universe ``idx`` (universe 0 is the 'LLM-prior friendly' one)."""
        if idx == 0:
            return cls()
        return cls.sample(random.Random(10_000 + idx))

    def mutate(self, rng: random.Random, n: int = 1) -> "Laws":
        """Change ``n`` laws (used for law-shift / continual-learning experiments)."""
        d = asdict(self)
        d["tool_map"] = tuple(tuple(x) for x in d["tool_map"])
        keys = rng.sample(["key_match", "fragile_material", "link_attr", "tool_map", "push_tool"], n)
        for k in keys:
            if k == "key_match":
                d[k] = rng.choice([a for a in KEY_ATTRS if a != self.key_match])
            elif k == "fragile_material":
                d[k] = rng.choice([m for m in FRAGILE_CANDIDATES if m != self.fragile_material])
            elif k == "link_attr":
                d[k] = rng.choice([a for a in LINK_ATTRS if a != self.link_attr])
            elif k == "push_tool":
                d[k] = rng.choice([t for t in PUSH_TOOLS if t != self.push_tool])
            else:
                tools = [t for _, t in self.tool_map]
                rotated = tools[1:] + tools[:1]
                d[k] = tuple(zip(PARTS, rotated))
        return Laws(**d)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tool_map"] = dict(self.tool_map)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Laws":
        d = dict(d)
        tm = d.get("tool_map")
        if isinstance(tm, dict):
            d["tool_map"] = tuple((p, tm[p]) for p in PARTS)
        elif tm is not None:
            d["tool_map"] = tuple(tuple(x) for x in tm)
        return cls(**d)

    def describe(self, blocks: list[str] | None = None) -> list[str]:
        """Ground-truth laws in natural language (used by the oracle-seed condition)."""
        lines = {
            "lockable": f"A key opens a lock only if the key and the lock share the same {self.key_match.upper()}.",
            "fragile": f"Only sealed jars made of {self.fragile_material.upper()} shatter when smashed.",
            "powered": f"A switch powers every door that shares its {self.link_attr.upper()}.",
            "machine": "A broken machine is fixed by repairing it with the right tool for its faulty part: "
            + ", ".join(f"{p}->{t}" for p, t in self.tool_map)
            + ".",
            "pushable": f"Boulders can only be pushed while holding a {self.push_tool.upper()}.",
        }
        if blocks is None:
            return list(lines.values())
        return [lines[b] for b in blocks if b in lines]
