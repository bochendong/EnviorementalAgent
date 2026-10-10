"""Climb the ladder from the two-machine tutorial to the full town, one new difficulty per level, recorded.

    python scripts/run_ladder.py --out results/ladder/try1                 # all levels, stop at the first failure
    python scripts/run_ladder.py --levels 4 5 --no-stop --out results/ladder/l45
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worldseeds.codeworld.ladder import LEVELS, LadderConfig, run  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", nargs="+", type=int, default=[11, 22, 33])
    ap.add_argument("--levels", nargs="+", type=int, default=[lv.n for lv in LEVELS])
    ap.add_argument("--no-stop", action="store_true", help="run every level even after one fails")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    run(LadderConfig(tuple(a.seeds), tuple(a.levels), a.out, stop=not a.no_stop))
