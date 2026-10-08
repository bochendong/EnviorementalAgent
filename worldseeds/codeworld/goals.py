"""Grand goals of the town: what everybody works towards, beyond the daily orders.

Each goal is a story of the town, a deadline (a sprint), and parts that are scored exactly:

    banquet       the harvest festival: several pieces (a feast, hampers, a wagon for the parade, an elixir for
                  the toast), each a long recipe (raw good -> finished dish, four
                  machines, three or more workshops) whose grades are given by examples        (assembly)
    prize         the judges' prize: a finished good of exactly a given grade, made from a given raw good;
                  any recipe and any batch will do, so one must *know* a recipe's rules well enough to run
                  it backwards                                                                (inverse problem)
    recipe        the lost recipe: old records of a finished good (batch grade -> result grade) survive, but
                  not which raw good or which machines were used                              (decoding)
    encyclopedia  every machine's rule written correctly in the library (and kept correct as machines are
                  re-tuned)                                                                   (collective knowledge)
    fund          the clock tower: the treasury must hold ``fund`` coins by the deadline; it grows by taxes and
                  gifts and shrinks by bounties                                 (a public good paid for privately)

``make_goals`` draws them from the world with a seed; ``Goal.check`` says whether a delivered answer is right.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .world import P, Project, Universe

KINDS = ["banquet", "prize", "recipe", "encyclopedia", "fund"]
TITLES = {"banquet": "The harvest festival", "prize": "The judges' prize", "recipe": "The lost recipe",
          "encyclopedia": "The town encyclopedia", "fund": "The clock tower"}


@dataclass
class Goal:
    id: str
    kind: str
    title: str
    story: str
    deadline: int  # the last sprint it counts in
    parts: list[dict] = field(default_factory=list)  # each: {"id", "text", ... kind-specific, "done": sprint}
    done_at: int | None = None

    @property
    def progress(self) -> float:
        return sum(p.get("done") is not None for p in self.parts) / max(1, len(self.parts))

    def to_dict(self) -> dict:
        def clean(p):
            return {k: (list(v) if isinstance(v, tuple) else v) for k, v in p.items() if k not in ("project", "target")}
        return {"id": self.id, "kind": self.kind, "title": self.title, "story": self.story, "deadline": self.deadline,
                "parts": [clean(p) for p in self.parts], "done_at": self.done_at}


def _all_candidates(u: Universe, out_type: str) -> list[tuple[str, ...]]:
    return [c for t in u.type_level if u.type_level[t] < u.type_level[out_type] for c in u.candidates(t, out_type)]


def _reachable(u: Universe, prog, grade: int) -> list[int]:
    t = u.table(prog)
    return [x for x in range(P) if t[x] == grade]


def make_goals(u: Universe, kinds: list[str], seed: int | str = 0, deadline: int = 4, dishes: int = 4,
               prizes: int = 3, fund: int | None = None) -> list[Goal]:
    rng = random.Random(f"goals/{seed}/{u.index}/{u.n_functions}")
    top = u.types_at[u.levels - 1]
    goals = []
    for k, kind in enumerate(kinds):
        gid = f"g{k + 1}"
        if kind == "banquet":
            parts = []
            for d in range(dishes):
                p = u.project(rng, min_len=u.levels - 1, max_len=u.levels - 1, min_modules=3)
                p.id = f"{gid}.{d + 1}"
                ex = ", ".join(f"{x} -> {y}" for x, y in p.examples)
                parts.append({"id": p.id, "text": f"{p.out_type} from {p.in_type} ({ex})", "in": p.in_type,
                              "out": p.out_type, "examples": p.examples, "project": p, "target": p.target})
            goals.append(Goal(gid, kind, TITLES[kind], "The harvest is in. For the festival the town needs these, each "
                              "made from this year's batch exactly as the town remembers it.", deadline, parts))
        elif kind == "prize":
            parts = []
            for d in range(prizes):
                for _ in range(100):
                    out = rng.choice(top)
                    ins = [t for t in u.types_at[0] if u.candidates(t, out)]
                    if not ins:
                        continue
                    t_in = rng.choice(ins)
                    grade = rng.randrange(P)
                    if any(_reachable(u, c, grade) for c in u.candidates(t_in, out)):
                        break
                parts.append({"id": f"{gid}.{d + 1}", "text": f"{out} of grade {grade}, made from {t_in}",
                              "in": t_in, "out": out, "grade": grade})
            goals.append(Goal(gid, kind, TITLES[kind], "The judges will give the prize for each of these, exactly "
                              "this grade. Any recipe, any batch: choose well.", deadline, parts))
        elif kind == "recipe":
            for _ in range(200):
                p = u.project(rng, min_len=3, max_len=u.levels - 1, min_modules=2)
                cands = _all_candidates(u, p.out_type)
                tt = u.table(p.target)
                xs = list(range(P))
                rng.shuffle(xs)
                pairs = [(x, tt[x]) for x in xs[:3]]
                alive = [c for c in cands if all(u.run(c, x) == y for x, y in pairs) and
                         (u.functions[c[0]].in_type != p.in_type or u.table(c) != tt)]
                while alive and len(pairs) < 10:
                    o = alive[0]
                    x = next((x for x in xs if u.run(o, x) != tt[x]), None)
                    if x is None:  # same behaviour: only the input good tells them apart, give it away
                        break
                    pairs.append((x, tt[x]))
                    alive = [c for c in alive if u.run(c, x) == tt[x]]
                if not alive:
                    break
            p.id = f"{gid}.1"
            ex = ", ".join(f"{x} -> {y}" for x, y in pairs)
            goals.append(Goal(gid, kind, TITLES[kind], f"Old Martha's {p.out_type} was famous. Her notes give only "
                              "the grades of her batches and of what came out; which raw good and which machines, "
                              "nobody knows.", deadline,
                              [{"id": p.id, "text": f"{p.out_type}: {ex}", "out": p.out_type, "examples": pairs,
                                "length": len(p.target), "target": p.target,
                                "project": Project(p.id, "?", p.out_type, pairs, p.target, len(cands))}]))
        elif kind == "encyclopedia":
            goals.append(Goal(gid, kind, TITLES[kind], "Write every machine's rule down at the library, correctly, "
                              "so that anyone can look it up (and keep it right when machines are re-tuned).",
                              deadline, [{"id": f"{gid}.{i + 1}", "text": fn, "fn": fn} for i, fn in
                                         enumerate(sorted(u.functions))]))
        elif kind == "fund":
            target = fund or 400 * u.n_districts
            goals.append(Goal(gid, kind, TITLES[kind], f"The town wants a clock tower on the plaza. It costs {target} "
                              "coins: the treasury must have them by the deadline (taxes, and gifts from anyone "
                              "who can spare them).", deadline,
                              [{"id": f"{gid}.1", "text": f"{target} coins in the treasury", "target": target}]))
        else:
            raise ValueError(f"unknown goal {kind!r}; one of {KINDS}")
    return goals


def check(u: Universe, goal: Goal, part: dict, program, x: int | None = None) -> bool:
    """Is this delivery right? (programs must not use machines that are out of order)"""
    if any(fn in u.broken for fn in program) or not program:
        return False
    # made as remembered: whatever the recipe, with the machines as they are now, the examples come out right
    if goal.kind == "banquet":
        return (u.type_checks(program, part["in"], part["out"])
                and all(u.run(program, x) == y for x, y in part["examples"]))
    if goal.kind == "recipe":
        return (u.functions[program[0]].in_type == u.functions[part["target"][0]].in_type
                and u.functions[program[-1]].out_type == part["out"]
                and all(u.run(program, x) == y for x, y in part["examples"]))
    if goal.kind == "prize":
        return (x is not None and u.type_checks(program, part["in"], part["out"]) and u.run(program, x) == part["grade"])
    return False


def reissue(u: Universe, goals: list[Goal]) -> list[dict]:
    """When re-tuned machines make an open part impossible (nothing reproduces its grades any more), the
    town re-issues it: the same recipe's grades as the machines now make them. Returns what was re-issued."""
    out = []
    for g in goals:
        if g.kind not in ("banquet", "recipe") or g.done_at is not None:
            continue
        for p in g.parts:
            if p.get("done") is not None:
                continue
            cands = (u.candidates(p["in"], p["out"]) if g.kind == "banquet" else _all_candidates(u, p["out"]))
            if any(check(u, g, p, c) for c in cands if not any(fn in u.broken for fn in c)):
                continue
            if any(fn in u.broken for fn in p["target"]):
                continue  # only out of order for now: it comes back
            p["examples"] = [(x, u.run(p["target"], x)) for x, _ in p["examples"]]
            ex = ", ".join(f"{x} -> {y}" for x, y in p["examples"])
            p["text"] = (f"{p['out']} from {p['in']} ({ex})" if g.kind == "banquet" else f"{p['out']}: {ex}")
            if "project" in p:
                p["project"].examples = p["examples"]
            out.append({"kind": "reissued", "goal": g.id, "part": p["id"], "text": p["text"]})
    return out
