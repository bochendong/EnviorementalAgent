"""The index of a run directory (slurm/run_all.sh): one README.md with every experiment's state and tables.

    python -m netagents.report $SCRATCH/worldseeds/results/net/runs/20261013-qwen3-8b

For each experiment it lists the runs done per design and copies in the main table (summary.md), the
published findings (hypotheses.json), the fidelity check (fidelity/debate.json) and the scripted
baselines (baselines/baselines.md). Rerun it at any time; it only reads.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter

from .evaluate import load_runs

ORDER = ["baselines", "fidelity", "calibration", "compat-framework", "compat-network", "test", "hard", "heldout",
         "scaling", "topology", "robustness", "org", "faults", "report", "guidance", "memory"]
WHAT = {
    "baselines": "scripted reference teams on every preset and variant (CPU)",
    "fidelity": "multiagent debate on GSM8K: the authors' code vs our port",
    "calibration": "easy and medium presets, dev seeds, a few designs: is the difficulty right for this model?",
    "compat-framework": "compatibility track: the papers' settings, messages through the framework",
    "compat-network": "the compatibility cases with messages through the environment's network",
    "test": "network track, medium difficulty, test seeds (the main table)",
    "hard": "network track, hard difficulty",
    "heldout": "network track, held-out tasks",
    "scaling": "CodeWorld with 2, 4, 8, 16 developers",
    "topology": "math with six network shapes",
    "robustness": "drifting laws, a changing client, an unreliable network",
    "org": "a hierarchy of managers above the workers, 0, 1 or 2 levels",
    "faults": "tool results that are silently wrong or fail loudly, with a check operation",
    "report": "a final report with every answer, scored field by field; with and without a provenance rule",
    "guidance": "the same tasks with and without procedural hints",
    "memory": "ten episodes in a row with a memory that carries over",
}


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def section(run_dir: str, exp: str, jobs: dict) -> list[str]:
    d = os.path.join(run_dir, exp)
    out = [f"## {exp}", "", WHAT.get(exp, ""), ""]
    if jobs.get(exp):
        out += ["Jobs: " + ", ".join(f"{design} `{job}`" for design, job in jobs[exp]), ""]
    if exp == "baselines":
        p = os.path.join(d, "baselines.md")
        out += [_read(p).strip() if os.path.exists(p) else "_not finished_", ""]
        return out
    if exp == "fidelity":
        p = os.path.join(d, "debate.json")
        if not os.path.exists(p):
            return out + ["_not finished_", ""]
        r = json.load(open(p))
        acc = r["accuracy"]
        lo, hi = r["official_gain_95"]
        out += ["| arm | accuracy |", "|---|---|"] + [f"| {k} | {v:.3f} |" for k, v in acc.items()]
        out += ["", f"Official gain {r['official_gain']:+.3f} [95% CI {lo:+.3f}, {hi:+.3f}]; port gain "
                f"{r['port_gain']:+.3f}; within the interval: **{r['port_gain_within_official_interval']}**. "
                f"The paper: {r['paper']['single']:.3f} -> {r['paper']['debate']:.3f} "
                f"({r['paper']['gain']:+.3f}, {r['paper']['model']}). Model here: {r['model']}, n = {r['n']}.", ""]
        return out
    rows = load_runs(d) if os.path.isdir(d) else []
    if not rows:
        return out + ["_no runs yet_", ""]
    n = Counter(r["design"] for r in rows)
    out += ["Runs per design: " + ", ".join(f"{k} {v}" for k, v in n.items()), ""]
    p = os.path.join(d, "summary.md")
    if os.path.exists(p):
        out += [_read(p).split("\n", 2)[-1].strip(), ""]  # without its title
    else:
        out += ["_summary.md is written when the experiment's last job ends_", ""]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    a = ap.parse_args()
    run = os.path.abspath(a.run_dir)
    jobs: dict[str, list] = {}
    plan = os.path.join(run, "plan.tsv")
    if os.path.exists(plan):
        with open(plan) as f:
            for r in csv.DictReader(f, delimiter="\t"):
                jobs.setdefault(r["experiment"], []).append((r["design"], r["job"]))
    present = [e for e in ORDER if os.path.isdir(os.path.join(run, e)) or e in jobs]
    present += sorted(e for e in os.listdir(run) if os.path.isdir(os.path.join(run, e))
                      and e not in present and e != "logs")
    lines = [f"# Run {os.path.basename(run)}", ""]
    for name in ("commit.txt", "env.txt"):
        p = os.path.join(run, name)
        if os.path.exists(p):
            lines += [f"`{name}`:", "", "```", _read(p).strip(), "```", ""]
    for e in present:
        lines += section(run, e, jobs)
    with open(os.path.join(run, "README.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(os.path.join(run, "README.md"))


if __name__ == "__main__":
    main()
