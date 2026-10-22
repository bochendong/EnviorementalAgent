"""DAG: a problem whose work and span are known exactly and cannot be shortcut by reasoning.

``depth`` layers of ``width`` tasks and a final task. Every task has a function of its own, hidden: f_T(x)
is a keyed hash of the task and x, a number from 0 to 999, and the only way to learn it is the ``apply``
operation (one action per value). A task starts from a number (layer 0: given; later: the sum of the
answers of ``fanin`` tasks of the layer before, mod 1000; the final task: the sum of the whole last layer)
and applies its function ``grain`` times in a row, x <- f_T(x); the answer is the last x, handed in as a
bare integer and checked exactly.

Each task's function is keyed so that its own chain repeats no value: no f(x) seen earlier in the chain can
stand in for an apply (a development audit found a grain-4 chain with a repeat, solved in 324 actions
against 325; results/net/runs/20261022-codex-dag-pilot-02/development-bound-audit.json). So no agent,
however strong, can do a task in fewer than ``grain`` applies and one submission, nor start it before its
parents' answers are known: one agent needs at least W = tasks * (grain + 1) actions, and a team
of N at least max(W / N, D) rounds, D = (depth + 1) * (grain + 1) (Brent). ``grain`` sets how much
computation a task holds against what sharing its answer costs (one message or store write, and reads).

The math provider's ``dag`` option (worldseeds/net/providers/math.py gen_dag) was the first version: its
recurrences could be handed in as closed-form expressions without any tool, and a strong model nested the
whole DAG into one expression, so neither work nor span held (results/net/runs/20261022-codex-netscale-
pilot-01).
"""

from __future__ import annotations

import hashlib
import random

from ..core import OpSpec, Role, Score, Task, TaskProvider

MOD = 1000


def hidden(seed: int, tid: str, x: int, salt: int = 0) -> int:
    """f_T(x): a keyed hash, 0..999."""
    h = hashlib.blake2b(f"worldseeds-dag/{seed}/{tid}/{salt}/{x % MOD}".encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") % MOD


def chain(seed: int, tid: str, start: int, grain: int) -> tuple[int, list[int]]:
    """The task's function, keyed so that its chain x0, x1, ..., x_grain repeats no value (otherwise an agent
    could reuse an f(x) it has seen and skip an apply): (salt, chain)."""
    for salt in range(10 ** 4):
        xs = [start]
        for _ in range(grain):
            xs.append(hidden(seed, tid, xs[-1], salt))
        if len(set(xs)) == len(xs):
            return salt, xs
    raise RuntimeError(f"no salt gives {tid} a chain without repeats")


def gen(seed: int, width: int, depth: int, fanin: int = 2, grain: int = 1) -> list[dict]:
    rng = random.Random(f"dag/{seed}")
    out: list[dict] = []
    answers: dict[str, int] = {}

    def task(tid, layer, deps, start, start_text):
        salt, xs = chain(seed, tid, start, grain)
        x = answers[tid] = xs[-1]
        times = "once" if grain == 1 else f"{grain} times in a row"
        out.append({"id": tid, "layer": layer, "deps": deps, "start": start, "answer": str(x), "salt": salt,
                    "text": f"Start from x = {start_text}. Apply {tid}'s function {times} (x <- f(x), with the "
                            f"'apply' operation); the answer is the last x, a whole number from 0 to {MOD - 1}."})

    for lv in range(depth):
        for i in range(width):
            tid = f"L{lv}.{i}"
            if lv == 0:
                s = rng.randrange(MOD)
                task(tid, lv, [], s, str(s))
            else:
                deps = [f"L{lv - 1}.{j}" for j in sorted(rng.sample(range(width), min(fanin, width)))]
                task(tid, lv, deps, sum(answers[d] for d in deps) % MOD,
                     "the sum of the answers of " + ", ".join(deps) + f", mod {MOD}")
    last = [f"L{depth - 1}.{i}" for i in range(width)]
    task("FINAL", depth, last, sum(answers[d] for d in last) % MOD,
         "the sum of the answers of " + ", ".join(last) + f", mod {MOD}")
    out[-1]["final"] = True
    return out


class DagProvider(TaskProvider):
    name = "dag"

    def __init__(self, width: int = 16, depth: int = 4, fanin: int = 2, grain: int = 1, agents: int = 4):
        self.width, self.depth, self.fanin, self.grain, self.agents = width, depth, fanin, grain, agents

    def reset(self, seed: int = 0) -> dict:
        self.seed = seed
        self.raw = {t["id"]: t for t in gen(seed, self.width, self.depth, self.fanin, self.grain)}
        return {"world": "dag", "problem": f"{len(self.raw)} tasks: {self.depth} layers of {self.width} and a final "
                                          "task; each task has a hidden function of its own",
                "answers": "bare whole numbers"}

    def roles(self) -> list[Role]:
        return [Role("worker", "Can apply any task's function.", count=self.agents)]

    def ops(self) -> list[OpSpec]:
        return [OpSpec("apply", "Apply a task's hidden function once: returns f(x) for that task. x is a whole number "
                                f"(taken mod {MOD}), or a list of whole numbers to add up first.",
                       {"task": {"type": "string"}, "x": {"description": "a whole number, or a list of them to add",
                                                          "anyOf": [{"type": "integer"},
                                                                    {"type": "array", "items": {"type": "integer"}}]}},
                       ("task", "x"))]

    def apply(self, agent: str, role: Role, op: str, args: dict) -> dict:
        tid, x = args.get("task"), args.get("x")
        if tid not in self.raw:
            return {"error": f"no task {tid!r}"}
        try:
            xs = [int(v) for v in (x if isinstance(x, list) else [x])]
        except (TypeError, ValueError):
            return {"error": "x must be a whole number or a list of whole numbers"}
        v = sum(xs) % MOD
        return {"task": tid, "x": v, "f(x)": hidden(self.seed, tid, v, self.raw[tid]["salt"])}

    def tasks(self) -> list[Task]:
        return [Task(t["id"], t["text"], "answer", tuple(t["deps"]), 4.0 if t.get("final") else 1.0, {},
                     bool(t.get("final"))) for t in self.raw.values()]

    def verify(self, task: Task, artifact, agent: str) -> Score:
        text = str(artifact).strip()
        if not text.lstrip("-").isdigit():
            return Score(False, 0.0, {"error": "hand in a bare whole number, e.g. 417"})
        ok = int(text) == int(self.raw[task.id]["answer"])
        return Score(ok, float(ok), {} if ok else {"error": "not the answer"})

    def summary(self) -> dict:
        return {"problem_tasks": len(self.raw), "grain": self.grain}
