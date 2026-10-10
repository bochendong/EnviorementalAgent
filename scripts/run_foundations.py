"""Run matched gates/calculator/world comparisons before multi-agent experiments."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worldseeds.codeworld.foundations import CONDITIONS, FoundationConfig, run


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", nargs="+", type=int, default=[11, 22, 33])
    ap.add_argument("--conditions", nargs="+", choices=[c.name for c in CONDITIONS],
                    default=[c.name for c in CONDITIONS])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    run(FoundationConfig(args.out, tuple(args.seeds), tuple(args.conditions)))
