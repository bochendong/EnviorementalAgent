"""Scripted solvers: teams that solve each provider through the network API alone (no hidden state).

They prove every provider is solvable through its public operations, give baselines, and show the
intended division of labour: who asks, who computes, how results travel (messages, the store). They are
baselines, not part of the environment.
"""

from __future__ import annotations

import re

from .env import NetworkEnv


def _by_role(env: NetworkEnv) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for a in env.agents.values():
        out.setdefault(a.role.name, []).append(a.name)
    return out


# ------------------------------------------------------------------ website
def _shop_code(answers: dict[str, str]) -> tuple[str, str]:
    name = re.search(r'called "(.+?)"', answers["name"]).group(1)
    o, c, day = re.search(r"open at (\d+):00 and close at (\d+):00, and we are closed on (\w+)", answers["hours"]).groups()
    items = dict((n, int(p)) for n, p in re.findall(r"([a-z][a-z ]*?) \((\d+) coins\)", answers["items"].split("We sell: ")[1]))
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


def solve_website(env: NetworkEnv) -> dict:
    """The PM asks the client and shares the answers in the store; frontend and backend write their files."""
    r = _by_role(env)
    pm, fe, be = r["pm"][0], r["frontend"][0], r["backend"][0]
    qs = {"name": "What is the shop called?", "hours": "What are your opening hours?",
          "items": "What products do you sell and at what prices?", "cart": "How should the cart total work?"}
    for k, q in qs.items():
        env.step(pm, "put", {"key": f"client/{k}", "value": env.step(pm, "ask_client", {"question": q})["answer"]})
    answers = {k: env.step(fe, "get", {"key": f"client/{k}"})["value"] for k in qs}
    pages, api = _shop_code(answers)
    env.step(fe, "write", {"path": "pages.py", "content": pages})
    env.step(be, "write", {"path": "api.py", "content": api})
    env.step(pm, "run_tests", {})
    for t in ("home", "about", "items", "missing", "cart", "release"):
        env.step(pm, "submit", {"task": t})
    return env.metrics()


# ------------------------------------------------------------------ codeworld
def _law(text: str):
    m = re.match(r"(\d+)\*x \+ (\d+) if x % (\d+) == 0 else (\d+)\*x \+ (\d+)", text)
    if m:
        a2, b2, md, a, b = map(int, m.groups())
        return lambda x: (a2 * x + b2) % 101 if x % md == 0 else (a * x + b) % 101
    a, b = map(int, re.match(r"(\d+)\*x \+ (\d+)", text).groups())
    return lambda x: (a * x + b) % 101


def solve_codeworld(env: NetworkEnv, share: bool = True) -> dict:
    """Each developer takes projects in turn, studies the functions it needs and builds the program.
    With ``share`` the laws go to the shared store and nobody studies a function twice."""
    devs = list(env.agents)
    sigs = {}
    for line in env.step(devs[0], "signatures", {})["functions"]:
        name, rest = line.split(": ")
        sigs[name] = tuple(rest.split(" -> "))
    known: dict[str, dict] = {d: {} for d in devs}
    tasks = env.step(devs[0], "tasks", {})["tasks"]
    for i, t in enumerate(tasks):
        d = devs[i % len(devs)]
        spec = t["spec"]

        def progs(ty, n):
            if n == 0:
                return [[]] if ty == spec["out"] else []
            return [[f] + rest for f, (a, b) in sigs.items() if a == ty for rest in progs(b, n - 1)]

        cands = progs(spec["in"], spec["length"])
        for fn in sorted({f for c in cands for f in c}):
            if fn in known[d]:
                continue
            got = env.step(d, "get", {"key": f"law/{fn}"}) if share else {"ok": False}
            if got.get("ok"):
                known[d][fn] = got["value"]
                continue
            law = env.step(d, "study", {"function": fn})
            if not law.get("ok"):
                break
            known[d][fn] = law["law"]
            if share:
                env.step(d, "put", {"key": f"law/{fn}", "value": law["law"]})
        for c in cands:
            if all(fn in known[d] for fn in c):
                fs = [_law(known[d][fn]) for fn in c]

                def run(x):
                    for f in fs:
                        x = f(x)
                    return x
                if all(run(x) == y for x, y in spec["examples"]):
                    env.step(d, "submit", {"task": t["id"], "artifact": c})
                    break
    return env.metrics()


# ------------------------------------------------------------------ math
def solve_math(env: NetworkEnv) -> dict:
    """Explorers compute numbers, the algebraist finds closed forms; results travel by message."""
    r = _by_role(env)
    ex, al = r["explorer"][0], r["algebraist"][0]
    tasks = {t["id"]: t for t in env.step(ex, "tasks", {})["tasks"]}
    finals = {}
    for pid in sorted({k.split(".")[0] for k in tasks if "." in k}):
        text = tasks[f"{pid}.L1"]["text"]
        m = re.search(r"a\(0\) = (\d+), a\(n\+1\) = (\d+)\*a\(n\) \+ (\d+)", text)
        if m:  # a recurrence
            r0, p, q = m.groups()
            vals = env.step(ex, "sequence", {"rec": f"{p}*a(n) + {q}", "init": r0, "count": 7})["values"]
            env.step(ex, "submit", {"task": f"{pid}.L1", "artifact": vals[6]})
            env.step(ex, "send", {"to": al, "text": f"{pid}: a(n+1) = {p}*a(n) + {q}, a(0) = {r0}"})
            env.step(al, "inbox", {})
            closed = env.step(al, "rsolve", {"recurrence": f"a(n+1) = {p}*a(n) + {q}", "init": {"0": r0}})["a(n)"]
            env.step(al, "submit", {"task": f"{pid}.L2", "artifact": closed})
            env.step(al, "send", {"to": ex, "text": closed})
            msg = env.step(ex, "inbox", {})["messages"][-1]["text"]
            N, M = re.search(r"a\((\d+)\) mod (\d+)", tasks[f"{pid}.T"]["text"]).groups()
            v = env.step(ex, "evaluate", {"expr": f"Mod({msg}, {M})", "subs": {"n": N}})["value"]
        else:  # a sum
            a, b, c = re.search(r"\((\d+)\*k\^2 \+ (\d+)\*k \+ (\d+)\)", text).groups()
            term = f"{a}*k**2 + {b}*k + {c}"
            env.step(ex, "submit", {"task": f"{pid}.L1", "artifact":
                                    env.step(ex, "evaluate", {"expr": f"Sum({term}, (k, 1, 10))"})["value"]})
            poly = env.step(al, "simplify", {"expr": f"Sum({term}, (k, 1, n))", "how": "factor"})["result"]
            env.step(al, "submit", {"task": f"{pid}.L2", "artifact": poly})
            env.step(al, "put", {"key": f"{pid}/S", "value": poly})
            T = int(re.search(r"S\(n\) > (\d+)", tasks[f"{pid}.T"]["text"]).group(1))
            roots = env.step(al, "solve", {"equation": f"{poly} = {T}", "var": "n"})["solutions"]
            guess = [s for s in roots if "I" not in s]
            S = env.step(ex, "get", {"key": f"{pid}/S"})["value"]
            n = int(float(env.step(ex, "evaluate", {"expr": f"floor({guess[0]})"})["value"])) if guess else 1
            while int(env.step(ex, "evaluate", {"expr": S, "subs": {"n": n}})["value"]) <= T:
                n += 1
            v = str(n)
        env.step(ex, "submit", {"task": f"{pid}.T", "artifact": v})
        finals[pid] = int(v)
    if "FINAL" in tasks:
        env.step(ex, "submit", {"task": "FINAL", "artifact": str(sum(finals.values()))})
    return env.metrics()


# ------------------------------------------------------------------ molecule
EDITS = ["add_fluoro", "add_chloro", "add_hydroxyl", "add_methoxy", "add_nitrile", "add_trifluoromethyl",
         "add_carboxyl", "add_amide", "add_sulfonamide", "add_morpholine", "add_piperazine", "aza", "remove",
         "acid_to_amide", "methylate_hydroxyl"]


def solve_molecule(env: NetworkEnv, repeats: int = 2) -> dict:
    """Structure-activity by the book. The chemists make one analogue of the start per edit, the biologist
    assays them (results in the shared store); the edits that helped are then stacked one by one, each
    kept only if the assay says it still helps. Candidates go to the tasks as they qualify."""
    r = _by_role(env)
    chem, bio = r["chemist"], r["biologist"][0]
    tasks = env.step(bio, "tasks", {})["tasks"]

    def make(c, smiles, act):
        for s in env.step(c, "edit", {"smiles": smiles, "action": act}).get("products", []):
            p = env.step(c, "props", {"smiles": s})
            if p.get("qed", 0) >= .5 and p.get("mw", 999) <= 450:
                return s
        return None

    def assay(s):
        xs = [env.step(bio, "assay", {"smiles": s}).get("activity") for _ in range(repeats)]
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else -1.0

    def try_tasks(s, a):
        for t in tasks:
            if env.state[t["id"]]["status"] == "done" or not env._ready(env.tasks[t["id"]]):
                continue
            need = t["spec"]["need"]
            if a < need.get("activity", 0) - .2:
                return
            if "tox" in need and env.step(bio, "tox", {"smiles": s}).get("tox", 1) > need["tox"]:
                return
            if not env.step(bio, "submit", {"task": t["id"], "artifact": s}).get("ok"):
                return

    start = env.provider.starts[0]  # public: reset() reports the start molecules
    base = assay(start)
    analogues = {}
    for k, act in enumerate(EDITS):
        m = make(chem[k % len(chem)], start, act)
        if m:
            analogues[act] = m
    env.step(chem[0], "put", {"key": "sar/analogues", "value": analogues})
    gains = {act: assay(m) - base for act, m in env.step(bio, "get", {"key": "sar/analogues"})["value"].items()}
    env.step(bio, "put", {"key": "sar/gains", "value": gains})
    cur, cur_a = start, base
    for act in sorted(gains, key=gains.get, reverse=True):
        if gains[act] < .4:
            break
        m = make(chem[0], cur, act)
        if not m:
            continue
        a = assay(m)
        if a > cur_a + .3:
            cur, cur_a = m, a
            try_tasks(cur, cur_a)
        if env.solved:
            break
    return env.metrics()


SOLVERS = {"codeworld": solve_codeworld, "math": solve_math, "website": solve_website, "molecule": solve_molecule}
