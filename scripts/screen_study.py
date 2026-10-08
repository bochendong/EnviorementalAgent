#!/usr/bin/env python
"""Why do cheap quick tests (screens) slow a learner down? A factorial study with the heuristic agent.

Three explanations, each switched on and off separately:

    evidence   screens replace real plantings, so the learner sees fewer real outcomes
               -> count plantings and night outcomes during training
    votes      positive screens are noisy evidence the learner counts (weight 0.3 by default)
               -> --screen-weight 0 (screens never enter the seed) vs 0.3 vs 1
    policy     the agent plants only where screens say "promising", so false negatives keep it away
               from the right soil -> --screen-policy use / ignore (screen, plant as if not) / off

    python scripts/screen_study.py --out results/screen_study            # universes 1 3, ~2 min on a CPU
    python scripts/screen_study.py --out results/screen_study --summary  # print the table again

Rows: one per setting. Training: plantings, outcomes and screens per town, laws learned (correct /
confident) at the end of training. Test: success and share of requests done in held-out towns.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worldseeds.experiment import ExpConfig, run_experiment  # noqa: E402

SETTINGS = [("no screens", None, "off", None)] + [
    (f"error {e:g}, {pol}, weight {w:g}", e, pol, w)
    for e in (0.1, 0.25) for pol in ("use", "ignore") for w in (0.0, 0.3, 1.0)
] + [(f"error {e:g}, off", e, "off", None) for e in (0.1, 0.25)]


def _name(label: str) -> str:
    return label.replace(", ", "_").replace(" ", "")


def run(out: Path, universes, n_train: int, n_test: int, repeats: int) -> None:
    for label, err, pol, w in SETTINGS:
        cfg = ExpConfig(env="board", protocol="compgen", policy="heuristic", conditions=["seed"],
                        universes=universes, n_train=n_train, n_test=n_test, repeats=repeats, max_actions=200,
                        screen_error=err, screen_policy=pol, screen_weight=w, out_dir=str(out / _name(label)))
        run_experiment(cfg)
        print("done", label, flush=True)


def summary(out: Path) -> None:
    def mean(xs):
        xs = list(xs)
        return sum(xs) / len(xs) if xs else float("nan")

    print("| setting | plantings / town | outcomes / town | screens / town | laws correct / confident | "
          "test success | test board |")
    print("|---|---|---|---|---|---|---|")
    for label, *_ in SETTINGS:
        f = out / _name(label) / "episodes.jsonl"
        if not f.exists():
            continue
        rows = [json.loads(x) for x in f.open()]
        tr = [r for r in rows if r["phase"] == "train"]
        te = [r for r in rows if r["phase"] == "test"]
        last = defaultdict(dict)
        for r in tr:
            last[r["chain"]] = r
        plant = [r.get("plantings", 0) for r in tr]
        print(f"| {label} | {mean(plant):.2f} | {mean(r.get('outcomes', 0) for r in tr):.2f} | "
              f"{mean(r.get('screens', 0) for r in tr):.2f} | "
              f"{mean(r['seed_laws_correct'] for r in last.values()):.1f} / "
              f"{mean(r['seed_laws_confident'] for r in last.values()):.1f} | "
              f"{mean(bool(r['success']) for r in te):.2f} | "
              f"{mean(r['board_done'] / r['board_total'] for r in te):.2f} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/screen_study")
    ap.add_argument("--universes", nargs="+", type=int, default=[1, 3])
    ap.add_argument("--n-train", type=int, default=30)
    ap.add_argument("--n-test", type=int, default=16)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--summary", action="store_true", help="only print the table of an earlier run")
    a = ap.parse_args()
    out = Path(a.out)
    if not a.summary:
        run(out, a.universes, a.n_train, a.n_test, a.repeats)
    summary(out)


if __name__ == "__main__":
    main()
