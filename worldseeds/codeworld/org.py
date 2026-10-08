"""Developers and how they are organised: alone, as a team without contact, or as a network.

A developer has a notebook of limited capacity and an action budget per sprint. To build a project it
searches the programs that type-check (cheapest to evaluate first) until one reproduces the examples, then
submits it. To know what a function does on some input it can

    use its notebook (free)        if it knows the function's law
    study the function (8 actions) probe it on a fixed design, learn its law, keep it in the notebook
    ask a teammate (1 + 1 actions) who explains the law from what they know (an owner studies first if
                                   needed); the explanation stays in working memory for this project only

Organisations (``MODES``):

    solo         one developer (give it the team's budget for a compute-matched baseline)
    independent  several developers, each on their own projects, never talking
    owners       every module has an owner (like CODEOWNERS); questions about a function go to its owner,
                 who learns its own module's laws when first asked
    directory    a live registry of who knows which law; questions go to someone who knows (else the owner)
    random       no idea who knows what: ask up to two random teammates, then study yourself
    pooled       one shared notebook for everyone, as big as all notebooks together (no message cost):
                 an upper bound for sharing

Town buildings (each an option, off by default):

    board    a notice board on each town plaza listing who knows which law; without routing (``random``)
             one can walk there and read it (1 action) once per sprint instead of asking around blindly
    library  rules written down for everyone: a master deposits its own machines' laws after studying them
             (walk + 1 action); anyone can read them there (walk + 1, every relevant law in one visit with
             ``batch``) instead of asking or studying; they stay in working memory for the project
    post     ask by letter instead of walking over: 1 action, the answer comes after ``post_delay`` actions
             of waiting (chosen when it is cheaper than the walk)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .knowledge import Notebook, fit, study_inputs
from .world import Project, Universe

MODES = ["solo", "independent", "owners", "directory", "random", "pooled"]
STUDY_COST = len(study_inputs())


class OutOfBudget(Exception):
    pass


class Broken(Exception):
    """The machine is out of order (this program cannot be made now)."""


@dataclass
class Dev:
    name: str
    notebook: Notebook
    owns: set[str] = field(default_factory=set)  # modules
    budget: int = 0
    spent: dict = field(default_factory=lambda: {"study": 0, "ask": 0, "answer": 0, "submit": 0, "walk": 0,
                                                 "letter": 0, "wait": 0, "read": 0, "write": 0})
    home: str | None = None  # the workshop (module) it works in; None = the plaza
    loc: str | None = None
    routes: dict = field(default_factory=dict)  # (from, to) -> the shortest way there, once walked
    board: dict | None = None  # what the notice board said (function -> who knew it) when last read
    broken: set = field(default_factory=set)  # machines it believes are out of order

    def spend(self, kind: str, n: int = 1) -> None:
        if self.budget < n:
            raise OutOfBudget(self.name)
        self.budget -= n
        self.spent[kind] += n


class Org:
    def __init__(self, universe: Universe, n: int, capacity: int | None, mode: str, learn: bool = True,
                 seed: int = 0, walk: bool = False, record: bool = False, batch: bool = False,
                 board: bool = False, library: bool = False, post: bool = False, post_delay: int = 3):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; one of {MODES}")
        self.u, self.mode, self.learn = universe, mode, learn
        self.rng = random.Random(seed)
        pool = Notebook(None if capacity is None else capacity * n) if mode == "pooled" else None
        self.devs = [Dev(f"dev{i}", pool if pool is not None else Notebook(capacity)) for i in range(n)]
        if universe.map is None:
            for k, m in enumerate(universe.modules):  # module owners, round robin
                self.devs[k % n].owns.add(m)
        else:  # in the town, neighbours: a master keeps the workshops of one map (or of neighbouring maps)
            mods = sorted(universe.modules, key=lambda m: (universe.room[m][0], universe.modules.index(m)))
            for k, m in enumerate(mods):
                self.devs[k * n // len(mods)].owns.add(m)
        if mode in ("owners", "directory"):  # specialists forget foreign laws before their own modules' laws
            for d in self.devs:
                d.notebook.keep = (lambda name, owns=d.owns: name.split(".", 1)[0] in owns)
        self.owner = {m: d for d in self.devs for m in d.owns}
        for d in self.devs:  # everyone starts in its first workshop (a lone developer: on the plaza)
            d.home = d.loc = next((m for m in universe.modules if m in d.owns), None) if n > 1 else None
        # walk: studying a machine means going to its workshop, asking someone means going to them
        # (next door 1 action, another district 3); without it moves are recorded but free
        self.walk = walk
        # batch: whoever is asked also explains every other law they know that matters for this project
        # (one visit, many answers) instead of only the one asked about
        self.batch = batch
        self._relevant: set[str] = set()
        self.board, self.library, self.post, self.post_delay = board, library, post, post_delay
        self.lib: dict = {}  # the library's shelves: function -> law as written down
        self.notices = {"broken": set(), "repaired": set(), "changed": set()}  # what masters have posted
        self.stats = {"broken_found": 0, "wrong_deliveries": 0, "goal_actions": 0}
        self.goals: list = []  # grand goals (goals.py), worked on before the day's orders
        self.sprint_no = 0
        self.ency = False  # the town encyclopedia is a goal: everyone writes down what is missing
        self.record = record
        self.events: list[dict] = []
        self._project: str | None = None

    def _ev(self, kind: str, dev: Dev, **kw) -> None:
        if self.record:
            self.events.append({"i": len(self.events), "kind": kind, "dev": dev.name, "loc": dev.loc,
                                "budget": dev.budget, "project": self._project, **kw})

    def _go(self, dev: Dev, place: str | None) -> None:
        if dev.loc == place:
            return
        extra = {}
        if self.u.map is not None:  # walk the shortest way, across areas, and remember it
            key = (dev.loc, place)
            known = key in dev.routes
            if not known:
                way = self.u.route(dev.loc, place)
                dev.routes[key], dev.routes[(place, dev.loc)] = way, tuple(reversed(way))
            path = dev.routes[key]
            extra = {"legs": self.u.map.legs(path), "steps": self.u.map.steps(path), "remembered": known}
        cost = self.u.distance(dev.loc, place) if self.walk else 0
        if cost:
            dev.spend("walk", cost)
        self._ev("walk", dev, to=place, frm=dev.loc, cost=cost, **extra)
        dev.loc = place

    # ------------------------------------------------------------ knowledge
    def _study(self, dev: Dev, fn: str):
        self._go(dev, self.u.functions[fn].module)
        if fn in self.u.broken:  # walked there for nothing: it is out of order
            dev.spend("study")
            dev.broken.add(fn)
            self.stats["broken_found"] += 1
            self._ev("broken_found", dev, fn=fn)
            raise Broken(fn)
        dev.spend("study", STUDY_COST)
        law = fit({x: self.u.functions[fn].law(x) for x in study_inputs()})
        gone = dev.notebook.put(fn, law)
        self._ev("learn", dev, fn=fn, law=law.describe(), correct=law.table == self.u.functions[fn].law.table,
                 forgot=gone)
        mine = self.u.functions[fn].module in dev.owns
        if self.library and (mine or self.ency) and (fn not in self.lib or (mine and self.lib[fn].table != law.table)):
            self._go(dev, self._nearest(dev, "library"))  # a master writes its machines down for everyone
            dev.spend("write")
            self.lib[fn] = law
            self._ev("deposit", dev, fn=fn)
        return law

    def _mine(self, dev: Dev) -> set:
        """Laws a master trusts without doubt: its own machines (it would have noticed a change)."""
        if self.mode not in ("owners", "directory"):
            return set()
        return {fn for fn in dev.notebook.laws if self.u.functions[fn].module in dev.owns}

    def _own(self, dev: Dev) -> set:
        return {fn for fn, f in self.u.functions.items() if f.module in dev.owns}

    def apply_events(self, events: list[dict]) -> None:
        """What the people of the town notice when events happen: a master knows about its own machines (and
        posts it on the board); everyone else finds out by trying, by a wrong delivery, or from the board."""
        for e in events:
            fn = e.get("fn")
            # only a team with masters (owners, directory) has someone who looks after each workshop
            owner = self.owner.get(self.u.functions[fn].module) if fn and self.mode in ("owners", "directory") else None
            if e["kind"] == "breakdown":
                self.notices["broken"].add(fn)
                if owner:
                    owner.broken.add(fn)
            elif e["kind"] == "repaired":
                self.notices["broken"].discard(fn)
                self.notices["repaired"].add(fn)
                if owner:
                    owner.broken.discard(fn)
            elif e["kind"] == "drift":
                self.notices["changed"].add(fn)
                if owner and fn in owner.notebook:
                    del owner.notebook.laws[fn]  # the master will study it again when it matters
        if events:
            self._ev("events", self.devs[0], events=events)

    def _nearest(self, dev: Dev, kind: str) -> str:
        """The nearest town building of a kind ("library", "post", "board")."""
        places = [f"{kind}:{d}" for d in range(self.u.n_districts)]
        return min(places, key=lambda p: (self.u.distance(dev.loc, p) if self.u.map is not None else 0, p))

    def _dist(self, a, b) -> int:
        return self.u.distance(a, b) if self.walk and self.u.map is not None else 0

    def _read_library(self, dev: Dev, fn: str, cache: dict):
        """Read ``fn`` (and, with batch, every relevant law on the shelves) at the library, if that is
        cheaper than studying it or asking its master."""
        if not self.library or fn not in self.lib:
            return None
        lib = self._nearest(dev, "library")
        cost = self._dist(dev.loc, lib) + 1
        study = self._dist(dev.loc, self.u.functions[fn].module) + STUDY_COST
        owner = self.owner[self.u.functions[fn].module]
        ask = self._dist(dev.loc, owner.loc) + 1 if self.mode in ("owners", "directory") and owner is not dev else study
        if cost > min(study, ask):
            return None
        self._go(dev, lib)
        dev.spend("read")
        got = [fn]
        cache[("law", fn)] = self.lib[fn]
        if self.batch:
            for g in sorted(self._relevant):
                if g != fn and g in self.lib and ("law", g) not in cache and g not in dev.notebook:
                    cache[("law", g)] = self.lib[g]
                    got.append(g)
        self._ev("read", dev, fn=fn, also=got[1:])
        return self.lib[fn]

    def _read_board(self, dev: Dev) -> None:
        """Walk to the notice board and note who knows what (once per sprint)."""
        self._go(dev, self._nearest(dev, "board"))
        dev.spend("read")
        dev.board = {}
        for d in self.devs:
            if d is not dev:
                for g in d.notebook.laws:
                    dev.board.setdefault(g, []).append(d.name)
        dev.broken -= self.notices["repaired"]  # and the masters' notices about their machines
        dev.broken |= self.notices["broken"]
        for g in self.notices["changed"]:
            if g in dev.notebook and g not in self._own(dev):
                del dev.notebook.laws[g]
        self._ev("board", dev, entries=sum(len(v) for v in dev.board.values()))

    def _helper(self, dev: Dev, fn: str):
        """Who to ask about ``fn`` (and whether they must study it first), per the organisation."""
        others = [d for d in self.devs if d is not dev]
        if not others or self.mode in ("solo", "independent", "pooled"):
            return None
        if self.mode == "random" and self.board:  # read the board once per sprint, then ask who it names
            if dev.board is None:
                self._read_board(dev)
            names = dev.board.get(fn, [])
            holders = [d for d in others if d.name in names and d.budget >= 1]
            holders.sort(key=lambda d: (self._dist(dev.loc, d.loc), d.name))
            for d in holders[:1]:
                if fn in d.notebook:
                    return d
                self._go(dev, d.loc)  # the board was out of date: they have forgotten it
                dev.spend("ask")
                d.spend("answer")
                self._ev("ask", dev, to=d.name, fn=fn, answered=False)
            return None
        if self.mode == "random":
            for d in self.rng.sample(others, min(2, len(others))):
                self._go(dev, d.loc)
                dev.spend("ask")
                if d.budget >= 1 and fn in d.notebook:
                    return d
                self._ev("ask", dev, to=d.name, fn=fn, answered=False)
                if d.budget >= 1:
                    d.spend("answer")  # "sorry, no idea"
            return None
        if self.mode == "directory":
            holders = [d for d in others if fn in d.notebook and d.budget >= 1]
            if self.walk:  # the nearest one who knows
                holders.sort(key=lambda d: self.u.distance(dev.loc, d.loc))
            if holders:
                return holders[0]
        owner = self.owner[self.u.functions[fn].module]
        if owner is dev:
            return None
        if fn in owner.notebook and owner.budget >= 1:
            return owner
        if owner.budget >= 1 + STUDY_COST:  # the owner learns its own module's function first
            self._study(owner, fn)
            return owner
        return None

    def values(self, dev: Dev, fn: str, xs: list[int], cache: dict) -> list[int]:
        """What ``fn`` gives on ``xs``, at the cheapest available price for ``dev``. ``cache`` is the working
        memory of the current project: what teammates explained (laws) and what was run (values). It does
        not use notebook capacity and is gone after the project."""
        law = dev.notebook.get(fn) or cache.get(("law", fn))
        if law is not None:
            return [law(x) for x in xs]
        known = cache.setdefault(fn, {})
        need = [x for x in xs if x not in known]
        if need and fn in dev.broken:
            raise Broken(fn)
        if need:
            law = self._read_library(dev, fn, cache)
            if law is not None:
                return [law(x) for x in xs]
            asked = self.mode == "random" and not self.board  # random asking has walked and asked already
            helper = self._helper(dev, fn)
            if helper is not None and fn in helper.broken:  # "it is out of order"
                if not asked:
                    self._go(dev, helper.loc)
                    dev.spend("ask")
                helper.spend("answer")
                dev.broken.add(fn)
                self._ev("ask", dev, to=helper.name, fn=fn, answered=True, law="out of order", also=[])
                raise Broken(fn)
            if helper is not None:  # the teammate explains what the function does (one question, one answer)
                by_post = (not asked and self.post and self.walk and self.u.map is not None
                           and self._dist(dev.loc, helper.loc) > self.post_delay)
                if by_post:  # a letter: no walk, but the answer takes a while
                    dev.spend("letter")
                    dev.spend("wait", self.post_delay)
                elif not asked:
                    self._go(dev, helper.loc)
                    dev.spend("ask")
                helper.spend("answer")
                law = helper.notebook.get(fn)
                cache[("law", fn)] = law
                extra = []
                if self.batch:
                    for g in sorted(self._relevant):
                        if g != fn and g in helper.notebook.laws and ("law", g) not in cache and g not in dev.notebook:
                            cache[("law", g)] = helper.notebook.laws[g]
                            extra.append(g)
                self._ev("ask", dev, to=helper.name, fn=fn, answered=True, law=law.describe(), also=extra,
                         **({"by": "post", "delay": self.post_delay} if by_post else {}))
                return [law(x) for x in xs]
            if self.learn:
                law = self._study(dev, fn)
                return [law(x) for x in xs]
            dev.spend("study", len(need))  # no memory: just run it on what is needed now
            known.update({x: self.u.functions[fn].law(x) for x in need})
        return [known[x] for x in xs]

    # ------------------------------------------------------------ projects
    def _cost(self, dev: Dev, program) -> int:
        """Estimated price of evaluating a program: functions the developer would still have to find out."""
        c = 0
        for fn in program:
            if fn in dev.notebook:
                continue
            owner = self.owner[self.u.functions[fn].module]
            if self.mode in ("owners", "directory") and owner is not dev:
                c += 2
            else:
                c += STUDY_COST
        return c

    def _deliver(self, dev: Dev, project: Project, prog, tried: int, before: int, verify=None) -> dict:
        dev.spend("submit")
        down = [fn for fn in prog if fn in self.u.broken]
        ok = not down and (verify(prog) if verify else self.u.table(prog) == self.u.table(project.target))
        why = {}
        if down:  # the order could not be made: a machine is out of order
            dev.broken.update(down)
            why = {"why": "out of order", "machines": down}
        elif not ok:  # it came out wrong: some law it relied on is wrong (a machine was re-tuned)
            self.stats["wrong_deliveries"] += 1
            for fn in prog:
                if fn in dev.notebook:
                    del dev.notebook.laws[fn]
            why = {"why": "came out wrong"}
        self._ev("submit", dev, program=list(prog), ok=ok, tried=tried, **why)
        return {"done": ok, "tried": tried, "actions": sum(dev.spent.values()) - before}

    def solve(self, dev: Dev, project: Project, cands=None, verify=None) -> dict:
        """Search programs (cheapest first) until one fits the examples, then submit it."""
        cands = list(cands) if cands is not None else self.u.candidates(project.in_type, project.out_type)
        self._relevant = {fn for c in cands for fn in c}
        cands.sort(key=lambda p: (self._cost(dev, p), p))
        xs = [x for x, _ in project.examples]
        want = [y for _, y in project.examples]
        cache: dict = {}
        prefix: dict[tuple, list[int]] = {(): xs}
        before = sum(dev.spent.values())
        tried = 0
        self._project = project.id
        self._ev("start", dev, text=project.text())
        try:
            for attempt in (0, 1):
                if attempt:  # nothing fits: something it remembers must be out of date; doubt it, look again
                    doubted = sorted({fn for c in cands for fn in c if fn in dev.notebook} - self._mine(dev))
                    if not doubted and not any(isinstance(k, tuple) and k[0] == "law" for k in cache):
                        break
                    for fn in doubted:
                        del dev.notebook.laws[fn]
                    cache.clear()
                    prefix = {(): xs}
                    self._ev("doubt", dev, laws=doubted)
                for prog in cands:
                    if dev.broken and any(fn in dev.broken for fn in prog):
                        continue
                    tried += 1
                    vals = xs
                    try:
                        for k in range(1, len(prog) + 1):
                            key = prog[:k]
                            if key not in prefix:
                                prefix[key] = self.values(dev, prog[k - 1], prefix[prog[:k - 1]], cache)
                            vals = prefix[key]
                    except Broken:
                        continue
                    if vals == want:
                        return self._deliver(dev, project, prog, tried, before, verify)
            self._ev("give_up", dev, reason="no program fits", tried=tried)
            return {"done": False, "tried": tried, "actions": sum(dev.spent.values()) - before, "stuck": True}
        except OutOfBudget:
            self._ev("give_up", dev, reason="out of budget", tried=tried)
            return {"done": False, "tried": tried, "actions": sum(dev.spent.values()) - before, "out_of_budget": True}
        finally:
            if self.u.map is not None and dev.home and dev.loc != dev.home:  # back to one's own workshop
                try:
                    self._go(dev, dev.home)
                except OutOfBudget:
                    dev.loc = dev.home  # the day is over: home anyway
            self._project = None

    # ------------------------------------------------------------ grand goals
    def _goal_tasks(self) -> list:
        """This sprint's goal work: one task per open part (round robin over the team), and for the
        encyclopedia, machines whose rule is missing from the library (or, for their master, re-tuned)."""
        tasks = []
        for g in self.goals:
            if g.done_at is not None or self.sprint_no > g.deadline:
                continue
            if g.kind == "encyclopedia":
                for p in g.parts:
                    fn = p["fn"]
                    changed = fn in self.notices["changed"] and self.mode in ("owners", "directory")
                    if fn not in self.lib or changed:
                        tasks.append(("ency", g, p))
                continue
            tasks += [("goal", g, p) for p in g.parts if p.get("done") is None]
        return tasks

    def _assign(self, tasks: list) -> list[list]:
        """Who does which goal task: the master of the machine (encyclopedia), else round robin."""
        out = [[] for _ in self.devs]
        k = 0
        for t in tasks:
            if t[0] == "ency" and self.mode in ("owners", "directory"):
                d = self.owner[self.u.functions[t[2]["fn"]].module]
                out[self.devs.index(d)].append(t)
            else:
                out[k % len(self.devs)].append(t)
                k += 1
        return out

    def work_goal(self, dev: Dev, task) -> None:
        kind, g, part = task
        from .goals import check

        self._project = part["id"]
        self._ev("goal_start", dev, goal=g.id, part=part["id"], text=part["text"])
        try:
            if kind == "ency":
                fn = part["fn"]
                law = dev.notebook.get(fn)
                if law is None or fn in self.notices["changed"]:
                    self._study(dev, fn)  # studying deposits it (see _study)
                elif fn not in self.lib:
                    self._go(dev, self._nearest(dev, "library"))
                    dev.spend("write")
                    self.lib[fn] = law
                    self._ev("deposit", dev, fn=fn)
                return
            if g.kind == "prize":
                ok = self._prize(dev, g, part)
            else:
                pr = part["project"]
                cands = None
                if g.kind == "recipe":  # any raw good may have been used
                    from .goals import _all_candidates
                    cands = _all_candidates(self.u, pr.out_type)
                res = self.solve(dev, pr, cands=cands, verify=lambda prog: check(self.u, g, part, prog))
                ok = res["done"]
            if ok:
                part["done"] = self.sprint_no
                part["by"] = dev.name
                self._ev("goal_part", dev, goal=g.id, part=part["id"])
        except (OutOfBudget, Broken):
            pass
        finally:
            self._project = None

    def _prize(self, dev: Dev, g, part) -> bool:
        """Find a recipe whose rules it knows (or can learn), run it backwards to the grade the judges want."""
        from .goals import check

        cands = self.u.candidates(part["in"], part["out"])
        cands.sort(key=lambda p: (self._cost(dev, p), p))
        everything = list(range(len(self.u.functions[next(iter(self.u.functions))].law.table)))
        cache: dict = {}
        for prog in cands:
            if dev.broken and any(fn in dev.broken for fn in prog):
                continue
            try:
                vals = everything
                for fn in prog:
                    vals = self.values(dev, fn, vals, cache)
            except Broken:
                continue
            xs = [x for x, y in zip(everything, vals) if y == part["grade"]]
            if xs:
                dev.spend("submit")
                ok = check(self.u, g, part, prog, xs[0])
                self._ev("submit", dev, program=list(prog), ok=ok, tried=1, batch_grade=xs[0])
                if not ok:  # it came out wrong: what it believed was out of date
                    for fn in prog:
                        if fn in dev.notebook:
                            del dev.notebook.laws[fn]
                return ok
        return False

    def _score_goals(self) -> None:
        for g in self.goals:
            if g.kind == "encyclopedia":
                for p in g.parts:
                    fn = p["fn"]
                    right = fn in self.lib and self.lib[fn].table == self.u.functions[fn].law.table
                    p["done"] = (p.get("done") or self.sprint_no) if right else None
            if g.done_at is None and self.sprint_no <= g.deadline and all(p.get("done") is not None for p in g.parts):
                g.done_at = self.sprint_no
                self._ev("goal_done", self.devs[0], goal=g.id)

    # ------------------------------------------------------------ sprints
    def sprint(self, projects: list[Project], budget: int, events: list[dict] | None = None, goals=None) -> dict:
        """Every developer gets ``budget`` actions; projects are handed out round robin and worked on in
        turns (one project per developer per turn) until done or nobody has budget left. Grand goals
        (``goals``, shared across sprints) come first: their open parts are handed out before the orders."""
        self.sprint_no += 1
        if goals is not None:
            self.goals = goals
            self.ency = any(g.kind == "encyclopedia" for g in goals)
            self.library = self.library or self.ency  # an encyclopedia needs a library
        for d in self.devs:
            d.budget = budget
            d.board = None
            for k in d.spent:
                d.spent[k] = 0
        for k in self.stats:
            self.stats[k] = 0
        self.notices["changed"], self.notices["repaired"] = set(), set()
        masters = self.mode in ("owners", "directory")
        for d in self.devs:  # who is not the master cannot tell whether it has been repaired since
            d.broken = {fn for fn in d.broken if masters and self.u.functions[fn].module in d.owns}
        self.apply_events(events or [])
        if self.goals:
            from .goals import reissue

            for e in reissue(self.u, self.goals):
                self._ev("goal_reissued", self.devs[0], **{k: v for k, v in e.items() if k != "kind"})
        gq = self._assign(self._goal_tasks()) if self.goals else [[] for _ in self.devs]
        for d, tasks in zip(self.devs, gq):  # goal work first, while there is time for it
            for t in tasks:
                if d.budget <= 0:
                    break
                before = sum(d.spent.values())
                self.work_goal(d, t)
                self.stats["goal_actions"] = self.stats.get("goal_actions", 0) + sum(d.spent.values()) - before
        queues = [projects[i::len(self.devs)] for i in range(len(self.devs))]
        results = []
        while any(queues):
            progressed = False
            for d, q in zip(self.devs, queues):
                if q and d.budget > 0:
                    results.append(self.solve(d, q.pop(0)))
                    progressed = True
                elif q:
                    results += [{"done": False, "out_of_budget": True, "actions": 0, "tried": 0} for _ in q]
                    q.clear()
            if not progressed:
                break
        if self.goals:
            self._score_goals()
        return self.metrics(results)

    def metrics(self, results: list[dict]) -> dict:
        spent = {k: sum(d.spent[k] for d in self.devs) for k in self.devs[0].spent}
        books = {id(d.notebook): d.notebook for d in self.devs}.values()
        correct = set()
        wrong = 0
        for nb in books:
            for n, law in nb.laws.items():
                if law.table == self.u.functions[n].law.table:
                    correct.add(n)
                else:
                    wrong += 1
        return {
            "projects": len(results), "done": sum(r["done"] for r in results),
            "out_of_budget": sum(bool(r.get("out_of_budget")) for r in results),
            "actions": sum(spent.values()), **{f"spent_{k}": v for k, v in spent.items()},
            "known_union": len(correct), "known_share": len(correct) / self.u.n_functions,
            "wrong_laws": wrong,
            "known_per_dev": sum(len(nb) for nb in books) / len(self.devs) if self.mode != "pooled"
            else len(next(iter(books))),
            "relearned": sum(nb.relearned for nb in books), "evictions": sum(nb.evictions for nb in books),
            "routes_known": sum(len(d.routes) for d in self.devs) // 2,
            **self.stats,
            **({"goal_parts_done": sum(p.get("done") is not None for g in self.goals for p in g.parts),
                "goal_parts": sum(len(g.parts) for g in self.goals),
                "goals_done": sum(g.done_at is not None for g in self.goals),
                "goal_progress": {g.id: round(g.progress, 3) for g in self.goals}} if self.goals else {}),
        }
