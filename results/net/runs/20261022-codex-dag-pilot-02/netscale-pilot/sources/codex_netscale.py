"""Run the existing netscale-pilot suite with Codex as its SDK model.

    python -m netagents.codex_netscale --model gpt-6.1-sol --out results/net/runs/codex/netscale-pilot

Keeps Peers, Lockstep, cases, seeds, tool budgets, traces and summary unchanged.
Only inference goes through the logged-in Codex CLI. Completed requests are
cached for exact replay; completed runs are skipped on --resume.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import importlib.metadata
import json
import multiprocessing as mp
from pathlib import Path
import shutil
import subprocess
import time

from agents import ModelSettings

from .codex_cli_model import CodexCLIModel, write_json
from .designs import DESIGNS
from .evaluate import run_one, write_summary
from .testset import SUITES


def execute_job(case, seed, args, gate, stop):
    # A process, not a worker thread: retain the math provider's SIGALRM limits.
    if stop.is_set():
        raise RuntimeError("Experiment stopped after an infrastructure failure")
    out = args.out.resolve()
    n = case.team_size()
    directory = out / "episodes" / f"n{n}-seed{seed}"
    model = CodexCLIModel(directory, args.model, args.reasoning_effort, gate, args.timeout, stop=stop)
    write_json(directory / "status.json", {"status": "running", "agents": n, "seed": seed, "call_budget": case.calls,
                                            "problem": case.opt, "started_epoch": time.time()})
    trace = out / "traces" / f"peers__{case.id.replace('/', '_')}__{seed}.jsonl.gz"
    settings = ModelSettings(tool_choice="required", parallel_tool_calls=False)
    try:
        result = {"model": f"codex-cli/{args.model}", "suite": args.suite,
                  **run_one(DESIGNS["peers"], case, seed, model, settings, case.calls, trace=str(trace))}
        write_json(directory / "result.json", result)
        if result["llm_errors"]:
            raise RuntimeError(f"Model errors in {case.id}, seed {seed}; see {directory / 'result.json'}")
        write_json(directory / "status.json", {"status": "complete", "solved": result["solved"], "done": result["done"],
                                                "tasks": result["tasks"], "steps": result["steps"]})
        return result
    except Exception as error:
        stop.set()
        write_json(directory / "status.json", {"status": "infrastructure_error", "error": str(error)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--reasoning-effort", default="high", choices=["low", "medium", "high", "xhigh"])
    parser.add_argument("--suite", default="netscale-pilot", choices=["netscale-pilot"])
    parser.add_argument("--sizes", nargs="+", type=int, default=[1, 2, 4, 8])
    parser.add_argument("--seeds", nargs="+", type=int, default=[100, 101, 102])
    parser.add_argument("--grains", nargs="+", type=int, default=[1], help="applies per task (the suite has 1 and 4)")
    parser.add_argument("--parallel-runs", type=int, default=2)
    parser.add_argument("--inference-concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not set(args.sizes) <= {1, 2, 4, 8} or not set(args.seeds) <= {100, 101, 102} or not set(args.grains) <= {1, 4}:
        parser.error("Use the pilot's original sizes and test seeds; development checks belong in a separate run")
    if min(args.parallel_runs, args.inference_concurrency, args.timeout) < 1:
        parser.error("Concurrency and timeout must be positive")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=args.resume)
    config = {**vars(args), "out": str(out), "codex_version": subprocess.check_output([shutil.which("codex"), "--version"], text=True).strip(),
              "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "agents_sdk": importlib.metadata.version("openai-agents"), "sympy": importlib.metadata.version("sympy"),
              "protocol": "Original Peers + Lockstep + SUITES['netscale-pilot'] + run_one + write_summary",
              "model_transport": "One Codex JSON tool selection per SDK model response; no outside capabilities"}
    if args.resume:
        previous = json.loads((out / "config.json").read_text())
        for key in ("model", "reasoning_effort", "suite", "sizes", "seeds", "grains", "agents_sdk", "sympy", "git_commit"):
            if previous[key] != config[key]:
                raise ValueError(f"Resume configuration changed: {key}")
    else:
        write_json(out / "config.json", config)
        source = out / "sources"
        source.mkdir()
        for name in ("codex_cli_model.py", "codex_netscale.py", "designs.py", "lockstep.py", "evaluate.py", "testset.py", "tools.py", "scaling.py"):
            shutil.copyfile(Path(__file__).with_name(name), source / name)
    path = out / "runs.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []
    done = {(r["case"], r["seed"]) for r in rows}
    cases = [c for c in SUITES[args.suite] if c.team_size() in args.sizes and c.opt["grain"] in args.grains]
    jobs = [(case, seed) for seed in args.seeds for case in cases if (case.id, seed) not in done]
    planned = len(cases) * len(args.seeds)
    plan = [{"case": case.id, "seed": seed, "agents": case.team_size(), "calls": case.calls, "problem": case.opt} for case, seed in jobs]
    write_json(out / "pending_plan.json", plan)
    write_json(out / "status.json", {"status": "running", "planned_runs": planned, "completed_runs": len(rows)})
    try:
        context = mp.get_context("spawn")
        with context.Manager() as manager:
            gate = manager.BoundedSemaphore(args.inference_concurrency)
            stop = manager.Event()
            with ProcessPoolExecutor(max_workers=args.parallel_runs, mp_context=context) as pool:
                futures = {pool.submit(execute_job, case, seed, args, gate, stop): (case.id, seed) for case, seed in jobs}
                for future in as_completed(futures):
                    result = future.result()
                    rows.append(result)
                    with path.open("a") as file:
                        file.write(json.dumps(result) + "\n")
                    write_summary(str(out), rows, f"netscale-pilot (Codex {args.model}, {args.reasoning_effort})")
                    write_json(out / "status.json", {"status": "running", "planned_runs": planned,
                                                    "completed_runs": len(rows)})
                    print(json.dumps({k: result[k] for k in ("case", "seed", "solved", "done", "tasks", "steps", "reference_steps", "llm_tool_calls")}), flush=True)
    except Exception as error:
        write_json(out / "failure.json", {"error": str(error)})
        write_json(out / "status.json", {"status": "infrastructure_error", "completed_runs": len(rows), "error": str(error)})
        raise
    write_json(out / "status.json", {"status": "complete", "completed_runs": len(rows), "planned_runs": planned})


if __name__ == "__main__":
    main()
