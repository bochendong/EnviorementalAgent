"""The network-scale tables: how far an LLM team is from the scripted reference, and how that changes with
the team's size.

    python -m netagents.netscale results/net/runs/<run>/netscale-pilot      # writes netscale.md there

Runs come from the "netscale" suites (netagents/testset.py): a team of N identical agents ("peers") on a DAG
problem (worldseeds/net/providers/dag.py), time in lockstep rounds (netagents/lockstep.py), and the scripted team's rounds on the same problem
(netagents/scaling.py). Per family and team size:

    solved        share of seeds solved
    T             the team's rounds to solve (solved runs; mean)
    T_lb          the lower bound on any team's rounds, max(W / N, D) (Brent), sharing counted as free
    b = T_lb/T    efficiency against the bound (at most 1)
    T_ref         the scripted team's rounds on the same problems (the fastest of broadcast, store and
                  batch; recomputed with the current netagents/scaling.py)
    sharing       how each run's team passed answers on: store, broadcast (a message per answer) or batch
    a = T_ref/T   how close the team comes to the reference (1: as fast as a scripted team)
    eta = a(N)/a(1)   coordination efficiency: the team's closeness relative to one agent's. On the fixed
                  family it is the team's speed-up over its own single agent divided by the reference's
                  speed-up; below 1, adding agents loses more to coordination than the reference does
    speed-up      T(1)/T(N) on the fixed family

the bulk synchronous reading T = T_bsp + S x L (T_bsp: the fastest layer-by-layer schedule; L: rounds lost
per superstep, S = depth + 1; with predictions
for team sizes not yet run), and the round budget each team's actions went to (compute, the shared store, coordination, waiting,
submissions), with duplicated computations. The Universal Scalability Law (Gunther), S(N) = N / (1 +
sigma (N - 1) + kappa N (N - 1)), is fitted to the fixed family's speed-ups: sigma is contention (work that
does not split), kappa coherence (the cost of keeping each other up to date); kappa > 0 means a team size
beyond which more agents are slower, at N* = sqrt((1 - sigma) / kappa).
"""

from __future__ import annotations

import argparse
import math
import os
import statistics as st
from collections import Counter
from functools import lru_cache

from .evaluate import load_runs

KINDS = {
    "compute": {"apply", "evaluate", "sequence", "simplify", "solve", "rsolve"},
    "store": {"put", "get", "keys"},
    "coordination": {"send", "inbox", "post", "board", "tasks", "status", "who", "claim", "release"},
    "wait": {"wait"},
    "submit": {"submit"},
}


def usl(n: float, sigma: float, kappa: float) -> float:
    return n / (1 + sigma * (n - 1) + kappa * n * (n - 1))


def fit_usl(points: list[tuple[int, float]]) -> tuple[float, float, float] | None:
    """Least squares over a grid: (sigma, kappa, root mean square error), or None with fewer than 3 sizes."""
    if len({n for n, _ in points}) < 3:
        return None
    best = None
    for i in range(201):
        sigma = i / 200
        for j in range(201):
            kappa = (j / 200) ** 2 * 0.5  # finer near 0, up to 0.5
            err = math.sqrt(sum((usl(n, sigma, kappa) - s) ** 2 for n, s in points) / len(points))
            if best is None or err < best[2]:
                best = (sigma, kappa, err)
    return best


@lru_cache(maxsize=None)
def _reference(width: int, depth: int, n: int, seed: int, grain: int) -> int:
    from .scaling import run

    return run(width, depth, n, seed, grain=grain)["rounds"]


def reference(r: dict) -> float:
    """The scripted reference's rounds for a run, from the current netagents/scaling.py (it got stronger
    after runs were recorded: the batch team), or as recorded for runs on the old math DAG."""
    if "grain" not in r:
        return r["reference_steps"]
    return _reference(r["width"], r["depth"], r["agents"], r["seed"], r["grain"])


def sharing(r: dict) -> str:
    """How a run's team passed answers on: through the store, by a message per answer (broadcast) or by
    messages that carry several answers (batch); "none" for one agent."""
    ops, tasks = r.get("ops", {}), r.get("tasks", 0) or 1
    if r["agents"] == 1:
        return "none"
    if ops.get("put", 0) > ops.get("send", 0):
        return "store"
    return "batch" if ops.get("send", 0) < 0.75 * tasks else "broadcast"


def superstep_overhead(rows: list[dict]) -> dict | None:
    """The bulk synchronous reading of a family: T = T_bsp + S x L, with S = depth + 1 supersteps and T_bsp the
    fastest layer-by-layer schedule (netagents/scaling.py layered_bound: whole tasks per layer, the final task
    alone). L, the rounds a team loses per superstep (sharing and synchronising), from solved runs of 2 or more
    agents; L_ref, the scripted reference's.

    The first version took the Brent bound max(W / N, D) as the base. Below the span that bound spreads the
    final task and the layers' remainders over the whole team, so it put 2-4 rounds of unavoidable schedule
    into L (4.2 instead of 3.4 per superstep at grain 4) and predicted 46 rounds for 32 agents, who took 38
    (docs/netscale-predictions.md)."""
    from .scaling import layered_bound

    rs = [r for r in rows if r["agents"] > 1 and r.get("solved_step") and "width" in r]
    if len(rs) < 2:
        return None
    base = {id(r): layered_bound(r["width"], r["depth"], r["agents"], r.get("grain", 1)) for r in rs}
    ls = [(r["solved_step"] - base[id(r)]) / (r["depth"] + 1) for r in rs]
    q1, _, q3 = st.quantiles(ls, n=4)
    return {"L": st.median(ls), "q1": q1, "q3": q3, "runs": len(rs),
            "L_ref": st.median((reference(r) - base[id(r)]) / (r["depth"] + 1) for r in rs)}


def predict(r: dict, n: int, bsp: dict) -> float:
    """T for a team of ``n`` on the problem of run ``r``, from the bulk synchronous reading."""
    from .scaling import layered_bound

    return layered_bound(r["width"], r["depth"], n, r.get("grain", 1)) + (r["depth"] + 1) * bsp["L"]


def rows_by_size(rows: list[dict]) -> dict:
    """{family: {N: [runs]}} for the runs that recorded lockstep time."""
    out: dict = {}
    for r in rows:
        if "steps" not in r:
            continue
        family = r["case"].split("/")[1] if r["case"].count("/") >= 2 else r["case"]
        out.setdefault((r["design"], family), {}).setdefault(r["agents"], []).append(r)
    return out


def table(rows: list[dict]) -> str:
    groups = rows_by_size(rows)
    if not groups:
        return ""
    text = ["## Network scale", ""]
    for (design, family), sizes in sorted(groups.items()):
        ns = sorted(sizes)
        stat = {}
        for n in ns:
            rs = sizes[n]
            ok = [r for r in rs if r["solved"] and r.get("solved_step")]
            t = st.mean(r["solved_step"] for r in ok) if ok else None
            tref = st.mean(reference(r) for r in (ok or rs))
            lb = st.mean(r["lower_bound"] for r in rs) if "lower_bound" in rs[0] else None
            stat[n] = {"runs": len(rs), "solved": len(ok) / len(rs), "T": t, "Tref": tref, "lb": lb,
                       "a": tref / t if t else None, "b": lb / t if t and lb else None,
                       "width": rs[0].get("width"), "depth": rs[0].get("depth"),
                       "per_seed": " ".join(str(r["solved_step"]) if r.get("solved_step") else "x"
                                            for r in sorted(rs, key=lambda r: r["seed"])),
                       "sharing": ", ".join(f"{k} {v}" for k, v in Counter(sharing(r) for r in rs).most_common())}
        a1 = stat.get(1, {}).get("a")
        text += [f"### {design}, {family} family", "",
                 "| agents | problem | runs | solved | T (rounds) | T per seed | sharing | T_lb | b = T_lb/T | T_ref | "
                 "a = T_ref/T | eta = a(N)/a(1) | speed-up |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        points = []
        for n in ns:
            s = stat[n]
            eta = s["a"] / a1 if s["a"] and a1 else None
            sp = (stat[1]["T"] / s["T"]) if family.startswith("fixed") and 1 in stat and stat[1]["T"] and s["T"] else None
            if sp:
                points.append((n, sp))
            f = lambda x, d=2: "-" if x is None else f"{x:.{d}f}"  # noqa: E731
            text.append(f"| {n} | {s['width']} x {s['depth']} | {s['runs']} | {s['solved']:.2f} | {f(s['T'], 1)} | "
                        f"{s['per_seed']} | {s['sharing']} | {f(s['lb'], 0)} | {f(s['b'])} | {s['Tref']:.1f} | {f(s['a'])} | {f(eta)} | {f(sp)} |")
        fit = fit_usl(points) if family.startswith("fixed") else None
        if fit:
            sigma, kappa, err = fit
            peak = math.sqrt((1 - sigma) / kappa) if kappa > 0 else float("inf")
            text += ["", f"Universal Scalability Law fit to the speed-ups: sigma = {sigma:.3f}, kappa = {kappa:.4f} "
                         f"(RMSE {err:.2f}); " + (f"the speed-up peaks near N* = {peak:.1f}." if kappa > 0 else
                                                  "no peak (kappa = 0).")]
        bsp = superstep_overhead([r for n in ns for r in sizes[n]])
        if bsp:
            text += ["", f"Bulk synchronous reading: T = T_bsp + S x L, T_bsp the fastest layer-by-layer schedule, "
                         f"S = depth + 1 supersteps (layers and the final task). The team's overhead per superstep L (median over runs of 2 or more agents, "
                         f"{bsp['runs']} runs): {bsp['L']:.1f} rounds (quartiles {bsp['q1']:.1f}-{bsp['q3']:.1f}); "
                         f"the scripted reference's: {bsp['L_ref']:.1f}."]
            if family.startswith("fixed") and "grain" in sizes[ns[0]][0]:
                r0 = sizes[ns[0]][0]
                pred = [f"N = {n}: {predict(r0, n, bsp):.0f} rounds" for n in (16, 32) if n not in sizes]
                if pred:
                    text += ["", "Predicted from that L (to be checked by runs not yet made): " + "; ".join(pred) + "."]
        text += ["", "Where the team's actions went (mean per run):", "",
                 "| agents | " + " | ".join(KINDS) + " | other | duplicated computations | wrong submissions | "
                 "rounds acted / rounds (mean over agents) |", "|---|" + "---|" * (len(KINDS) + 4)]
        for n in ns:
            rs = sizes[n]
            mix = {k: st.mean(sum(v for op, v in r["ops"].items() if op in ops) for r in rs) for k, ops in KINDS.items()}
            known = set().union(*KINDS.values())
            other = st.mean(sum(v for op, v in r["ops"].items() if op not in known) for r in rs)
            busy = st.mean(st.mean(r["acted"].values()) / max(1, r["steps"]) for r in rs)
            text.append(f"| {n} | " + " | ".join(f"{v:.0f}" for v in mix.values()) + f" | {other:.0f} | "
                        f"{st.mean(r['duplicate_work'] for r in rs):.1f} | "
                        f"{st.mean(r['wrong_submissions'] for r in rs):.1f} | {busy:.2f} |")
        text.append("")
    text += ["T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on "
             "any team's rounds; b: efficiency against it. T_ref: the scripted team of "
             "the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: "
             "coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.", ""]
    return "\n".join(text)


def phases(trace: str, grain: int, width: int) -> dict:
    """Where a run's time went, from its trace: the rounds each layer took (from the last acceptance of the layer
    before to the last of its own) over the fastest it could (ceil(width / N) tasks of grain + 1 actions), and
    the join: from the last layer's end to the final task's acceptance, with what its solver did meanwhile."""
    import gzip
    import json

    with gzip.open(trace, "rt") as f:
        ops = [e for e in map(json.loads, f) if e.get("kind") == "op"]
    agents = {e["agent"] for e in ops}
    done = {}
    for e in ops:
        if e["op"] == "submit" and e["obs"].get("ok"):
            done.setdefault(e["args"]["task"], (e["round"] + 1, e["agent"]))
    depth = 1 + max(int(t[1:].split(".")[0]) for t in done if t != "FINAL")
    ends = [max(r for t, (r, _) in done.items() if t.startswith(f"L{lv}.")) for lv in range(depth)]
    fastest = math.ceil(width / len(agents)) * (grain + 1)
    layers = [b - a - fastest for a, b in zip([0] + ends, ends)]
    fin, solver = done["FINAL"]
    by = Counter(e["op"] for e in ops if e["agent"] == solver and ends[-1] - 1 <= e["round"] < fin)
    return {"agents": len(agents), "layer_excess": layers, "join": fin - ends[-1], "join_excess": fin - ends[-1] - (grain + 1),
            "join_reads": by["get"] + by["inbox"], "join_store_reads": by["get"]}


def phase_table(root: str, rows: list[dict]) -> str:
    """Per team size: mean rounds lost per layer and at the join, over the runs whose traces are under root."""
    by: dict = {}
    for r in rows:
        if not r.get("trace") or "grain" not in r:
            continue
        paths = [os.path.join(d, r["trace"]) for d, _, fs in os.walk(root) if r["trace"] in fs]
        if paths:
            by.setdefault((r["grain"], r["agents"]), []).append(phases(paths[0], r["grain"], r["width"]))
    if not by:
        return ""
    out = ["## Where the time went", "",
           "| grain | agents | runs | rounds lost per layer (mean) | per layer, each run | join: rounds lost | join: store reads |",
           "|---|---|---|---|---|---|---|"]
    for (g, n), ps in sorted(by.items()):
        per = [st.mean(p["layer_excess"][1:]) if len(p["layer_excess"]) > 1 else 0 for p in ps]
        out.append(f"| {g} | {n} | {len(ps)} | {st.mean(per):.1f} | {' '.join(f'{x:.1f}' for x in per)} | "
                   f"{' '.join(str(p['join_excess']) for p in ps)} | {' '.join(str(p['join_store_reads']) for p in ps)} |")
    return "\n".join(out + ["", "Rounds lost: over the fastest a layer can go (whole tasks per agent, no sharing); layer 0, "
                                "which needs no answers, is left out of the mean. The join is the final task, which "
                                "needs every answer of the last layer.", ""])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    a = ap.parse_args()
    rows = load_runs(a.dir)
    text = table(rows)
    if not text:
        raise SystemExit(f"no network-scale runs under {a.dir}")
    text += "\n" + phase_table(a.dir, rows)
    with open(os.path.join(a.dir, "netscale.md"), "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
