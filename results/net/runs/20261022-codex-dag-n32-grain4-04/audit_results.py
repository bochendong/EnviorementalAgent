"""Recompute the formal pilot audit and usage from original traces and CLI records.

Run from a checkout with the same DAG provider as the archived adf0045 source.
No model calls are made. Development examples and chat tokens are excluded.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import re
import statistics as st
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
SNAPSHOT = tempfile.TemporaryDirectory(prefix="dag-pilot-audit-")
with tarfile.open(ROOT / "source-adf0045.tar.gz") as source:
    source.extractall(SNAPSHOT.name, filter="data")
sys.path.insert(0, SNAPSHOT.name)
from netagents.codex_cli_model import audit as audit_transport
from netagents.netscale import fit_usl
from worldseeds.net.providers.dag import gen, hidden


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def reason(text):
    if text.startswith("already done"):
        return "duplicate_submission"
    if text.startswith("waits for"):
        return "dependencies_not_ready"
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    out = ROOT / "netscale"
    config = json.loads((out / "config.json").read_text())
    assert config["git_commit"] == "adf004518204915f23733333db3897bdc98d3b02"
    assert config["grains"] == [4]
    assert config["suite"] == "netscale" and config["families"] == ["fixed"] and config["sizes"] == [32]
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines() if line]
    expected = {(f"dag/fixed-g4/n{n}", seed) for n in (32,) for seed in (100, 101, 102)}
    present = {(r["case"], r["seed"]) for r in rows}
    assert len(present) == len(rows) and present <= expected
    if not args.allow_incomplete:
        assert present == expected, f"Missing {expected - present}"

    per_run, usage_runs = [], []
    totals = Counter()
    interrupted_totals = Counter()
    for row in sorted(rows, key=lambda r: (r["agents"], r["seed"])):
        assert row["grain"] == 4 and row["llm_errors"] == 0
        tasks = {t["id"]: t for t in gen(row["seed"], row["width"], row["depth"], grain=4)}
        events = [json.loads(line) for line in gzip.open(out / "traces" / row["trace"], "rt")]
        assert events[0]["provider"] == "dag" and events[0]["seed"] == row["seed"]
        accepted, good_applies, store = {}, defaultdict(list), {}
        chains, chain_evidence = {}, {}
        for tid, task in tasks.items():
            xs = [task["start"]]
            for _ in range(4):
                xs.append(hidden(row["seed"], tid, xs[-1], task["salt"]))
            assert len(set(xs)) == 5 and str(xs[-1]) == task["answer"]
            chains[tid] = xs
        hops = defaultdict(dict)
        ops, applies, rejected, provenance = Counter(), Counter(), Counter(), Counter()
        missing, early, wrong_inputs = [], [], []
        for event in events:
            if event.get("kind") != "op":
                continue
            op, params, obs = event["op"], event.get("args", {}), event["obs"]
            ops[op] += 1
            if op == "put" and obs.get("ok"):
                store[params["key"]] = params["value"]
            if op == "apply" and obs.get("ok"):
                tid = params["task"]
                applies[(tid, obs["x"])] += 1
                xs = chains[tid]
                matches = [i for i in range(4) if obs["x"] == xs[i] and obs["f(x)"] == xs[i + 1]]
                if matches:
                    i = matches[0]
                    if i == 0 or i - 1 in hops[tid]:
                        hops[tid].setdefault(i, {"event": event["t"], "agent": event["agent"],
                                                  "input": obs["x"], "output": obs["f(x)"]})
                    if len(hops[tid]) == 4:
                        good_applies[tid].append(event["t"])
                    waiting = [d for d in tasks[tid]["deps"] if d not in accepted]
                    if waiting:
                        early.append({"task": tid, "event": event["t"], "parents_not_yet_accepted": waiting})
                else:
                    wrong_inputs.append({"task": tid, "event": event["t"], "input": obs["x"]})
            if op != "submit":
                continue
            if not obs.get("ok"):
                rejected[reason(obs.get("error", "unknown"))] += 1
                continue
            tid = params["task"]
            value = params.get("artifact")
            if value in (None, ""):
                value = store[params.get("store_key") or params.get("key")]
            text = str(value).strip()
            assert re.fullmatch(r"-?\d+", text) and int(text) == int(tasks[tid]["answer"])
            assert tid not in accepted
            assert all(d in accepted for d in tasks[tid]["deps"])
            if not good_applies[tid]:
                missing.append(tid)
            chain_evidence[tid] = {"accepted_event": event["t"], "accepted_by": event["agent"],
                                   "chain": [hops[tid].get(i) for i in range(4)]}
            accepted[tid] = int(text)
            provenance[event.get("provenance", {}).get("source", "unrecorded")] += 1

        assert dict(ops) == row["ops"]
        assert sum(ops.values()) == row["llm_tool_calls"]
        assert len(accepted) == row["done"] and len(tasks) == row["tasks"] == 65
        assert sum(rejected.values()) == row["wrong_submissions"]
        assert ("FINAL" in accepted) == row["solved"]
        assert not missing, f"Accepted tasks without a preceding valid apply: {missing}"
        assert row["lower_bound"] == max(-(-325 // row["agents"]), 25)
        b = row["lower_bound"] / row["solved_step"] if row["solved"] else None
        assert b is None or b <= 1

        episode = out / "episodes" / f"fixed-g4-n{row['agents']}-seed{row['seed']}"
        usage, attempts, interrupted_usage, interrupted_errors = Counter(), 0, Counter(), Counter()
        interrupted_with_receipt = 0
        successes = 0
        for path in (episode / "calls").glob("*/*/events.jsonl"):
            log = [json.loads(line) for line in path.read_text().splitlines() if line]
            if ".interrupted-" in path.parent.name or not (path.parent / "metadata.json").exists():
                attempts += 1
                receipt_seen = False
                for entry in log:
                    if entry.get("type") == "turn.completed":
                        interrupted_usage.update(entry["usage"])
                        receipt_seen = True
                    if entry.get("type") == "error":
                        interrupted_errors[entry.get("message", "unknown")] += 1
                interrupted_with_receipt += receipt_seen
                continue
            receipt = audit_transport(log)
            metadata = json.loads((path.parent / "metadata.json").read_text())
            assert metadata["usage"] == receipt and metadata["tool_audit"] == "passed"
            usage.update(receipt)
            successes += 1
        assert successes == row["llm_requests"]
        assert usage["input_tokens"] == row["input_tokens"] and usage["output_tokens"] == row["output_tokens"]
        interrupted_totals.update(interrupted_usage)
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        totals.update(usage)
        usage_runs.append({"case": row["case"], "agents": row["agents"], "seed": row["seed"],
                           "successful_requests": successes, "usage": dict(usage),
                           "interrupted_attempts": attempts, "interrupted_attempts_without_usage": attempts - interrupted_with_receipt,
                           "interrupted_errors": dict(interrupted_errors),
                           "interrupted_usage_receipts": dict(interrupted_usage)})
        per_run.append({"case": row["case"], "agents": row["agents"], "seed": row["seed"],
                        "solved": row["solved"], "correctly_accepted_tasks": len(accepted),
                        "accepted_tasks_with_preceding_valid_apply": len(accepted) - len(missing),
                        "missing_apply_tasks": missing, "accepted_task_chain_evidence": chain_evidence, "successful_apply_calls": sum(applies.values()),
                        "duplicate_apply_calls": sum(v - 1 for v in applies.values()),
                        "native_duplicate_work": row["duplicate_work"], "wrong_input_apply_calls": wrong_inputs,
                        "valid_apply_before_parent_acceptance": early,
                        "submission_attempts": ops["submit"], "rejected_submissions": dict(rejected),
                        "accepted_submission_provenance": dict(provenance), "steps": row["steps"],
                        "lower_bound": row["lower_bound"], "b": b})

    by_size = []
    baseline = [json.loads(line) for line in (ROOT / "baseline-grain4-runs.jsonl").read_text().splitlines() if line]
    base = [r for r in baseline if r["agents"] == 1 and r["solved"]]
    assert len(base) == 3 and all(r["solved_step"] == 330 and r["reference_steps"] == 325 for r in base)
    t1 = st.mean(r["solved_step"] for r in base) if base else None
    ref1 = st.mean(r["reference_steps"] for r in base) if base else None
    for n in (32,):
        rs = [r for r in rows if r["agents"] == n]
        if not rs:
            continue
        solved = [r for r in rs if r["solved"]]
        t = st.mean(r["solved_step"] for r in solved) if solved else None
        ref = st.mean(r["reference_steps"] for r in solved) if solved else None
        lb = max(-(-325 // n), 25)
        by_size.append({"agents": n, "runs": len(rs), "solved": len(solved),
                        "mean_rounds": t, "lower_bound": lb, "b": lb / t if t else None,
                        "mean_reference_rounds": ref, "a": ref / t if t else None,
                        "eta": (ref / t) / (ref1 / t1) if t and t1 else None,
                        "speedup": t1 / t if t and t1 else None,
                        "mean_tool_calls": st.mean(r["llm_tool_calls"] for r in rs),
                        "mean_total_tokens": st.mean(r["input_tokens"] + r["output_tokens"] for r in rs),
                        "mean_coordination_operations": st.mean(sum(r["ops"].get(k, 0) for k in
                            ("send", "inbox", "post", "board", "tasks", "status", "who", "claim", "release")) for r in rs)})
    fit = fit_usl([(s["agents"], s["speedup"]) for s in by_size if s["speedup"]])
    frozen = json.loads((ROOT / "preregistration.json").read_text())
    assert frozen["source_commit"] == config["git_commit"]
    assert frozen["prediction_file_sha256"] == __import__("hashlib").sha256((ROOT / "predictions-adf0045.md").read_bytes()).hexdigest()
    complete_solved = len(rows) == 3 and all(r["solved"] for r in rows)
    observed_t = by_size[0]["mean_rounds"] if by_size else None
    prediction_check = {"frozen_BSP_T": frozen["BSP_T"], "frozen_BSP_range": frozen["BSP_quartile_range"],
                        "frozen_USL_T": frozen["USL_T"], "all_three_runs_solved": complete_solved,
                        "mean_solved_T": observed_t,
                        "observed_mean_L": (observed_t - 25) / 5 if observed_t else None,
                        "absolute_error_BSP": abs(observed_t - 46) if complete_solved else None,
                        "absolute_error_USL": abs(observed_t - 37) if complete_solved else None,
                        "T32_vs_T16": "Unavailable: 16-agent runs were deferred before launch",
                        "interpretation": "Report observed distances and all failures; near/far lack a prespecified formal decision threshold. Do not refit the pre-run predictions using these observations."}
    report = {"complete": present == expected, "source_commit": config["git_commit"],
              "formal_runs": len(rows), "solved_runs": sum(r["solved"] for r in rows),
              "correctly_accepted_tasks": sum(r["done"] for r in rows),
              "all_accepted_tasks_have_preceding_valid_apply": True,
              "all_observed_b_at_most_one": all(r["b"] is None or r["b"] <= 1 for r in per_run),
              "by_team_size": by_size, "runs": per_run,
              "prediction_check": prediction_check,
              "baseline": {"data_commit": "70735615d14072f491630dbc610a55c5d551bfb2", "model_source_commit": "1953d3c0f4cd7a213661e518b70bde66066fc676", "T1": t1, "Tref1": ref1, "usage_excluded": True},
              "usl_fit": dict(zip(("sigma", "kappa", "rmse"), fit)) if fit else None,
              "limits": "Three seeds, 32 agents, fixed grain4 DAG only. Full four-edge apply chains audited for accepted tasks; integer verifier does not enforce query counts for arbitrary strategies. Single-agent baseline from the prior grain4 run; new run usage excludes that baseline and all development/chat use. No 16-agent result yet. Predictions frozen before launch under adf0045; do not infer a universal law or tune on these seeds."}

    interrupted_totals["total_tokens"] = interrupted_totals["input_tokens"] + interrupted_totals["output_tokens"]
    all_receipted = totals + interrupted_totals
    usage_report = {"complete": present == expected, "formal_runs": len(rows), "totals": dict(totals),
                    "interrupted_usage_totals": dict(interrupted_totals),
                    "all_receipted_usage_totals": dict(all_receipted),
                    "attempts_without_usage_receipt": sum(r["interrupted_attempts_without_usage"] for r in usage_runs),
                    "counting": "total_tokens = input_tokens + output_tokens. Cached input and reasoning output are subsets, not extra tokens.",
                    "scope": "totals counts each successful formal cached request once, not each replay. Interrupted or unused failed directories and any usage receipts are separate; all_receipted_usage_totals adds these receipts. Failures without receipts have unknown usage. Development, coding/report/chat usage excluded.",
                    "runs": usage_runs}
    save(out / "audit.json", report)
    save(out / "usage.json", usage_report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("runs", "limits")}, ensure_ascii=False, indent=2))
    print("USAGE", dict(totals))


if __name__ == "__main__":
    main()
