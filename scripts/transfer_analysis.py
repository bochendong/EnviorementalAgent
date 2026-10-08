#!/usr/bin/env python
"""Does SeedVille rank agent configurations the way real benchmarks do?

    python scripts/transfer_analysis.py study.json [--out report.md]

study.json lists the agent configurations (see docs/transfer_study.example.json):

    {"covariate": "static_qa",
     "configs": [
       {"name": "qwen3-8b", "seedville": ["results/qwen3-8b/frontier/..."],
        "labbench": "results/labbench/qwen3-8b.json",            # from scripts/run_labbench.py
        "benchmarks": {"bixbench": 0.21, "static_qa": 0.55}},      # numbers from other harnesses
       ...]}

For every SeedVille skill (worldseeds.transfer.seedville_scores) and every benchmark score it reports, across
configurations: Spearman and Kendall correlations with bootstrap intervals, and the Spearman correlation
with the covariate partialled out (does SeedVille predict beyond, say, raw model strength?).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worldseeds.transfer import bootstrap_ci, kendall, partial_spearman, seedville_scores, spearman  # noqa: E402


def collect(study: dict, base: Path) -> tuple[list[str], dict, dict]:
    names, sv, bench = [], {}, {}
    for c in study["configs"]:
        names.append(c["name"])
        sv[c["name"]] = seedville_scores([base / d for d in c.get("seedville", [])])
        b = {k: v for k, v in c.get("benchmarks", {}).items() if v is not None}
        if c.get("labbench"):
            lb = json.loads((base / c["labbench"]).read_text())
            b["labbench_accuracy"] = lb["overall"]["accuracy"]
            b["labbench_precision"] = lb["overall"]["precision"]
            for cfg, s in lb.get("configs", {}).items():
                b[f"labbench_{cfg}"] = s["accuracy"]
        bench[c["name"]] = b
    return names, sv, bench


def report(study: dict, base: Path, n_boot: int = 2000) -> str:
    names, sv, bench = collect(study, base)
    cov = study.get("covariate")
    lines = ["# SeedVille vs real benchmarks", "",
             f"{len(names)} agent configurations: " + ", ".join(names), "",
             "## Scores", ""]
    skills = sorted({k for s in sv.values() for k in s if k != "episodes"})
    benches = sorted({k for b in bench.values() for k in b})
    lines.append("| config | " + " | ".join(skills + benches) + " |")
    lines.append("|---|" + "---|" * (len(skills) + len(benches)))
    for n in names:
        cells = [f"{sv[n].get(k, float('nan')):.3f}" for k in skills] + \
                [f"{bench[n].get(k, float('nan')):.3f}" for k in benches]
        lines.append(f"| {n} | " + " | ".join(cells) + " |")
    lines += ["", "## Rank correlations across configurations", "",
              "Spearman rho with a 95% bootstrap interval (configurations resampled), Kendall tau-b" +
              (f", and Spearman with `{cov}` partialled out" if cov else "") + ". n = configurations with both.", "",
              "| SeedVille skill | benchmark | n | Spearman [95% CI] | Kendall |" + (" partial |" if cov else ""),
              "|---|---|---|---|---|" + ("---|" if cov else "")]
    for k in skills:
        for b in benches:
            if b == cov:
                continue
            both = [n for n in names if k in sv[n] and b in bench[n] and (not cov or cov in bench[n])]
            if len(both) < 3:
                continue
            x, y = [sv[n][k] for n in both], [bench[n][b] for n in both]
            rho = spearman(x, y)
            if rho != rho:  # one side does not vary across configurations
                lines.append(f"| {k} | {b} | {len(both)} | no variation | |" + (" |" if cov else ""))
                continue
            lo, hi = bootstrap_ci(spearman, [x, y], n=n_boot)
            row = f"| {k} | {b} | {len(both)} | {rho:+.2f} [{lo:+.2f}, {hi:+.2f}] | {kendall(x, y):+.2f} |"
            if cov:
                row += f" {partial_spearman(x, y, [bench[n][cov] for n in both]):+.2f} |"
            lines.append(row)
    lines += ["", "With fewer than about 8 configurations the intervals are wide; read the signs, not the digits."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("study")
    ap.add_argument("--out")
    ap.add_argument("--bootstrap", type=int, default=2000)
    a = ap.parse_args()
    p = Path(a.study)
    text = report(json.loads(p.read_text()), p.parent, a.bootstrap)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
