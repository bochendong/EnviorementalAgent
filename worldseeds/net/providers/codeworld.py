"""CodeWorld as a task provider: the synthetic twin of real work.

Functions with hidden laws, projects that ask for a chain of functions fitting some examples (see
``worldseeds/codeworld/world.py``). Running a function costs 1, studying one (learning its law) costs
``study_cost``. With ``owners=True`` every module has its own owner role and only owners can study their
module's functions: knowledge is spread and must travel through the network. ``drift`` re-tunes a
function's law with that chance per round. ``theme="town"`` is the same world as the town of
web/codeworld.html (workshops and machines, ``districts`` of 8 workshops with ``fns_per_module`` machines
each), so a run can be watched there (worldseeds/net/replay.py).

The load knob (the "load" suite): ``n_modules`` sets how much there is to master, while ``project_len``
fixes every project's chain length and ``n_projects`` the number of projects, so the work asked for stays
the same and only the world it must be found in grows. ``owner_groups=k`` splits the modules into k
owners (round robin): with 12 modules and 4 owners each owns 3; nobody else can study them.
"""

from __future__ import annotations

import random
from dataclasses import replace

from ...codeworld.world import Universe, town_world
from ..core import OpSpec, Role, Score, Task, TaskProvider


class CodeWorldProvider(TaskProvider):
    name = "codeworld"

    def __init__(self, n_modules: int = 4, fns_per_module: int = 4, levels: int = 5, n_projects: int = 6,
                 devs: int = 3, owners: bool = False, study_cost: int = 8, drift: float = 0.0, universe: int = 0,
                 theme: str = "software", districts: int = 1, project_len: int = 0, owner_groups: int = 0):
        self.opt = dict(n_modules=n_modules, fns_per_module=fns_per_module, levels=levels)
        self.theme, self.districts = theme, districts
        self.n_projects, self.devs, self.owners = n_projects, devs, owners
        self.study_cost, self.drift, self.universe = study_cost, drift, universe
        self.project_len, self.owner_groups = project_len, owner_groups

    def reset(self, seed: int = 0) -> dict:
        if self.theme == "town":
            self.u = town_world(self.universe, self.districts, self.opt["fns_per_module"])
        else:
            self.u = Universe(index=self.universe, **self.opt)
        self.rng = random.Random(f"cw-net/{seed}")
        self.projects = {}
        for _ in range(self.n_projects):
            p = self.u.project(self.rng, min_len=self.project_len, max_len=self.project_len) if self.project_len \
                else self.u.project(self.rng)
            self.projects[p.id] = p
        return {"world": "codeworld", "theme": self.theme, "modules": self.u.modules, "functions": len(self.u.functions),
                "values": "integers mod 101", "projects": len(self.projects)}

    def roles(self) -> list[Role]:
        if not self.owners:
            return [Role("dev", "A developer: runs and studies any function, builds programs.", count=self.devs)]
        if self.owner_groups:
            k = self.owner_groups
            groups = [self.u.modules[i::k] for i in range(k)]
            return [Role(f"owner_{i}", f"Owner of modules {', '.join(g)}: the only one who can study their functions.",
                         scope={"modules": list(g)}) for i, g in enumerate(groups) if g]
        return [Role(f"owner_{m}", f"Owner of module {m}: the only one who can study its functions.",
                     scope={"modules": [m]}) for m in self.u.modules]

    def ops(self) -> list[OpSpec]:
        S = {"type": "string"}
        return [
            OpSpec("signatures", "List functions and their types (optionally of one module).",
                   {"module": {**S, "description": "module name (optional)"}}),
            OpSpec("run", "Run a program (a chain of function names) on an input x in 0..100.",
                   {"program": {"type": "array", "items": S}, "x": {"type": "integer"}}, ("program", "x")),
            OpSpec("study", "Learn the exact law of one function.", {"function": S}, ("function",),
                   cost=self.study_cost),
        ]

    def artifact_schema(self) -> dict:
        return {"type": "array", "items": {"type": "string"}}

    def apply(self, agent: str, role: Role, op: str, args: dict) -> dict:
        u = self.u
        if op == "signatures":
            mod = args.get("module", "")
            return {"functions": [f.signature for f in u.functions.values() if not mod or f.module == mod]}
        if op == "run":
            prog, x = list(args["program"]), int(args["x"])
            bad = [n for n in prog if n not in u.functions]
            if bad:
                return {"error": f"unknown functions {bad}"}
            for a, b in zip(prog, prog[1:]):
                if u.functions[a].out_type != u.functions[b].in_type:
                    return {"error": f"{a} gives {u.functions[a].out_type}, {b} takes {u.functions[b].in_type}"}
            return {"y": u.run(prog, x % 101)}
        if op == "study":
            fn = args["function"]
            if fn not in u.functions:
                return {"error": f"unknown function {fn!r}"}
            mods = role.scope.get("modules")
            if mods is not None and u.functions[fn].module not in mods:
                return {"error": f"only the owner of {u.functions[fn].module} can study it"}
            return {"function": fn, "law": u.functions[fn].law.describe()}
        return {"error": f"unknown op {op}"}

    def tasks(self) -> list[Task]:
        return [Task(p.id, p.text(), "program", reward=1.0,
                     spec={"in": p.in_type, "out": p.out_type, "length": p.length, "examples": p.examples,
                           "hint": f"Find {p.length} functions that chain from {p.in_type} to {p.out_type} "
                                   "('signatures'), learn what each does ('study', or ask whoever studied it), "
                                   "then 'run' your chain on the examples before you submit it."})
                for p in self.projects.values()]

    def verify(self, task: Task, artifact, agent: str) -> Score:
        p = self.projects[task.id]
        prog = tuple(artifact or ())
        if not self.u.type_checks(prog, p.in_type, p.out_type):
            return Score(False, 0.0, {"error": "the program does not type-check"})
        if self.u.table(prog) != self.u.table(p.target):
            bad = [(x, y) for x, y in p.examples if self.u.run(prog, x) != y]
            return Score(False, 0.0, {"error": "wrong behaviour" + (f" on example {bad[0]}" if bad else "")})
        return Score(True, 1.0)

    def tick(self, round: int) -> list[dict]:
        out = []
        if self.drift:
            for fn in sorted(self.u.functions):
                if self.rng.random() < self.drift:
                    f = self.u.functions[fn]
                    self.u.functions[fn] = replace(f, law=Universe._law(self.rng, .3))
                    out.append({"kind": "drift", "fn": fn, "old": f.law.describe(),
                                "new": self.u.functions[fn].law.describe()})
        return out

    def summary(self) -> dict:
        """The load: how big the world is, and how many programs fit each project's types (what must be
        searched) and how many distinct functions the projects need (what must be known)."""
        cands = [len(self.u.candidates(p.in_type, p.out_type)) for p in self.projects.values()]
        return {"modules": len(self.u.modules), "functions": len(self.u.functions),
                "candidates_per_project": round(sum(cands) / max(1, len(cands)), 1),
                "distinct_functions_needed": len({f for p in self.projects.values() for f in p.target})}
