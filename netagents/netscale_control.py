"""The fifth netscale prediction's runs, one slice at a time (docs/netscale-predictions.md).

    python -m netagents.netscale_control status --run results/net/runs/<run>
    python -m netagents.netscale_control next   --run results/net/runs/<run> [--max-usage 70] [--dry-run]

The plan is fixed by the prediction: plain 32 and peers-columns 32 on seeds 100-104, each arm in its own shuffled
order, then plain 16 on seeds 103 and 104. Codex usage is weekly, so the plan is never run in one go. Each `next`
runs one slice and returns:

- slices 1-5: the k-th seed of each 32-agent arm, the two arms at the same time (one team each, so total
  inference concurrency stays 2, as in the earlier runs). This is what keeps the control concurrent: an arm never
  runs ahead of the other by more than one slice.
- slice 6: plain 16 on seeds 103 and 104, two teams at once.

A slice takes about 2.5-3 hours and, at the rate of the earlier 32-agent runs, about 70M tokens (30-37M per team).
If a slice is cut off (Codex usage limit, a closed laptop, Ctrl-C), run `next` again: the interrupted team resumes
from its cached Codex calls, and an arm that already finished its slice waits for the other.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time

ARMS = {  # name: (design, agents, seeds in the order the prediction fixed)
    "plain32": ("peers", 32, [103, 100, 104, 102, 101]),
    "columns32": ("peers-columns", 32, [101, 104, 100, 103, 102]),
    "plain16": ("peers", 16, [103, 104]),
}
PAIRED = ("plain32", "columns32")


def completed(out: Path) -> int:
    path = out / "runs.jsonl"
    return sum(1 for line in path.read_text().splitlines() if line.strip()) if path.exists() else 0


def tokens(out: Path) -> int:
    path = out / "runs.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    return sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in rows)


def next_slice(run: Path) -> list[tuple[str, int]]:
    """The arms to run now, with how many teams each: empty when the plan is done."""
    done = {arm: completed(run / arm) for arm in ARMS}
    k = min(done[a] for a in PAIRED)
    if k < len(ARMS["plain32"][2]):
        return [(arm, 1) for arm in PAIRED if done[arm] == k]
    left = len(ARMS["plain16"][2]) - done["plain16"]
    return [("plain16", left)] if left > 0 else []


def command(run: Path, arm: str, teams: int, model: str, effort: str) -> list[str]:
    design, agents, seeds = ARMS[arm]
    out = run / arm
    cmd = [sys.executable, "-m", "netagents.codex_netscale", "--suite", "netscale-control", "--design", design,
           "--families", "fixed", "--sizes", str(agents), "--grains", "4", "--seeds", *map(str, seeds),
           "--model", model, "--reasoning-effort", effort, "--parallel-runs", str(teams),
           "--inference-concurrency", str(teams), "--max-runs", str(teams), "--out", str(out)]
    return cmd + ["--resume"] if (out / "config.json").exists() else cmd


def codex_weekly_usage() -> float | None:
    """The weekly used_percent in the newest Codex session log, if there is one (best effort)."""
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    logs = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:5] if root.exists() else []
    for log in logs:
        for line in reversed(log.read_text(errors="ignore").splitlines()):
            if "used_percent" not in line:
                continue
            try:
                found = _find_weekly(json.loads(line))
            except json.JSONDecodeError:
                continue
            if found is not None:
                return found
    return None


def _find_weekly(node) -> float | None:
    if isinstance(node, dict):
        if "used_percent" in node and node.get("window_minutes", 0) >= 7 * 24 * 60:
            return float(node["used_percent"])
        node = list(node.values())
    if isinstance(node, list):
        for child in node:
            found = _find_weekly(child)
            if found is not None:
                return found
    return None


def status(run: Path) -> dict:
    arms = {arm: {"completed": completed(run / arm), "planned": len(seeds), "tokens": tokens(run / arm),
                  "state": json.loads((run / arm / "status.json").read_text()).get("status")
                  if (run / arm / "status.json").exists() else "not started"}
            for arm, (_, _, seeds) in ARMS.items()}
    return {"arms": arms, "next": next_slice(run), "codex_weekly_used_percent": codex_weekly_usage()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["status", "next"])
    parser.add_argument("--run", type=Path, required=True, help="the run directory, e.g. results/net/runs/<run>")
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--max-usage", type=float, default=None,
                        help="do not start if the Codex weekly usage is above this percent")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run = args.run.resolve()
    if args.action == "status":
        print(json.dumps(status(run), indent=2))
        return
    todo = next_slice(run)
    if not todo:
        print("The plan is complete.")
        return
    usage = codex_weekly_usage()
    print(f"Codex weekly usage: {'unknown' if usage is None else f'{usage:.0f}%'}")
    if args.max_usage is not None and usage is not None and usage > args.max_usage:
        sys.exit(f"Not starting: weekly usage {usage:.0f}% is above --max-usage {args.max_usage:.0f}%")
    commands = {arm: command(run, arm, teams, args.model, args.reasoning_effort) for arm, teams in todo}
    for arm, cmd in commands.items():
        print(f"{arm}: {' '.join(cmd)}")
    if args.dry_run:
        return
    run.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with (run / "slices.jsonl").open("a") as file:
        file.write(json.dumps({"started": started, "arms": dict(todo), "codex_weekly_used_percent": usage,
                               "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                               "commands": commands}) + "\n")
    procs = {}
    for arm, cmd in commands.items():
        log = open(run / f"{arm}-runner.log", "a")
        # keep a Mac awake while the slice runs (caffeinate exits with the process it watches)
        awake = ["caffeinate", "-i"] if shutil.which("caffeinate") else []
        procs[arm] = subprocess.Popen(awake + cmd, stdout=log, stderr=subprocess.STDOUT)
    codes = {arm: proc.wait() for arm, proc in procs.items()}
    print(json.dumps({"exit_codes": codes, **status(run)}, indent=2))
    if any(codes.values()):
        sys.exit("A slice did not finish; run `next` again to resume it (see <arm>-runner.log)")


if __name__ == "__main__":
    main()
