"""CodeWorld: a procedurally generated software ecosystem with hidden behaviour.

A universe is a set of *modules* (auth, billing, geo, ...). Each module exposes functions with a public
signature (``billing.quote_price: Order -> Price``) and a hidden behaviour, its *law*. Values are integers
mod P. A law is either

    affine    f(x) = a*x + b                                     (mod P)
    branch    f(x) = a2*x + b2 if x % m == 0 else a*x + b        (an edge case: m in 2, 3, 5)

Types sit on levels and every function maps a type of level l to a type of level l+1, so a *program*
from type S to type G is a chain of functions of known length. Several functions, often in different
modules, share a signature, so many programs type-check but only one does what is wanted.

A *project* is a feature request: input type, output type and a few examples (x -> expected y), chosen so
that exactly one program among those that type-check (up to programs that compute the same thing) fits
them. Its target usually crosses several modules: building it means knowing how functions of several
modules behave. Running a function costs an action; so does studying a function to learn its law (probing
it on a fixed design of inputs). Knowing laws makes development cheap; the world can hold more laws than
one developer can keep in mind. Everything is scored exactly: every believed law, every program.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import cached_property

P = 101  # values are integers mod P
DESIGN = (0, 1, 2, 3, 4, 5, 6, 7)  # the inputs a careful developer probes to learn a law (covers every edge case)
BRANCH_MODS = (2, 3, 5)

MODULE_NAMES = ["auth", "billing", "geo", "search", "cache", "mail", "crypto", "ledger", "ranking", "media",
                "i18n", "metrics", "queue", "storage", "users", "orders", "inventory", "pricing", "shipping",
                "tax", "feeds", "chat", "maps", "payroll", "audit", "forms", "reports", "notify", "sessions",
                "catalog", "reviews", "ads"]
TYPE_NAMES = ["UserId", "Email", "Token", "Session", "Order", "Cart", "Price", "Invoice", "Region", "Address",
              "Route", "Score", "Rank", "Query", "Doc", "Hash", "Locale", "Text", "Report", "Event", "Metric",
              "Payload", "Message", "Receipt", "Shipment", "Rate", "Tax", "Ledger", "Review", "Ad", "Feed", "Plan"]
VERBS = ["to", "make", "get", "parse", "quote", "hash", "map", "lookup", "encode", "rank", "route", "sign",
         "resolve", "build", "check", "derive"]

# the town theme: modules are workshops (in districts of 8), types are goods, functions are machines
WORKSHOPS = ["bakery", "smithy", "florist", "mine", "clinic", "inn", "shop", "farm"]
DISTRICTS = ["oak", "river", "hill", "sea", "pine", "stone", "fern", "moss", "lake", "dune", "ash", "elm",
             "glen", "cove", "peak", "vale"]
GOODS = ["wheat", "ore", "petal", "herb", "milk", "clay", "wool", "fish", "flour", "ingot", "dye", "salve",
         "cheese", "brick", "yarn", "salt", "dough", "horseshoe", "ribbon", "tonic", "butter", "tile", "cloth",
         "jerky", "bread", "bell", "bouquet", "potion", "pie", "lamp", "coat", "stew", "feast", "carriage",
         "festoon", "elixir", "banquet", "tower", "tapestry", "voyage"]
TOWN_VERBS = ["knead", "bake", "forge", "smelt", "press", "dye", "weave", "brew", "grind", "polish", "mix",
              "cut", "boil", "carve", "spin", "cure"]
PER_DISTRICT = len(WORKSHOPS)


@dataclass(frozen=True)
class Law:
    kind: str  # "affine" | "branch"
    a: int
    b: int
    m: int = 0
    a2: int = 0
    b2: int = 0

    def __call__(self, x: int) -> int:
        if self.kind == "branch" and x % self.m == 0:
            return (self.a2 * x + self.b2) % P
        return (self.a * x + self.b) % P

    @cached_property
    def table(self) -> tuple[int, ...]:
        return tuple(self(x) for x in range(P))

    def describe(self) -> str:
        base = f"{self.a}*x + {self.b}"
        if self.kind == "branch":
            return f"{self.a2}*x + {self.b2} if x % {self.m} == 0 else {base} (mod {P})"
        return f"{base} (mod {P})"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "a": self.a, "b": self.b, "m": self.m, "a2": self.a2, "b2": self.b2}


@dataclass(frozen=True)
class Function:
    name: str  # module.verb_type
    module: str
    in_type: str
    out_type: str
    law: Law = field(repr=False, compare=False)

    @property
    def signature(self) -> str:
        return f"{self.name}: {self.in_type} -> {self.out_type}"


@dataclass
class Project:
    id: str
    in_type: str
    out_type: str
    examples: list[tuple[int, int]]
    target: tuple[str, ...]  # hidden: one correct program
    n_candidates: int  # programs that type-check

    @property
    def length(self) -> int:
        return len(self.target)

    def text(self) -> str:
        ex = ", ".join(f"{x} -> {y}" for x, y in self.examples)
        return (f"Project {self.id}: build a program {self.in_type} -> {self.out_type} (a chain of {self.length} "
                f"functions) such that {ex}.")


class Universe:
    """One software ecosystem: modules, functions with hidden laws, and a stream of projects."""

    def __init__(self, index: int = 0, n_modules: int = 8, fns_per_module: int = 4, levels: int = 5,
                 types_per_level: int = 2, branch_share: float = 0.3, popularity: float = 1.0,
                 theme: str = "software"):
        self.index, self.levels, self.theme = index, levels, theme
        rng = random.Random(f"codeworld/{index}/{n_modules}/{fns_per_module}/{levels}/{types_per_level}"
                            + ("" if theme == "software" else f"/{theme}"))
        town = theme == "town"
        if town:  # workshops grouped in districts of 8 (a single district keeps the plain names)
            names = [WORKSHOPS[i % PER_DISTRICT] if n_modules <= PER_DISTRICT else
                     f"{DISTRICTS[(i // PER_DISTRICT) % len(DISTRICTS)]}"
                     f"{'' if i // PER_DISTRICT < len(DISTRICTS) else i // PER_DISTRICT}_{WORKSHOPS[i % PER_DISTRICT]}"
                     for i in range(n_modules)]
            self.kind_of = {m: WORKSHOPS[i % PER_DISTRICT] for i, m in enumerate(names)}
            self.district_of = {m: i // PER_DISTRICT for i, m in enumerate(names)}
        else:
            names = [MODULE_NAMES[i % len(MODULE_NAMES)] + (str(i // len(MODULE_NAMES) + 1)
                                                            if i >= len(MODULE_NAMES) else "") for i in range(n_modules)]
            self.kind_of = {m: m for m in names}
            self.district_of = {m: 0 for m in names}
        self.modules = names
        self.map = None
        self.door: dict[str, tuple[int, int]] = {}
        self.tile: dict[str, tuple[int, int]] = {}
        if town:  # the street map: every workshop stands on a tile with its door on a road
            from .citymap import CityMap

            self.map = CityMap(max(self.district_of.values()) + 1)
            for i, m in enumerate(names):
                self.tile[m], self.door[m] = self.map.slot(self.district_of[m], i % PER_DISTRICT)
        pool, verbs = (GOODS, TOWN_VERBS) if town else (TYPE_NAMES, VERBS)
        tnames = [pool[i % len(pool)] + (str(i // len(pool) + 1) if i >= len(pool) else "")
                  for i in range(levels * types_per_level)]
        if not town:
            rng.shuffle(tnames)  # (town goods are listed raw materials first, so they keep their order)
        self.type_level = {t: i // types_per_level for i, t in enumerate(tnames)}
        self.types_at = {lv: [t for t in tnames if self.type_level[t] == lv] for lv in range(levels)}
        # module popularity: some modules are used far more than others (a long tail, like real code)
        self.weight = {m: 1.0 / (k + 1) ** popularity for k, m in enumerate(names)}
        self.functions: dict[str, Function] = {}
        for m in names:
            used = set()
            for _ in range(fns_per_module):
                lv = rng.randrange(levels - 1)
                t_in, t_out = rng.choice(self.types_at[lv]), rng.choice(self.types_at[lv + 1])
                base = f"{m}.{rng.choice(verbs)}_{t_out.lower()}"
                name, k = base, 2
                while name in self.functions or name in used:
                    name, k = f"{base}{k}", k + 1
                used.add(name)
                self.functions[name] = Function(name, m, t_in, t_out, self._law(rng, branch_share))
        self.out_of: dict[str, list[Function]] = {}
        for f in self.functions.values():
            self.out_of.setdefault(f.in_type, []).append(f)
        self._n_projects = 0

    @staticmethod
    def _law(rng: random.Random, branch_share: float) -> Law:
        a, b = rng.randrange(2, P), rng.randrange(P)
        if rng.random() < branch_share:
            a2 = rng.randrange(2, P)
            while a2 == a:
                a2 = rng.randrange(2, P)
            return Law("branch", a, b, rng.choice(BRANCH_MODS), a2, rng.randrange(P))
        return Law("affine", a, b)

    # ------------------------------------------------------------ programs
    def run(self, program, x: int) -> int:
        for name in program:
            x = self.functions[name].law(x)
        return x

    def table(self, program) -> tuple[int, ...]:
        t = tuple(range(P))
        for name in program:
            law = self.functions[name].law.table
            t = tuple(law[v] for v in t)
        return t

    def type_checks(self, program, in_type: str, out_type: str) -> bool:
        cur = in_type
        for name in program:
            f = self.functions.get(name)
            if f is None or f.in_type != cur:
                return False
            cur = f.out_type
        return cur == out_type

    def candidates(self, in_type: str, out_type: str, cap: int = 20000) -> list[tuple[str, ...]]:
        """Every program from in_type to out_type (they all have the same length: levels only go up)."""
        goal = self.type_level[out_type]
        out: list[tuple[str, ...]] = []

        def walk(t, path):
            if len(out) >= cap:
                return
            if t == out_type:
                out.append(tuple(path))
                return
            if self.type_level[t] >= goal:
                return
            for f in self.out_of.get(t, []):
                walk(f.out_type, path + [f.name])

        walk(in_type, [])
        return out

    # ------------------------------------------------------------ projects
    def project(self, rng: random.Random, min_len: int = 2, max_len: int = 4, min_modules: int = 2,
                tries: int = 200) -> Project:
        """A feature request whose examples single out one program (up to equivalent programs)."""
        for _ in range(tries):
            length = rng.randint(min_len, max_len)
            lv = rng.randrange(0, self.levels - length) if self.levels - length > 0 else 0
            t = rng.choice(self.types_at[lv])
            path = []
            for _ in range(length):
                opts = self.out_of.get(t, [])
                if not opts:
                    break
                f = rng.choices(opts, [self.weight[o.module] for o in opts])[0]
                path.append(f.name)
                t = f.out_type
            if len(path) < length or len({self.functions[n].module for n in path}) < min_modules:
                continue
            target = tuple(path)
            in_type = self.functions[target[0]].in_type
            cands = self.candidates(in_type, t)
            tt = self.table(target)
            others = {self.table(c) for c in cands} - {tt}
            examples: list[tuple[int, int]] = []
            xs = list(range(P))
            rng.shuffle(xs)
            for x in xs[:2]:
                examples.append((x, tt[x]))
            # add examples until no other behaviour fits them (edge cases included when they matter)
            alive = {o for o in others if all(o[x] == y for x, y in examples)}
            while alive and len(examples) < 8:
                o = next(iter(alive))
                x = next(x for x in xs if o[x] != tt[x])
                examples.append((x, tt[x]))
                alive = {o for o in alive if o[x] == tt[x]}
            if alive:
                continue
            self._n_projects += 1
            return Project(f"p{self._n_projects}", in_type, t, examples, target, len(cands))
        raise RuntimeError("could not generate a project; make the universe bigger")

    # ------------------------------------------------------------ text
    def signatures_text(self, modules=None) -> str:
        lines = []
        for m in modules or self.modules:
            fs = [f for f in self.functions.values() if f.module == m]
            lines.append(f"{m}: " + "; ".join(f"{f.name}: {f.in_type} -> {f.out_type}" for f in fs))
        return "\n".join(lines)

    @property
    def n_functions(self) -> int:
        return len(self.functions)

    @property
    def n_districts(self) -> int:
        return max(self.district_of.values()) + 1

    def where(self, place: str | None) -> tuple[int, int]:
        """The road tile one stands on at a place (a workshop's door; None is the plaza)."""
        return self.door[place] if place else self.map.plaza

    def route(self, a: str | None, b: str | None) -> tuple[tuple[int, int], ...]:
        """The shortest walk along the roads between two places (town theme)."""
        return self.map.route(self.where(a), self.where(b))

    def distance(self, a: str | None, b: str | None) -> int:
        """Walking cost between two places (workshops, or None for the plaza): in the town, one action per
        block of road on the shortest route; without a map, 1 between any two places. The same place is 0."""
        if a == b:
            return 0
        if self.map is None:
            return 1
        return self.map.cost(len(self.route(a, b)) - 1)

    def layout(self) -> dict:
        """Districts, workshops and machines (public), for the pixel client."""
        out = []
        for d in range(self.n_districts):
            mods = [m for m in self.modules if self.district_of[m] == d]
            out.append({"index": d, "name": DISTRICTS[d % len(DISTRICTS)] if self.n_districts > 1 else "town",
                        "workshops": [{"module": m, "kind": self.kind_of[m], "machines": [
                            {"name": f.name, "in": f.in_type, "out": f.out_type}
                            for f in self.functions.values() if f.module == m],
                            **({"tile": list(self.tile[m]), "door": list(self.door[m])} if self.map else {})}
                            for m in mods]})
        return {"theme": self.theme, "districts": out, "levels": [self.types_at[lv] for lv in range(self.levels)],
                "map": self.map.to_dict() if self.map else None}
