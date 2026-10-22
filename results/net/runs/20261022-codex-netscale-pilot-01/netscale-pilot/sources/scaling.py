"""The reference law: how fast a perfectly coordinated team solves a problem of known work and span.

    python -m netagents.scaling --out results/net/scaling-reference

Problems come from the math provider's ``dag`` generator (worldseeds/net/providers/math.py gen_dag):
``depth`` layers of ``width`` tasks, each task needing its parents' answers. A scripted team that never
wastes an action (list scheduling: every agent takes an open task; answers travel through the shared
store) is run on two families, as in parallel computing:

    fixed     the same problem for every team size (Amdahl: speed-up is capped by the span)
    scaled    width grows with the team (Gustafson: a bigger team takes on a bigger problem)

Time is measured in the environment's rounds (a round is one action per agent). The table gives each
team's rounds to solve, its speed-up over one agent, and the speed-up Brent's theorem guarantees a greedy
schedule, from T_N <= W/N + D (work and span in agent actions, counting the reads and writes a team needs and
one agent does not). LLM networks are measured against this curve: the share of the scripted
team's speed-up they reach is their coordination efficiency.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re

from worldseeds.net import NetConfig, NetworkEnv, providers


def scripted_dag_team(env) -> dict:
    """Every agent in turn takes one action. An idle agent claims the open task with the most work below it
    (the lowest layer first), reads its parents' answers from the store, computes, submits and stores the
    answer. Returns rounds to solve and actions."""
    raw = env.provider.raw
    agents = list(env.agents)
    taken: set[str] = set()
    plan: dict[str, list] = {a: [] for a in agents}
    done_at = None
    for _ in range(100000):
        if env.solved or env.done:
            break
        for a in agents:
            if env.solved or env.done:
                break
            if not plan[a]:
                ready = [t for t, s in env.state.items() if s["status"] == "open" and t not in taken
                         and all(_known(env, a, d) for d in env.tasks[t].deps)]
                if not ready:
                    env.step(a, "wait")
                    continue
                t = min(ready, key=lambda x: raw[x].get("layer", 10 ** 6))
                taken.add(t)
                plan[a] = _steps(t, raw[t], shared="put" in env.usable(a))
            op, args = plan[a].pop(0)
            obs = env.step(a, op, args(env) if callable(args) else args)
            if op == "submit" and not obs.get("ok"):
                raise RuntimeError(f"scripted submission refused: {obs}")
        if env.solved and done_at is None:
            done_at = env.round
    return {"solved": env.solved, "rounds": done_at if done_at is not None else env.round, "actions": env.actions}


def _known(env, agent, tid) -> bool:
    """Is the answer of tid available to agent: in the store for a team, its own submission for one agent."""
    if "get" in env.usable(agent):
        return f"ans/{tid}" in env.store
    return env.state[tid]["status"] == "done"


def _steps(tid: str, t: dict, shared: bool) -> list:
    """The actions of one task. A team reads the parents' answers from the store and stores its own; one agent
    remembers them."""
    reads = [("get", {"key": f"ans/{d}"}) for d in t["deps"]] if shared else []
    store = [("put", {"key": f"ans/{tid}", "value": t["answer"]})] if shared else []
    if tid == "FINAL":
        return reads + [("submit", {"task": tid, "artifact": t["answer"]})]
    m = re.search(r"a\(n\+1\) = (\d+)\*a\(n\) \+ (\d+): what is a\((\d+)\) mod (\d+)", t["text"])
    p, q, k, mod = map(int, m.groups())

    def seq(env, t=t, p=p, q=q, k=k):
        raw = env.provider.raw
        if t["deps"]:
            r = sum(int(raw[d]["answer"]) for d in t["deps"]) % 10
        else:
            r = int(re.search(r"a\(0\) = (\d+)", t["text"]).group(1))
        return {"rec": f"{p}*a(n) + {q}", "init": str(r), "count": k + 1}

    return reads + [("sequence", seq), ("submit", {"task": tid, "artifact": t["answer"]})] + store


def run(width: int, depth: int, n: int, seed: int, fanin: int = 2) -> dict:
    prov = providers.make("math", dag=(width, depth, fanin), free_roles=True, explorers=n, algebraists=0)
    env = NetworkEnv(prov, NetConfig(budget=10 ** 6))
    env.reset(seed)
    r = scripted_dag_team(env)
    work, span = work_span(env.provider.raw, shared=n > 1)
    return {"width": width, "depth": depth, "agents": n, "seed": seed, **r, "tasks": len(env.provider.raw),
            "work": work, "span": span, "brent_rounds": math.ceil(work / n) + span}


def work_span(raw: dict, shared: bool) -> tuple[int, int]:
    """Work (all actions) and span (actions on the longest chain) of a DAG problem, in agent actions. A team
    task reads its parents, computes, submits and stores (FINAL reads and submits); one agent computes and
    submits."""
    def cost(tid):
        reads = len(raw[tid]["deps"]) if shared else 0
        return reads + (1 if tid == "FINAL" else 2 + shared)

    finish: dict[str, int] = {}

    def path(tid):
        if tid not in finish:
            finish[tid] = cost(tid) + max((path(d) for d in raw[tid]["deps"]), default=0)
        return finish[tid]

    return sum(cost(t) for t in raw), max(path(t) for t in raw)


def table(rows: list[dict]) -> str:
    out = ["| family | agents | width x depth | work | span | rounds to solve | Brent's T_N bound | speed-up | "
           "speed-up Brent guarantees |", "|---|---|---|---|---|---|---|---|---|"]
    for fam in dict.fromkeys(r["family"] for r in rows):
        mine = [r for r in rows if r["family"] == fam]
        one = {(r["width"], r["depth"]): r["rounds"] for r in mine if r["agents"] == 1}
        for r in mine:
            base = one.get((r["width"], r["depth"]))
            if base is None:  # scaled family: one agent on the same problem, measured separately
                base = r["single_rounds"]
            out.append(f"| {fam} | {r['agents']} | {r['width']} x {r['depth']} | {r['work']} | {r['span']} | "
                       f"{r['rounds']} | {r['brent_rounds']} | {base / r['rounds']:.2f} | "
                       f"{base / r['brent_rounds']:.2f} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", type=int, nargs="*", default=[1, 2, 4, 8, 16, 32])
    ap.add_argument("--fixed", type=int, nargs=2, default=[16, 4], metavar=("WIDTH", "DEPTH"))
    ap.add_argument("--depth", type=int, default=4, help="depth of the scaled family (width = team size)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rows = []
    for n in a.sizes:
        rows.append({"family": "fixed", **run(*a.fixed, n, a.seed)})
    for n in a.sizes:
        r = run(n, a.depth, n, a.seed)
        r["single_rounds"] = run(n, a.depth, 1, a.seed)["rounds"]
        rows.append({"family": "scaled", **r})
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
