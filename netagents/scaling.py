"""The reference law: how fast a team that wastes nothing solves a problem of known work and span.

    python -m netagents.scaling --out results/net/scaling-reference
    python -m netagents.scaling --grain 4 --sizes 1 2 4 8

Problems come from the DAG provider (worldseeds/net/providers/dag.py): ``depth`` layers of ``width`` tasks
and a final task, each task ``grain`` applies of a hidden function and a submission, starting from its
parents' answers. Two families, as in parallel computing:

    fixed     the same problem for every team size (Amdahl: speed-up is capped by the span)
    scaled    width grows with the team (Gustafson: a bigger team takes on a bigger problem)

Time is in rounds (every agent takes one action a round, netagents/lockstep.py). For each team size:

    lower bound   no strategy is faster: max(ceil(W / N), D), W = tasks * (grain + 1) actions of work and
                  D = (depth + 1) * (grain + 1) on the longest chain, sharing answers counted as free
    reference     a scripted team (list scheduling: an idle agent takes the open task of the lowest layer
                  whose parents' answers are out) that passes answers on in the cheaper of two ways:
                  broadcast (one message to everyone; one inbox read brings all that arrived) or the
                  shared store (one write; one read per answer needed). One agent needs no sharing and
                  meets the lower bound exactly

An LLM team is measured against both (netagents/netscale.py).
"""

from __future__ import annotations

import argparse
import json
import math
import os

from worldseeds.net import NetConfig, NetworkEnv, providers

SHARING = ("broadcast", "store")


def make_env(width: int, depth: int, n: int, seed: int, fanin: int = 2, grain: int = 1) -> NetworkEnv:
    env = NetworkEnv(providers.make("dag", width=width, depth=depth, fanin=fanin, grain=grain, agents=n),
                     NetConfig(budget=10 ** 6))
    env.reset(seed)
    return env


def lower_bound(width: int, depth: int, n: int, grain: int = 1) -> int:
    tasks = width * depth + 1
    return max(math.ceil(tasks * (grain + 1) / n), (depth + 1) * (grain + 1))


def scripted_team(env, sharing: str = "broadcast") -> dict:
    """Every agent in turn takes one action a round. Returns rounds to solve and actions."""
    raw, grain = env.provider.raw, env.provider.grain
    agents = list(env.agents)
    alone = len(agents) == 1
    known = {a: {} for a in agents}  # answers each agent holds
    out: set[str] = set()  # answers passed on to the team
    taken: set[str] = set()
    plan: dict[str, list] = {a: [] for a in agents}

    def steps(a, tid):
        t = raw[tid]
        missing = [d for d in t["deps"] if d not in known[a]]
        reads = [] if not missing else (
            [("inbox", lambda: {}, lambda o: _heard(known[a], o))] if sharing == "broadcast" else
            [("get", lambda d=d: {"key": f"ans/{d}"}, lambda o, d=d: known[a].__setitem__(d, int(o["value"])))
             for d in missing])
        x = {"v": None}

        def start():
            return {"task": tid, "x": [known[a][d] for d in t["deps"]] if t["deps"] else t["start"]}

        applies = [("apply", (lambda i=i: start() if i == 0 else {"task": tid, "x": x["v"]}),
                    lambda o: x.__setitem__("v", o["f(x)"])) for i in range(grain)]

        def done(o):
            if not o.get("ok"):
                raise RuntimeError(f"scripted submission refused: {o}")
            known[a][tid] = x["v"]

        submit = [("submit", lambda: {"task": tid, "artifact": str(x["v"])}, done)]
        share = [] if alone or tid == "FINAL" else [
            ("send", lambda: {"to": "*", "text": f"ANS {tid} {x['v']}"}, lambda o: out.add(tid))
            if sharing == "broadcast" else
            ("put", lambda: {"key": f"ans/{tid}", "value": str(x["v"])}, lambda o: out.add(tid))]
        return reads + applies + submit + share

    solved_at = None
    for _ in range(10 ** 5):
        if env.solved:
            break
        for a in agents:
            if not plan[a]:
                have = known[a] if alone else {**known[a], **dict.fromkeys(out)}
                ready = [t for t, s in env.state.items() if s["status"] == "open" and t not in taken
                         and all(d in have for d in raw[t]["deps"])]
                if not ready:
                    env.step(a, "wait")
                    continue
                # the lowest layer first; among those, one whose parents' answers this agent already holds
                t = min(ready, key=lambda x: (raw[x]["layer"], sum(d not in known[a] for d in raw[x]["deps"])))
                taken.add(t)
                plan[a] = steps(a, t)
            op, args, then = plan[a].pop(0)
            then(env.step(a, op, args()))
        if env.solved and solved_at is None:
            solved_at = env.round
    return {"solved": env.solved, "rounds": solved_at if solved_at is not None else env.round,
            "actions": env.actions}


def _heard(known: dict, obs: dict):
    for m in obs.get("messages", []):
        parts = m["text"].split()
        if len(parts) == 3 and parts[0] == "ANS":
            known[parts[1]] = int(parts[2])


def run(width: int, depth: int, n: int, seed: int, fanin: int = 2, grain: int = 1) -> dict:
    """The reference on one problem: the faster sharing (one agent shares nothing), and the lower bound."""
    tried = {s: scripted_team(make_env(width, depth, n, seed, fanin, grain), s) for s in (SHARING[:1] if n == 1
                                                                                          else SHARING)}
    best = min(tried, key=lambda s: tried[s]["rounds"])
    tasks = width * depth + 1
    return {"width": width, "depth": depth, "grain": grain, "agents": n, "seed": seed, "solved": tried[best]["solved"],
            "rounds": tried[best]["rounds"], "sharing": best if n > 1 else "none",
            **{f"rounds_{s}": r["rounds"] for s, r in tried.items() if n > 1},
            "work": tasks * (grain + 1), "span": (depth + 1) * (grain + 1),
            "lower_bound": lower_bound(width, depth, n, grain)}


def table(rows: list[dict]) -> str:
    out = ["| family | grain | agents | problem | lower bound | reference | sharing | speed-up (reference) | "
           "speed-up (bound) |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        base = r["single_rounds"]
        out.append(f"| {r['family']} | {r['grain']} | {r['agents']} | {r['width']} x {r['depth']} | {r['lower_bound']} | "
                   f"{r['rounds']} | {r['sharing']} | {base / r['rounds']:.2f} | {base / r['lower_bound']:.2f} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", type=int, nargs="*", default=[1, 2, 4, 8, 16, 32])
    ap.add_argument("--fixed", type=int, nargs=2, default=[16, 4], metavar=("WIDTH", "DEPTH"))
    ap.add_argument("--depth", type=int, default=4, help="depth of the scaled family (width = team size)")
    ap.add_argument("--grain", type=int, nargs="*", default=[1, 4])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rows = []
    for g in a.grain:
        for fam in ("fixed", "scaled"):
            for n in a.sizes:
                w, d = a.fixed if fam == "fixed" else (n, a.depth)
                r = {"family": fam, **run(w, d, n, a.seed, grain=g)}
                r["single_rounds"] = run(w, d, 1, a.seed, grain=g)["rounds"]
                rows.append(r)
    text = table(rows)
    print(text)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "reference.json"), "w") as f:
            json.dump(rows, f, indent=1)
        with open(os.path.join(a.out, "reference.md"), "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
