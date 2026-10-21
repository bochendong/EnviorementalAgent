"""The network-scale tables: how far an LLM team is from the scripted reference, and how that changes with
the team's size.

    python -m netagents.netscale results/net/runs/<run>/netscale-pilot      # writes netscale.md there

Runs come from the "netscale" suites (netagents/testset.py): a team of N identical agents ("peers") on a DAG
problem, time in lockstep rounds (netagents/lockstep.py), and the scripted team's rounds on the same problem
(netagents/scaling.py). Per family and team size:

    solved        share of seeds solved
    T             the team's rounds to solve (solved runs; mean)
    T_ref         the scripted team's rounds on the same problems
    a = T_ref/T   how close the team comes to the reference (1: as fast as a team that wastes nothing)
    eta = a(N)/a(1)   coordination efficiency: the team's closeness relative to one agent's. On the fixed
                  family it is the team's speed-up over its own single agent divided by the reference's
                  speed-up; below 1, adding agents loses more to coordination than the reference does
    speed-up      T(1)/T(N) on the fixed family

and the round budget each team's actions went to (compute, the shared store, coordination, waiting,
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

from .evaluate import load_runs

KINDS = {
    "compute": {"evaluate", "sequence", "simplify", "solve", "rsolve"},
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
            tref = st.mean(r["reference_steps"] for r in ok) if ok else st.mean(r["reference_steps"] for r in rs)
            stat[n] = {"runs": len(rs), "solved": len(ok) / len(rs), "T": t, "Tref": tref,
                       "a": tref / t if t else None, "width": rs[0].get("width"), "depth": rs[0].get("depth")}
        a1 = stat.get(1, {}).get("a")
        text += [f"### {design}, {family} family", "",
                 "| agents | problem | runs | solved | T (rounds) | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |",
                 "|---|---|---|---|---|---|---|---|---|"]
        points = []
        for n in ns:
            s = stat[n]
            eta = s["a"] / a1 if s["a"] and a1 else None
            sp = (stat[1]["T"] / s["T"]) if family == "fixed" and 1 in stat and stat[1]["T"] and s["T"] else None
            if sp:
                points.append((n, sp))
            f = lambda x, d=2: "-" if x is None else f"{x:.{d}f}"  # noqa: E731
            text.append(f"| {n} | {s['width']} x {s['depth']} | {s['runs']} | {s['solved']:.2f} | {f(s['T'], 1)} | "
                        f"{s['Tref']:.1f} | {f(s['a'])} | {f(eta)} | {f(sp)} |")
        fit = fit_usl(points) if family == "fixed" else None
        if fit:
            sigma, kappa, err = fit
            peak = math.sqrt((1 - sigma) / kappa) if kappa > 0 else float("inf")
            text += ["", f"Universal Scalability Law fit to the speed-ups: sigma = {sigma:.3f}, kappa = {kappa:.4f} "
                         f"(RMSE {err:.2f}); " + (f"the speed-up peaks near N* = {peak:.1f}." if kappa > 0 else
                                                  "no peak (kappa = 0).")]
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
    text += ["T: lockstep rounds until the final task was accepted, over solved runs. T_ref: the scripted team of "
             "the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: "
             "coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.", ""]
    return "\n".join(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    a = ap.parse_args()
    text = table(load_runs(a.dir))
    if not text:
        raise SystemExit(f"no network-scale runs under {a.dir}")
    with open(os.path.join(a.dir, "netscale.md"), "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
