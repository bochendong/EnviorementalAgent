"""Scripted teams: reference solutions written for the built-in task generators.

They are not baselines to beat. They show that each built-in task can be solved through the public
operations, they give a reference cost, and they show the division of labour each provider was built
around. They know the generators' templates (the wording of the problems, what the client will say),
so they do not work on held-out tasks; that is what learning agents are for.

They are honest about the network: they pick agents by what their role can do, claim tasks when the
market asks for it, wait out outages, and move information between agents only through the network
(the shared store, else messages, else the board). With all three switched off, information does not
travel and the team does only what each member can do alone.
"""

from __future__ import annotations

import json
import re



class Team:
    """Helpers over the public interface: who can do what, budgets, and moving data through the network."""

    def __init__(self, env):
        self.env = env
        self.k = 0
        self.pub = env.public()
        self.names = list(self.pub["agents"])
        self.cfg = self.pub["config"]
        self.ops = {a: {o["name"] for o in env.ops(a)} for a in self.names}
        self.on = set.union(*self.ops.values())  # the network ops switched on are offered to everyone

    def budget(self, a: str) -> int:
        return self.env.observe(a)["budget"]

    def can(self, op: str) -> list[str]:
        return [a for a in self.names if op in self.ops[a]]

    def pick(self, op: str, prefer: str | None = None) -> str | None:
        alive = [a for a in self.can(op) if self.budget(a) > 0]
        if not alive:
            return None
        if prefer in alive:
            return prefer
        self.k += 1
        return alive[self.k % len(alive)]

    def writer(self, path: str) -> str | None:
        """An agent whose role may write ``path`` (website)."""
        for a in self.names:
            o = self.env.observe(a)
            if "write" in self.ops[a] and any(path.startswith(p) for p in o["scope"].get("write", [""])):
                if o["budget"] > 0:
                    return a
        return None

    def do(self, agent: str | None, op: str, args: dict | None = None) -> dict:
        if agent is None:
            return {"ok": False, "error": "nobody can do this"}
        obs = {}
        tries = 2 + len(self.names) * (self.cfg["outage_rounds"] + 1) * 2  # wait out an outage
        for _ in range(tries):
            obs = self.env.step(agent, op, args or {})
            if "offline" not in str(obs.get("error", "")):
                return obs
        return obs

    def share(self, src: str | None, dst: str | None, key: str, value):
        """Move ``value`` from ``src`` to ``dst`` through the network; returns what ``dst`` received or None."""
        if src is None or dst is None:
            return None
        if src == dst:
            return value
        on = self.on
        if "put" in on:
            self.do(src, "put", {"key": key, "value": value})
            got = self.do(dst, "get", {"key": key})
            return got.get("value") if got.get("ok") else None
        if "send" in on and dst in self.env.observe(src)["neighbours"]:
            self.do(src, "send", {"to": dst, "text": key, "data": value})
            for _ in range(2 * len(self.names) * (self.cfg["latency"] + 1) + 2):
                for m in self.do(dst, "inbox").get("messages", []):
                    if m["text"] == key:
                        return m.get("data")
                if self.budget(dst) <= 0:
                    return None
                self.do(dst, "wait")
            return None
        if "post" in on:
            self.do(src, "post", {"text": json.dumps({"key": key, "value": value}), "tags": [key]})
            for p in self.do(dst, "board", {"tag": key}).get("posts", []):
                return json.loads(p["text"])["value"]
        return None

    def submit(self, agent: str | None, task: str, artifact=None) -> dict:
        if self.cfg["market"] == "claim":
            self.do(agent, "claim", {"task": task})
        args = {"task": task} if artifact is None else {"task": task, "artifact": artifact}
        return self.do(agent, "submit", args)

    def tasks(self, agent: str | None) -> list[dict]:
        return self.do(agent, "tasks").get("tasks", [])


# ------------------------------------------------------------------ website
def _shop_code(answers: dict[str, str]) -> tuple[str, str]:
    name = re.search(r'called "(.+?)"', answers["name"]).group(1)
    o, c, day = re.search(r"open at (\d+):00 and close at (\d+):00, and we are closed on (\w+)", answers["hours"]).groups()
    items = {n: int(p) for n, p in re.findall(r"([a-z][a-z ]*?) \((\d+) coins\)", answers["items"].split("We sell: ")[1])}
    over, off = map(int, re.search(r"over (\d+) coins get (\d+)%", answers["cart"]).groups())
    pages = f'''def handle(path):
    if path == "/":
        return "200 OK", "<h1>{name}</h1>"
    if path == "/about":
        return "200 OK", "<p>Open {o}:00 to {c}:00, closed on {day}.</p>"
    return "404 Not Found", "<p>not found</p>"
'''
    api = f'''PRICES = {items!r}
def handle(method, path, body):
    if path == "/api/items":
        return "200 OK", [{{"name": n, "price": p}} for n, p in sorted(PRICES.items(), key=lambda kv: (kv[1], kv[0]))]
    if path == "/api/cart" and method == "POST":
        names = (body or {{}}).get("items", [])
        if any(n not in PRICES for n in names):
            return "400 Bad Request", {{"error": "unknown item"}}
        t = sum(PRICES[n] for n in names)
        return "200 OK", {{"total": round(t * (100 - {off}) / 100, 2) if t > {over} else t}}
    return "404 Not Found", {{"error": "not found"}}
'''
    return pages, api


def solve_website(env) -> dict:
    """The PM asks the client and passes the answers on; whoever owns pages.py and api.py writes them."""
    T = Team(env)
    pm = T.pick("ask_client")
    qs = {"name": "What is the shop called?", "hours": "What are your opening hours?",
          "items": "What products do you sell and at what prices?", "cart": "How should the cart total work?"}
    answers = {k: T.do(pm, "ask_client", {"question": q}).get("answer", "") for k, q in qs.items()}
    fe, be = T.writer("pages.py"), T.writer("api.py")
    got = {w: T.share(pm, w, "client/answers", answers) for w in {fe, be}}
    try:
        pages, _ = _shop_code(got[fe])
        T.do(fe, "write", {"path": "pages.py", "content": pages})
    except (TypeError, KeyError, AttributeError, IndexError):
        pass  # the answers never arrived
    try:
        _, api = _shop_code(got[be])
        T.do(be, "write", {"path": "api.py", "content": api})
    except (TypeError, KeyError, AttributeError, IndexError):
        pass
    for t in ("home", "about", "items", "missing", "cart", "release"):
        T.submit(T.pick("submit", pm), t)
    return env.metrics()


# ------------------------------------------------------------------ codeworld
def _law(text: str):
    m = re.match(r"(\d+)\*x \+ (\d+) if x % (\d+) == 0 else (\d+)\*x \+ (\d+)", text)
    if m:
        a2, b2, md, a, b = map(int, m.groups())
        return lambda x: (a2 * x + b2) % 101 if x % md == 0 else (a * x + b) % 101
    a, b = map(int, re.match(r"(\d+)\*x \+ (\d+)", text).groups())
    return lambda x: (a * x + b) % 101


def solve_codeworld(env, share: bool = True) -> dict:
    """Projects go round the developers. Each studies the functions its candidates need; with ``share``
    laws go to the store and are looked up there first. A function only its owner may study is studied
    by the owner and sent to whoever needs it."""
    T = Team(env)
    devs = T.can("study")
    sigs = {}
    for line in T.do(devs[0], "signatures").get("functions", []):
        name, rest = line.split(": ")
        sigs[name] = tuple(rest.split(" -> "))
    owner = {}
    for a in devs:
        for m in env.observe(a)["scope"].get("modules", []):  # public: roles say who owns what
            owner[m] = a
    known: dict[str, dict] = {d: {} for d in devs}
    for i, t in enumerate(T.tasks(devs[0])):
        d = max(devs, key=T.budget)  # whoever has the most budget left
        if T.budget(d) <= 0:
            break
        spec = t["spec"]

        def progs(ty, n, spec=spec):
            if n == 0:
                return [[]] if ty == spec["out"] else []
            return [[f] + rest for f, (a, b) in sigs.items() if a == ty for rest in progs(b, n - 1)]

        cands = progs(spec["in"], spec["length"])
        for fn in sorted({f for c in cands for f in c}):
            if fn in known[d]:
                continue
            if share and "get" in T.on:
                got = T.do(d, "get", {"key": f"law/{fn}"})
                if got.get("ok"):
                    known[d][fn] = got["value"]
                    continue
            pooled = share and "put" in T.on
            st = max(devs, key=T.budget) if pooled and not owner else d  # spread the studying
            law = T.do(st, "study", {"function": fn})
            if law.get("ok") and st != d:
                law = {"ok": True, "law": T.share(st, d, f"law/{fn}", law["law"])}
                known[d][fn] = law["law"]
                continue
            if not law.get("ok") and "only the owner" in law.get("error", ""):
                o = owner.get(fn.split(".")[0])
                res = T.do(o, "study", {"function": fn}) if o else {}
                text = T.share(o, d, f"law/{fn}", res["law"]) if res.get("ok") else None
                law = {"ok": text is not None, "law": text}
            elif law.get("ok") and share and "put" in T.on:
                T.do(d, "put", {"key": f"law/{fn}", "value": law["law"]})
            if law.get("ok"):
                known[d][fn] = law["law"]
        for c in cands:
            if all(fn in known[d] for fn in c):
                fs = [_law(known[d][fn]) for fn in c]

                def run(x, fs=fs):
                    for f in fs:
                        x = f(x)
                    return x
                if all(run(x) == y for x, y in spec["examples"]):
                    T.submit(d, t["id"], c)
                    break
    return env.metrics()


# ------------------------------------------------------------------ math
def solve_math(env) -> dict:
    """Problems go round the explorers; for each, the explorer computes the numbers and an algebraist
    the closed form, and they pass results to each other. The last explorer adds up the finals."""
    T = Team(env)
    exs, als = T.can("sequence"), T.can("rsolve")
    tasks = {t["id"]: t for t in T.tasks(exs[0])}
    finals: dict[str, tuple[str, int]] = {}  # problem -> (who knows the answer, answer)
    for i, pid in enumerate(sorted({k.split(".")[0] for k in tasks if "." in k})):
        ex, al = T.pick("sequence", exs[i % len(exs)]), T.pick("rsolve", als[i % len(als)])
        if ex is None or al is None:
            break
        text = tasks[f"{pid}.L1"]["text"]
        v = None
        m = re.search(r"a\(0\) = (\d+), a\(n\+1\) = (\d+)\*a\(n\) \+ (\d+)", text)
        if m:  # a recurrence
            r0, p, q = m.groups()
            vals = T.do(ex, "sequence", {"rec": f"{p}*a(n) + {q}", "init": r0, "count": 7}).get("values")
            if vals:
                T.submit(ex, f"{pid}.L1", vals[6])
            closed = T.do(al, "rsolve", {"recurrence": f"a(n+1) = {p}*a(n) + {q}", "init": {"0": r0}}).get("a(n)")
            if closed:
                T.submit(al, f"{pid}.L2", closed)
            closed = T.share(al, ex, f"{pid}/closed", closed) if closed else None
            if closed:
                N, M = re.search(r"a\((\d+)\) mod (\d+)", tasks[f"{pid}.T"]["text"]).groups()
                v = T.do(ex, "evaluate", {"expr": f"Mod({closed}, {M})", "subs": {"n": N}}).get("value")
        else:  # a sum
            a, b, c = re.search(r"\((\d+)\*k\^2 \+ (\d+)\*k \+ (\d+)\)", text).groups()
            term = f"{a}*k**2 + {b}*k + {c}"
            s10 = T.do(ex, "evaluate", {"expr": f"Sum({term}, (k, 1, 10))"}).get("value")
            if s10:
                T.submit(ex, f"{pid}.L1", s10)
            poly = T.do(al, "simplify", {"expr": f"Sum({term}, (k, 1, n))", "how": "factor"}).get("result")
            if poly:
                T.submit(al, f"{pid}.L2", poly)
                lim = int(re.search(r"S\(n\) > (\d+)", tasks[f"{pid}.T"]["text"]).group(1))
                roots = [s for s in T.do(al, "solve", {"equation": f"{poly} = {lim}", "var": "n"}).get("solutions", [])
                         if "I" not in s]
                got = T.share(al, ex, f"{pid}/poly", {"poly": poly, "roots": roots})
                if got:
                    n = 1
                    if got["roots"]:
                        n = int(float(T.do(ex, "evaluate", {"expr": f"floor({got['roots'][0]})"}).get("value", 1)))
                    for _ in range(5):
                        val = T.do(ex, "evaluate", {"expr": got["poly"], "subs": {"n": n}}).get("value")
                        if val is None or int(val) > lim:
                            break
                        n += 1
                    v = str(n)
        if v is not None and T.submit(ex, f"{pid}.T", v).get("ok"):
            finals[pid] = (ex, int(v))
    if "FINAL" in tasks and finals:
        last = T.pick("sequence", exs[-1])
        total = 0
        for pid, (who, val) in finals.items():
            got = T.share(who, last, f"{pid}/answer", val)
            if got is None:
                return env.metrics()
            total += got
        T.submit(last, "FINAL", str(total))
    return env.metrics()


# ------------------------------------------------------------------ molecule
EDITS = ["add_fluoro", "add_chloro", "add_hydroxyl", "add_methoxy", "add_nitrile", "add_trifluoromethyl",
         "add_carboxyl", "add_amide", "add_sulfonamide", "add_morpholine", "add_piperazine", "aza", "remove",
         "acid_to_amide", "methylate_hydroxyl", "acetylate_amine"]


def solve_molecule(env, repeats: int = 2) -> dict:
    """Structure-activity by the book. Chemists make one analogue of the start per edit and pass them to
    a biologist, who assays them and passes back the gains; the helpful edits are then stacked one by
    one, each kept only if the assay says it still helps. Candidates go to the tasks as they qualify."""
    T = Team(env)
    chems, bios = T.can("edit"), T.can("assay")
    tasks = T.tasks(bios[0])
    done: set[str] = set()

    def make(c, smiles, act):
        for s in T.do(c, "edit", {"smiles": smiles, "action": act}).get("products", []):
            p = T.do(c, "props", {"smiles": s})
            if p.get("qed", 0) >= .5 and p.get("mw", 999) <= 450:
                return s
        return None

    def assay(b, s):
        xs = [T.do(b, "assay", {"smiles": s}).get("activity") for _ in range(repeats)]
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    def try_tasks(b, s, a):
        for t in tasks:
            if t["id"] in done or any(d not in done for d in t["deps"]):
                continue
            need = t["spec"]["need"]
            if a < need.get("activity", 0) - .2:
                return
            if "tox" in need and T.do(b, "tox", {"smiles": s}).get("tox", 1) > need["tox"]:
                return
            if not T.submit(b, t["id"], s).get("ok"):
                return
            done.add(t["id"])  # the market is public: everyone can see a task is done

    start = T.pub["info"]["start"][0]
    chem = T.pick("edit", chems[0])
    analogues = {}
    for k, act in enumerate(EDITS):
        m = make(T.pick("edit", chems[k % len(chems)]), start, act)
        if m:
            analogues[act] = m
    # the biologists split the analogues, each sends its measurements back to the chemist
    gains: dict[str, float] = {}
    acts = sorted(analogues)
    for j, b in enumerate(bios):
        mine = T.share(chem, b, f"sar/analogues/{b}", {a: analogues[a] for a in acts[j::len(bios)]}) or {}
        base = assay(b, start)
        res = {a: v - base for a, m in mine.items() if base is not None and (v := assay(b, m)) is not None}
        gains.update(T.share(b, chem, f"sar/gains/{b}", res) or {})
    cur, cur_a = start, None
    for i, act in enumerate(sorted(gains, key=gains.get, reverse=True) if gains else EDITS):
        if gains and gains[act] < .4:
            break
        chem, b = T.pick("edit", chem), T.pick("assay", bios[i % len(bios)])
        if chem is None or b is None:
            break
        m = make(chem, cur, act)
        if not m:
            continue
        got = T.share(chem, b, "sar/next", m)
        a = assay(b, got) if got else None
        verdict = T.share(b, chem, "sar/verdict", a) if a is not None else None
        if verdict is None or cur_a is None or verdict > cur_a + .3:  # without a verdict the chemist works blind
            cur, cur_a = m, verdict if verdict is not None else cur_a
            if a is not None:
                try_tasks(b, m, a)
        if len(done) == len(tasks):
            break
    return env.metrics()


SOLVERS = {"codeworld": solve_codeworld, "math": solve_math, "website": solve_website, "molecule": solve_molecule}
