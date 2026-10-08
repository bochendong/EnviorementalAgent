"""Agent-side memories, i.e. what is carried from one world to the next.

* ``SeedMemory``       - the *learned* world seed S_t. Structured causal hypotheses
                         (one hypothesis space per causal block) whose evidence is
                         consolidated from interaction events across worlds, plus
                         optional free-text rules written by an LLM consolidator.
                         It renders itself as compact "causal DNA" for the agent and
                         supports ``predict`` (a tiny world model) whose uncertainty
                         drives adaptive zoom.
* ``RetrievalMemory``  - baseline: event lines stored verbatim, keyword retrieval.
* ``TrajectoryMemory`` - baseline: the last K episode logs pasted into context.

Consolidation only uses attributes the agent actually perceived (``Event`` records
visible attributes), so the learned seed never peeks at hidden ground truth.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .laws import FRAGILE_CANDIDATES, KEY_ATTRS, LINK_ATTRS, PARTS, PUSH_TOOLS, REPAIR_TOOLS, Laws
from .world import Event, World

SPACES = {
    "key_match": KEY_ATTRS,
    "fragile_material": FRAGILE_CANDIDATES,
    "link_attr": LINK_ATTRS,
    "push_tool": PUSH_TOOLS + ["none"],
    **{f"tool_for.{p}": REPAIR_TOOLS for p in PARTS},
}

SPACE_BLOCK = {
    "key_match": "lockable",
    "fragile_material": "fragile",
    "link_attr": "powered",
    "push_tool": "pushable",
    **{f"tool_for.{p}": "machine" for p in PARTS},
}


@dataclass
class Hyp:
    support: float = 0.0
    against: float = 0.0

    def belief(self) -> float:
        return (self.support + 1.0) / (self.support + self.against + 2.0)


class LawSeed:
    """A learned seed: one hypothesis space per causal block, filled with evidence.

    Subclasses (one per environment family) define ``SPACES``, how events become
    evidence (``consolidate_events``), how the seed reads as text (``render_laws``),
    its tiny world model (``predict``) and the ground truth for scoring (``truth``)."""

    SPACES: dict[str, list[str]] = {}

    def __init__(self, decay: float = 1.0):
        self.decay = decay  # <1.0 = recency weighting (helps when laws shift)
        self.hyps: dict[str, dict[str, Hyp]] = {s: {h: Hyp() for h in hs} for s, hs in self.SPACES.items()}
        self.rules: list[str] = []  # free-text rules (LLM consolidator)
        self.reflected: list[tuple[str, str]] = []  # (law, value) the LLM consolidator claims; scored, not used
        self.worlds_seen = 0
        self.events_seen = 0

    # ------------------------------------------------------------ evidence
    def _vote(self, space: str, hyp: str, ok: bool, w: float = 1.0) -> None:
        if hyp not in self.hyps.get(space, {}):
            return
        h = self.hyps[space][hyp]
        if ok:
            h.support += w
        else:
            h.against += w

    def _vote_exclusive(self, space: str, hyp: str, w: float = 1.0) -> None:
        """Evidence that ``hyp`` is THE answer of a one-of-N space."""
        for h in self.hyps.get(space, {}):
            self._vote(space, h, h == hyp, w)

    def _apply_decay(self) -> None:
        if self.decay < 1.0:
            for sp in self.hyps.values():
                for h in sp.values():
                    h.support *= self.decay
                    h.against *= self.decay

    def best(self, space: str) -> tuple[str, float, float]:
        """(hypothesis, belief, evidence) for the leading hypothesis of ``space``."""
        items = self.hyps[space]
        h, v = max(items.items(), key=lambda kv: (kv[1].belief(), kv[1].support))
        return h, v.belief(), v.support + v.against

    def confident(self, space: str, thresh: float = 0.75, min_evidence: float = 1.0) -> str | None:
        h, b, n = self.best(space)
        others = [x.belief() for k, x in self.hyps[space].items() if k != h]
        margin = b - (max(others) if others else 0.0)
        return h if b >= thresh and n >= min_evidence and margin > 0.1 else None

    def allowed(self, space: str) -> list[str]:
        return self.SPACES.get(space, [])

    def reflection_score(self, laws) -> tuple[int, int, int]:
        """(correct, wrong, invalid) among the LLM consolidator's claims about the laws; a claim is
        invalid when the law does not exist or the value is not one it can take."""
        truth = self.truth(laws)
        valid = [(sp, v) for sp, v in self.reflected if sp in truth and v in self.allowed(sp)]
        ok = sum(1 for sp, v in valid if truth[sp] == v)
        return ok, len(valid) - ok, len(self.reflected) - len(valid)

    def recovery(self, laws) -> dict[str, bool | None]:
        """Per-space: did the seed recover the true law? (None = no confident belief yet)."""
        truth = self.truth(laws)
        return {sp: (None if self.confident(sp) is None else self.confident(sp) == truth[sp]) for sp in self.SPACES}

    def render(self, max_rules: int = 12) -> str:
        """The seed as compact causal DNA (text injected into the agent's instructions)."""
        lines = self.render_laws() + [f"- {r}" for r in self.rules[:max_rules]]
        return "\n".join(lines) if lines else "(no consolidated world knowledge yet)"

    # ------------------------------------------------------------ subclass hooks
    def consolidate_events(self, events) -> int:
        raise NotImplementedError

    def render_laws(self) -> list[str]:
        raise NotImplementedError

    def predict(self, world, verb: str, target: str, instrument: str | None = None) -> str:
        return "No learned law covers this action."

    @staticmethod
    def truth(laws) -> dict[str, str]:
        raise NotImplementedError

    # ------------------------------------------------------------ io
    def to_dict(self) -> dict:
        return {
            "type": type(self).__name__,
            "decay": self.decay,
            "hyps": {s: {h: [v.support, v.against] for h, v in hs.items()} for s, hs in self.hyps.items()},
            "rules": self.rules,
            "reflected": [list(c) for c in self.reflected],
            "worlds_seen": self.worlds_seen,
            "events_seen": self.events_seen,
        }

    @classmethod
    def from_dict(cls, d: dict):
        m = cls(decay=d.get("decay", 1.0))
        for s, hs in d["hyps"].items():
            for h, (sup, ag) in hs.items():
                m.hyps[s][h] = Hyp(sup, ag)
        m.rules = list(d.get("rules", []))
        m.reflected = [tuple(c) for c in d.get("reflected", [])]
        m.worlds_seen = d.get("worlds_seen", 0)
        m.events_seen = d.get("events_seen", 0)
        return m

    def merge(self, other: "LawSeed") -> None:
        """Merge another agent's evidence into this seed (shared multi-agent seed)."""
        for s, hs in other.hyps.items():
            for h, v in hs.items():
                self.hyps[s][h].support += v.support
                self.hyps[s][h].against += v.against
        for r in other.rules:
            if r not in self.rules:
                self.rules.append(r)

    @classmethod
    def certain_of(cls, laws, strength: float = 50.0):
        """A seed certain of the true laws (oracle condition for the heuristic agent)."""
        m = cls()
        truth = cls.truth(laws)
        for sp, hs in cls.SPACES.items():
            for h in hs:
                m.hyps[sp][h] = Hyp(strength, 0.0) if h == truth[sp] else Hyp(0.0, strength)
        return m


class SeedMemory(LawSeed):
    """The learned seed for the dungeon world (locks, jars, switches, machines, boulders)."""

    SPACES = SPACES

    @staticmethod
    def truth(laws: Laws) -> dict[str, str]:
        return {
            "key_match": laws.key_match,
            "fragile_material": laws.fragile_material,
            "link_attr": laws.link_attr,
            "push_tool": laws.push_tool,
            **{f"tool_for.{p}": t for p, t in laws.tool_map},
        }


    def consolidate_events(self, events: list[Event]) -> int:
        """Symbolic consolidation: C(S_t, trajectory) -> S_{t+1}. Returns #informative events."""
        self._apply_decay()
        used = 0
        for ev in events:
            if not ev.valid:
                continue
            t, i = ev.target_attrs, ev.instr_attrs
            if ev.verb == "unlock" and i.get("kind") == "key" and "already" not in ev.message:
                for a in KEY_ATTRS:
                    kv, lv = i.get(a), t.get(f"lock_{a}")
                    if kv is None or lv is None:
                        continue
                    self._vote("key_match", a, (kv == lv) == ev.success)
                    used += 1
            elif ev.verb == "smash" and t.get("kind") == "jar" and "already" not in ev.message:
                m = t.get("material")
                if m is None:
                    continue
                for cand in FRAGILE_CANDIDATES:
                    self._vote("fragile_material", cand, (m == cand) == ev.success)
                used += 1
            elif ev.verb == "press" and t.get("kind") == "switch":
                # a hypothesis is consistent if it predicts exactly the doors that changed
                changed = ev.effects
                for a in LINK_ATTRS:
                    sv = t.get(a)
                    if sv is None:
                        continue
                    if changed:
                        known = [d for d in changed if d.get(a) is not None]
                        if not known:
                            continue
                        self._vote("link_attr", a, all(d.get(a) == sv for d in known))
                        used += 1
            elif ev.verb == "repair" and t.get("kind") == "machine" and "already" not in ev.message:
                part, tool = t.get("fault"), i.get("name")
                if part is None or tool not in REPAIR_TOOLS:
                    continue
                if ev.success:
                    for cand in REPAIR_TOOLS:
                        self._vote(f"tool_for.{part}", cand, cand == tool)
                else:
                    self._vote(f"tool_for.{part}", tool, False)
                used += 1
            elif ev.verb == "push" and t.get("kind") == "boulder" and "already" not in ev.message:
                held = set(ev.inventory)
                for cand in PUSH_TOOLS + ["none"]:
                    pred = cand == "none" or cand in held
                    if ev.success:
                        self._vote("push_tool", cand, pred)
                    elif pred:
                        self._vote("push_tool", cand, False)
                used += 1
        self.events_seen += len(events)
        return used

    # ------------------------------------------------------------ queries
    def as_laws_guess(self) -> dict:
        out = {}
        for sp in ("key_match", "fragile_material", "link_attr", "push_tool"):
            out[sp] = self.best(sp)[0]
        out["tool_map"] = {p: self.best(f"tool_for.{p}")[0] for p in PARTS}
        return out

    def render_laws(self) -> list[str]:
        lines = []
        km = self.confident("key_match")
        if km:
            lines.append(f"- [lockable] A key opens a lock only when they share the same {km.upper()} "
                         f"(belief {self.best('key_match')[1]:.2f}).")
        fm = self.confident("fragile_material")
        if fm:
            lines.append(f"- [fragile] Only sealed jars made of {fm.upper()} shatter when smashed "
                         f"(belief {self.best('fragile_material')[1]:.2f}).")
        la = self.confident("link_attr")
        if la:
            lines.append(f"- [powered] A switch powers the doors that share its {la.upper()} "
                         f"(belief {self.best('link_attr')[1]:.2f}).")
        pt = self.confident("push_tool")
        if pt:
            lines.append(f"- [pushable] Boulders move only while holding a {pt.upper()}." if pt != "none"
                         else "- [pushable] Boulders can be pushed bare-handed.")
        tm = [(p, self.confident(f"tool_for.{p}")) for p in PARTS]
        known = [f"{p}->{t}" for p, t in tm if t]
        if known:
            lines.append("- [machine] Repair a machine's faulty part with: " + ", ".join(known) + ".")
        return lines

    # ------------------------------------------------------------ world model
    def predict(self, world: World, verb: str, target: str, instrument: str | None = None) -> str:
        """W(S_t, focus, a) -> predicted outcome + uncertainty, using only perceived attributes.

        When the relevant attribute has not been perceived, the answer names what to
        zoom into: this is the uncertainty-triggered zoom of section 7."""
        t = world.visible_attrs(target)
        i = world.visible_attrs(instrument)
        if not t:
            return f"Unknown target '{target}'."
        verb = verb.lower()
        if verb == "unlock":
            a = self.confident("key_match")
            if a is None:
                return (f"UNCERTAIN: no confident law for keys yet. Zoom into {target} and {instrument} "
                        "before trying, so the outcome teaches you the law.")
            kv, lv = i.get(a), t.get(f"lock_{a}")
            if lv is None:
                return f"UNCERTAIN: zoom into {target} to read its lock {a}."
            if kv is None:
                return f"UNCERTAIN: zoom into {instrument} to read its {a}."
            return f"PREDICT {'SUCCESS' if kv == lv else 'FAIL'} (law: same {a}; belief {self.best('key_match')[1]:.2f})"
        if verb == "smash":
            m = self.confident("fragile_material")
            if m is None:
                return f"UNCERTAIN: fragile material not yet known. Zoom into {target} before trying."
            if "material" not in t:
                return f"UNCERTAIN: zoom into {target} to see its material."
            return f"PREDICT {'SUCCESS' if t['material'] == m else 'FAIL'} (law: {m} shatters)"
        if verb == "press":
            a = self.confident("link_attr")
            if a is None:
                return (f"UNCERTAIN: switch wiring law not yet known. Zoom into {target} (and the doors "
                        "nearby) before pressing.")
            if a not in t:
                return f"UNCERTAIN: zoom into {target} to see its {a}."
            return f"PREDICT: powers doors whose {a} is {t[a]}."
        if verb == "repair":
            if "fault" not in t:
                return f"UNCERTAIN: zoom into {target} and its faulty component to identify the part."
            tool = self.confident(f"tool_for.{t['fault']}")
            if tool is None:
                return f"UNCERTAIN: right tool for a {t['fault']} not yet known."
            if not i:
                return f"PREDICT: needs a {tool}."
            return f"PREDICT {'SUCCESS' if i.get('name') == tool else 'FAIL'} (a {t['fault']} needs a {tool})"
        if verb == "push":
            pt = self.confident("push_tool")
            if pt is None:
                return "UNCERTAIN: what moves boulders is not yet known."
            held = {world.objs[x].name for x in world.inventory}
            ok = pt == "none" or pt in held
            return f"PREDICT {'SUCCESS' if ok else 'FAIL'} (needs {pt})"
        return "No learned law covers this action."

class OracleSeed:
    """Upper bound: the agent is told the true laws (any laws object with ``describe``)."""

    def __init__(self, laws):
        self.laws = laws

    def render(self, blocks=None) -> str:
        return "\n".join(f"- {x}" for x in self.laws.describe(blocks))


# ------------------------------------------------------------------ baselines
_TOK = re.compile(r"[a-z0-9_]+")


def _tokens(s: str) -> list[str]:
    return _TOK.findall(s.lower())


@dataclass
class RetrievalMemory:
    """Episodic store of event lines; BM25-style retrieval via a ``recall`` tool."""

    entries: list[str] = field(default_factory=list)

    def add_events(self, events: list[Event], world_tag: str = "") -> None:
        for ev in events:
            if ev.valid and ev.verb != "go":
                self.entries.append(f"[{world_tag}] {ev.line()}")

    def add_note(self, note: str) -> None:
        self.entries.append(note)

    def recall(self, query: str, k: int = 8) -> list[str]:
        if not self.entries:
            return []
        docs = [_tokens(e) for e in self.entries]
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        avg = sum(map(len, docs)) / n
        q = _tokens(query)
        scores = []
        for idx, d in enumerate(docs):
            tf = Counter(d)
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
            scores.append((s, idx))
        scores.sort(reverse=True)
        return [self.entries[i] for s, i in scores[:k] if s > 0]


@dataclass
class TrajectoryMemory:
    """Raw-history baseline: last ``k`` episodes' event logs, truncated to ``max_lines``."""

    k: int = 3
    max_lines: int = 80
    episodes: list[list[str]] = field(default_factory=list)

    def add_events(self, events: list[Event], world_tag: str = "") -> None:
        self.episodes.append([f"[{world_tag}] {ev.line()}" for ev in events if ev.valid])
        self.episodes = self.episodes[-self.k:]

    def render(self) -> str:
        lines = [ln for ep in self.episodes for ln in ep][-self.max_lines:]
        return "\n".join(lines) if lines else "(no past trajectories)"


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)
