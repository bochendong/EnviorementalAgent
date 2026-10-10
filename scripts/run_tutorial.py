"""Run the small two-machine Qwen action/communication diagnostic, with full recording."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worldseeds.codeworld.tutorial import TutorialConfig, run

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", nargs="+", type=int, default=[11, 22, 33])
    ap.add_argument("--budget", type=int, default=32)
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not args.seeds or len(set(args.seeds)) != len(args.seeds):
        ap.error("seeds must be nonempty and unique")
    run(TutorialConfig(tuple(args.seeds), args.budget, args.max_turns, args.out))
