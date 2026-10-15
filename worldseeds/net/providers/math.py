"""Mathematics as a task provider: a problem cut into lemmas, checked by SymPy.

A problem is a DAG of tasks. Each task asks for an *answer* (a number or a closed form in some variables)
and opens once the tasks it depends on are done; the final task is the problem itself. Answers are
checked symbolically (``simplify(answer - truth) == 0``) after a quick numeric screen. Tasks of kind
``lean`` take Lean 4 source and are checked by the ``lean`` executable when one is installed.

Roles split the tools, so the work must be shared:

    explorer    evaluate, sequence      numbers: compute values, tabulate a sequence, spot patterns
    algebraist  simplify, solve, rsolve symbols: rewrite, solve equations, solve recurrences

Problems come from seeded generators (``recurrence``, ``sum``, any number of each, joined by a final
``combine`` task; with ``linked=True``, recurrences in one chain, each starting from the previous one's
answer) or from your own JSON file:

    {"title": "...", "tasks": [
        {"id": "L1", "text": "...", "answer": "n*(n+1)/2", "vars": ["n"]},
        {"id": "T", "text": "...", "answer": "5050", "deps": ["L1"], "final": true, "reward": 3}]}

Expressions are parsed with a whitelist of SymPy names; attribute access and underscores are refused.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from contextlib import contextmanager

import sympy as sp
from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application, parse_expr,
                                        standard_transformations)

from ..core import OpSpec, Role, Score, Task, TaskProvider

NAMES = {k: getattr(sp, k) for k in (
    "Rational", "Integer", "sqrt", "exp", "log", "sin", "cos", "tan", "pi", "E", "I", "oo", "factorial",
    "binomial", "gcd", "lcm", "Mod", "floor", "ceiling", "Abs", "Sum", "Product", "Function", "Eq", "Symbol",
    "symbols", "isprime", "prime", "totient", "divisors", "factorint", "fibonacci", "harmonic", "Max", "Min",
    "Piecewise", "Matrix")}
TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
MAX_LEN = 500


class MathError(ValueError):
    pass


@contextmanager
def time_limit(seconds: float):
    """A SIGALRM time limit (only in the main thread; elsewhere no limit)."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def boom(*_):
        raise MathError(f"took longer than {seconds}s")

    old = signal.signal(signal.SIGALRM, boom)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def parse(s, extra: dict | None = None):
    if not isinstance(s, (str, int, float)):
        raise MathError("an expression must be a string")
    s = str(s)
    if len(s) > MAX_LEN:
        raise MathError(f"expression longer than {MAX_LEN} characters")
    if "_" in s or re.search(r"[A-Za-z)\]]\s*\.", s) or any(c in s for c in "\\;'\"`@$"):
        raise MathError("attribute access, underscores and quotes are not allowed")
    loc = {**NAMES, **(extra or {})}
    for name in set(re.findall(r"[A-Za-z]+", s)) - set(loc):
        loc[name] = sp.Symbol(name)  # unknown names are symbols (n, k, x, a ...)
    try:
        e = parse_expr(s, local_dict=loc, global_dict={"__builtins__": {}, **{k: getattr(sp, k) for k in (
            "Integer", "Float", "Rational", "Symbol")}}, transformations=TRANSFORMS)
    except Exception as e:  # noqa: BLE001 (SymPy raises many kinds)
        raise MathError(f"cannot parse {s!r}: {type(e).__name__}") from None
    if isinstance(e, (int, float)):
        e = sp.sympify(e)
    if not isinstance(e, sp.Basic):
        raise MathError(f"{s!r} is not a mathematical expression")
    return e


def same(answer, truth, vars_=()) -> bool:
    a, t = parse(answer), parse(truth)
    syms = [sp.Symbol(v) for v in vars_]
    for k in range(0, 13):  # quick numeric screen
        sub = {x: k + 1 + i for i, x in enumerate(syms)}
        try:
            d = sp.N((a - t).subs(sub).doit(), 30)
            if not d.is_number or abs(d) > 1e-20:
                return False
        except (TypeError, ValueError, AttributeError):
            return False
        if not syms:
            break
    return sp.simplify(a - t) == 0


# ------------------------------------------------------------------ generators
def gen_recurrence(rng: random.Random, tag: str, after: dict | None = None) -> list[dict]:
    """``after``: a task whose answer sets a(0) (its answer mod 10), so this problem waits for that one."""
    p, q, r = rng.randint(2, 5), rng.randint(1, 9), rng.randint(0, 9)
    if after is not None:
        r = int(after["answer"]) % 10
    n = sp.Symbol("n")
    closed = sp.simplify((r + sp.Rational(q, p - 1)) * p ** n - sp.Rational(q, p - 1))
    a = lambda k: closed.subs(n, k)  # noqa: E731
    N, M = rng.choice([1000, 2024, 5000]), rng.choice([1009, 997, 10007])
    seq = f"a(0) = {r}, a(n+1) = {p}*a(n) + {q}"
    if after is not None:
        seq = f"a(0) = (the answer of {after['id']}) mod 10, a(n+1) = {p}*a(n) + {q}"
    return [
        {"id": f"{tag}.L1", "text": f"For the sequence {seq}: what is a(6)?", "answer": str(a(6)),
         "hint": "Tabulate the sequence with 'sequence' (a recurrence and its initial value) and read off a(6).",
         **({"deps": [after["id"]]} if after is not None else {})},
        {"id": f"{tag}.L2", "text": f"For the sequence {seq}: give a closed form for a(n) in terms of n.",
         "answer": str(closed), "vars": ["n"], "deps": [f"{tag}.L1"], "reward": 2,
         "hint": "Solve the recurrence with 'rsolve' and its initial value; check it against a(6)."},
        {"id": f"{tag}.T", "text": f"For the sequence {seq}: what is a({N}) mod {M}?",
         "answer": str(int(a(N)) % M), "deps": [f"{tag}.L2"], "reward": 3, "final_of": tag,
         "hint": "Evaluate Mod(closed form with n set, M) with 'evaluate'; SymPy handles the big power."},
    ]


def gen_sum(rng: random.Random, tag: str) -> list[dict]:
    a, b, c = rng.randint(1, 6), rng.randint(0, 9), rng.randint(0, 9)
    n, k = sp.symbols("n k")
    term = a * k ** 2 + b * k + c
    S = sp.factor(sp.summation(term, (k, 1, n)))
    T = rng.choice([10 ** 5, 10 ** 6, 3 * 10 ** 6])
    first = next(m for m in range(1, 10 ** 6) if S.subs(n, m) > T)
    desc = f"S(n) = sum of ({a}*k^2 + {b}*k + {c}) for k = 1..n"
    return [
        {"id": f"{tag}.L1", "text": f"Let {desc}. What is S(10)?", "answer": str(S.subs(n, 10)),
         "hint": "Evaluate Sum(term, (k, 1, 10)) with 'evaluate'."},
        {"id": f"{tag}.L2", "text": f"Let {desc}. Give S(n) as a polynomial in n.", "answer": str(S),
         "vars": ["n"], "deps": [f"{tag}.L1"], "reward": 2,
         "hint": "Sum(term, (k, 1, n)) with 'evaluate' or 'simplify' gives S(n); check it against S(10)."},
        {"id": f"{tag}.T", "text": f"Let {desc}. What is the smallest n with S(n) > {T}?", "answer": str(first),
         "deps": [f"{tag}.L2"], "reward": 3, "final_of": tag,
         "hint": f"Estimate n from the leading term of S(n), then tabulate S(n) around it with 'sequence' "
                 f"and take the first n where it exceeds {T}."},
    ]


GENERATORS = {"recurrence": gen_recurrence, "sum": gen_sum}


class MathProvider(TaskProvider):
    name = "math"

    def __init__(self, problems: tuple[str, ...] | list[str] = ("recurrence", "sum"), problem_file: str = "",
                 explorers: int = 2, algebraists: int = 1, timeout: float = 3.0, free_roles: bool = False,
                 linked: bool = False):
        self.kinds, self.problem_file, self.linked = list(problems), problem_file, linked
        if linked and set(self.kinds) != {"recurrence"}:
            raise ValueError("linked problems are recurrences only")
        self.explorers, self.algebraists, self.timeout, self.free = explorers, algebraists, timeout, free_roles

    def reset(self, seed: int = 0) -> dict:
        if self.problem_file:
            with open(self.problem_file) as f:
                data = json.load(f)
            title, raw = data.get("title", self.problem_file), data["tasks"]
            if not any(t.get("final") for t in raw):
                raw[-1]["final"] = True
        else:
            rng = random.Random(f"math/{seed}")
            raw = []
            for i, kind in enumerate(self.kinds):
                if self.linked and i:  # one chain: each problem starts from the previous problem's answer
                    raw += gen_recurrence(rng, f"P{i + 1}", after=raw[-1])
                else:
                    raw += GENERATORS[kind](rng, f"P{i + 1}")
            finals = [t for t in raw if t.get("final_of")]
            if self.linked:
                finals[-1]["final"] = True
            elif len(finals) > 1:
                total = sum(int(t["answer"]) for t in finals)
                raw.append({"id": "FINAL", "text": "Add up the answers of " + ", ".join(t["id"] for t in finals)
                            + ".", "answer": str(total), "deps": [t["id"] for t in finals], "reward": 4,
                            "final": True})
            else:
                finals[0]["final"] = True
            title = (" -> " if self.linked else " + ").join(self.kinds)
        self.raw = {t["id"]: t for t in raw}
        return {"world": "math", "problem": title, "tasks": len(raw), "answers": "SymPy expressions (strings)"}

    def roles(self) -> list[Role]:
        if self.free:
            return [Role("mathematician", "Has every tool.", count=self.explorers + self.algebraists)]
        return [Role("explorer", "Works with numbers: evaluate expressions and tabulate sequences.",
                     ("evaluate", "sequence"), self.explorers),
                Role("algebraist", "Works with symbols: simplify, solve equations and recurrences.",
                     ("simplify", "solve", "rsolve"), self.algebraists)]

    def ops(self) -> list[OpSpec]:
        S, I = {"type": "string"}, {"type": "integer"}
        return [
            OpSpec("evaluate", "Evaluate an expression exactly, optionally substituting values: "
                               "evaluate('3^20 mod 7') is evaluate('Mod(3**20, 7)').",
                   {"expr": S, "subs": {"type": "object", "description": "e.g. {\"n\": 10}"}}, ("expr",)),
            OpSpec("sequence", "Tabulate expr for var = start .. start+count-1 (count <= 40). For a recurrence "
                               "give 'rec' instead: a(n+1) in terms of a(n) and n, with init a(start).",
                   {"expr": S, "var": S, "start": I, "count": I, "rec": S, "init": S}, ("count",)),
            OpSpec("simplify", "Rewrite an expression: how = simplify | expand | factor | together | apart.",
                   {"expr": S, "how": S}, ("expr",)),
            OpSpec("solve", "Solve an equation 'lhs = rhs' (or expr = 0) for a variable.", {"equation": S, "var": S},
                   ("equation", "var"), cost=2),
            OpSpec("rsolve", "Solve a recurrence 'a(n+1) = 3*a(n) + 2' with init {\"0\": 1} for a(n).",
                   {"recurrence": S, "init": {"type": "object"}}, ("recurrence",), cost=3),
        ]

    def apply(self, agent: str, role: Role, op: str, args: dict) -> dict:
        try:
            with time_limit(self.timeout):
                return getattr(self, f"_{op}")(**args)
        except MathError as e:
            return {"error": str(e)}

    def _evaluate(self, expr: str, subs: dict | None = None) -> dict:
        e = parse(expr)
        if subs:
            e = e.subs({sp.Symbol(k): parse(v) for k, v in subs.items()})
        v = sp.simplify(e.doit())
        return {"value": str(v), **({"approx": str(sp.N(v, 15))} if not v.is_Integer and v.is_number else {})}

    def _sequence(self, count: int, expr: str = "", var: str = "n", start: int = 0, rec: str = "",
                  init: str = "0") -> dict:
        count = max(1, min(int(count), 40))
        if rec:
            a = sp.Function("a")
            n = sp.Symbol("n")
            body = parse(rec, {"a": a})
            vals, cur = [], parse(init)
            for i in range(start, start + count):
                vals.append(str(cur))
                cur = sp.simplify(body.replace(lambda x: isinstance(x, sp.core.function.AppliedUndef), lambda x: cur)
                                  .subs(n, i))
            return {"values": vals}
        e, v = parse(expr), sp.Symbol(var)
        return {"values": [str(sp.simplify(e.subs(v, i).doit())) for i in range(start, start + count)]}

    def _simplify(self, expr: str, how: str = "simplify") -> dict:
        f = {"simplify": sp.simplify, "expand": sp.expand, "factor": sp.factor, "together": sp.together,
             "apart": sp.apart}.get(how)
        if f is None:
            return {"error": f"unknown how={how!r}"}
        return {"result": str(f(parse(expr).doit()))}

    def _solve(self, equation: str, var: str) -> dict:
        lhs, _, rhs = equation.partition("=")
        e = parse(lhs) - (parse(rhs) if rhs else 0)
        return {"solutions": [str(s) for s in sp.solve(e, sp.Symbol(var))]}

    def _rsolve(self, recurrence: str, init: dict | None = None) -> dict:
        a, n = sp.Function("a"), sp.Symbol("n")
        lhs, _, rhs = recurrence.partition("=")
        eq = parse(lhs, {"a": a}) - (parse(rhs, {"a": a}) if rhs else 0)
        ic = {a(int(k)): parse(v) for k, v in (init or {}).items()}
        sol = sp.rsolve(eq, a(n), ic or None)
        return {"a(n)": str(sp.simplify(sol)) if sol is not None else None}

    def tasks(self) -> list[Task]:
        return [Task(t["id"], t["text"], t.get("kind", "answer"), tuple(t.get("deps", ())), t.get("reward", 1.0),
                     {"vars": t.get("vars", []), **({"hint": t["hint"]} if t.get("hint") else {})},
                     bool(t.get("final"))) for t in self.raw.values()]

    def verify(self, task: Task, artifact, agent: str) -> Score:
        t = self.raw[task.id]
        if t.get("kind") == "lean":
            return lean_check(str(artifact or ""), t.get("theorem", ""), self.timeout * 20)
        try:
            with time_limit(self.timeout):
                ok = same(str(artifact), t["answer"], t.get("vars", ()))
        except MathError as e:
            return Score(False, 0.0, {"error": str(e)})
        return Score(ok, 1.0 if ok else 0.0, {} if ok else {"error": "not equal to the answer"})

    def summary(self) -> dict:
        return {"problem_tasks": len(self.raw)}


def lean_check(source: str, theorem: str, timeout: float) -> Score:
    lean = shutil.which("lean")
    if lean is None:
        return Score(False, 0.0, {"error": "no lean executable on this machine"})
    if theorem and theorem not in source:
        return Score(False, 0.0, {"error": "the source must contain the theorem statement unchanged"})
    if "sorry" in source or "admit" in source:
        return Score(False, 0.0, {"error": "sorry/admit are not proofs"})
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as f:
        f.write(source)
    try:
        r = subprocess.run([lean, f.name], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Score(False, 0.0, {"error": "lean timed out"})
    ok = r.returncode == 0
    return Score(ok, float(ok), {} if ok else {"error": (r.stdout + r.stderr)[-1500:]})
