"""What a developer knows: laws of functions, learned by probing, held in a notebook of limited capacity."""

from __future__ import annotations

from collections import OrderedDict

from .world import BRANCH_MODS, DESIGN, P, Law


def _affine(points) -> Law | None:
    pts = list(points)
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            (x1, y1), (x2, y2) = pts[i], pts[j]
            if x1 != x2:
                a = (y2 - y1) * pow(x2 - x1, -1, P) % P
                law = Law("affine", a, (y1 - a * x1) % P)
                return law if all(law(x) == y for x, y in pts) else None
    return None


def fit(points: dict[int, int]) -> Law | None:
    """The law behind observed (x -> y) points, if they pin one down; None if they do not (yet).

    Affine needs three points that agree. A branch needs, for some m in 2, 3, 5, two agreeing points on
    each side of the edge case (multiples of m or not) and no affine law fitting everything. Points that
    never touch an edge case can look affine: a law learned from such points may be wrong (like code that
    passes the visible tests)."""
    pts = sorted(points.items())
    if len(pts) < 3:
        return None
    law = _affine(pts)
    if law is not None:
        return law
    for m in BRANCH_MODS:
        edge = [(x, y) for x, y in pts if x % m == 0]
        rest = [(x, y) for x, y in pts if x % m != 0]
        if len(edge) < 2 or len(rest) < 2:
            continue
        a, b = _affine(edge), _affine(rest)
        if a is not None and b is not None:
            return Law("branch", b.a, b.b, m, a.a, a.b)
    return None


def study_inputs() -> tuple[int, ...]:
    """The inputs a careful developer probes to learn a law: every edge case of every branch is covered."""
    return DESIGN


class Notebook:
    """Laws a developer keeps in mind, at most ``capacity`` (None = unbounded); least recently used go first."""

    def __init__(self, capacity: int | None = None, keep=None):
        self.capacity = capacity
        # keep(name) -> True for laws to forget last (a specialist keeps its own modules' laws)
        self.keep = keep
        self.laws: OrderedDict[str, Law] = OrderedDict()
        self.ever: set[str] = set()  # every function this notebook has held (to count re-learning)
        self.evictions = 0
        self.relearned = 0

    def __contains__(self, name: str) -> bool:
        return name in self.laws

    def __len__(self) -> int:
        return len(self.laws)

    def get(self, name: str) -> Law | None:
        law = self.laws.get(name)
        if law is not None:
            self.laws.move_to_end(name)
        return law

    def put(self, name: str, law: Law) -> list[str]:
        """Keep a law; returns the names forgotten to make room."""
        if name in self.ever and name not in self.laws:
            self.relearned += 1
        self.ever.add(name)
        self.laws[name] = law
        self.laws.move_to_end(name)
        gone = []
        while self.capacity is not None and len(self.laws) > self.capacity:
            old = next((n for n in self.laws if not (self.keep and self.keep(n))), None)
            if old is None:
                old = next(iter(self.laws))
            del self.laws[old]
            gone.append(old)
            self.evictions += 1
        return gone

    def score(self, universe) -> tuple[int, int]:
        """(correct, wrong) laws in this notebook."""
        ok = sum(1 for n, law in self.laws.items() if law.table == universe.functions[n].law.table)
        return ok, len(self.laws) - ok
