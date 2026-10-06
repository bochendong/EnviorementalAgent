"""Interventional environment similarity (section 3 of the program seed).

Two worlds are compared by how they *respond to interventions*, not by how they
look. For each world we probe the transition function with canonical interventions
(every key on every lock, every tool on every machine, ...) and abstract each
outcome to a relational pattern, e.g. ("unlock", matches=("shape",)) -> True. The
resulting signature is surface-independent: worlds with different objects, colours
and layouts but the same causal DNA get similarity 1 on their overlapping probes.
"""

from __future__ import annotations

from collections import Counter

from .laws import KEY_ATTRS, LINK_ATTRS, PUSH_TOOLS
from .world import World


def interventional_signature(w: World) -> dict[tuple, bool]:
    sig: dict[tuple, bool] = {}
    objs = list(w.objs.values())
    keys = [o for o in objs if o.kind == "key"]
    locks = [o for o in objs if o.lock]
    for k in keys:
        for lk in locks:
            kv = {"color": k.color, **k.fine}
            pattern = tuple(a for a in KEY_ATTRS if kv.get(a) == lk.lock[a])
            sig[("unlock", pattern)] = w.would_unlock(k, lk.lock)
    for j in (o for o in objs if o.kind == "jar"):
        sig[("smash", j.fine["material"])] = w.would_shatter(j)
    tools = [o for o in objs if o.kind == "tool"]
    for m in (o for o in objs if o.kind == "machine"):
        for t in tools:
            sig[("repair", m.fine["fault"], t.name)] = w.would_repair(m, t)
    if any(o.kind == "boulder" for o in objs):
        for t in PUSH_TOOLS:
            sig[("push", t)] = w.can_push([t])
    doors = [o for o in objs if o.kind == "door" and o.state.get("needs_power")]
    for s in (o for o in objs if o.kind == "switch"):
        for d in doors:
            sv = {"glyph": s.fine["glyph"], "color": s.color}
            dv = {"glyph": d.fine["glyph"], "color": d.color}
            pattern = tuple(a for a in LINK_ATTRS if sv[a] == dv[a])
            sig[("press", pattern)] = sv[w.laws.link_attr] == dv[w.laws.link_attr]
    return sig


def interventional_similarity(a: World, b: World) -> tuple[float, int]:
    """(agreement on shared probes, number of shared probes). NaN-free: 1.0 if nothing shared."""
    sa, sb = interventional_signature(a), interventional_signature(b)
    shared = set(sa) & set(sb)
    if not shared:
        return 1.0, 0
    return sum(sa[k] == sb[k] for k in shared) / len(shared), len(shared)


def observational_similarity(a: World, b: World) -> float:
    """Bag-of-(kind, colour) Jaccard: a deliberately naive appearance-based baseline."""
    ca = Counter((o.kind, o.color) for o in a.objs.values())
    cb = Counter((o.kind, o.color) for o in b.objs.values())
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    return inter / union if union else 1.0
