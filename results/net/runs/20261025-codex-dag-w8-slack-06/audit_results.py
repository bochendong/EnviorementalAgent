"""Recompute the formal pilot audit and usage from original traces and CLI records.

Run from a checkout with the same DAG provider as the archived 4f768d7 source.
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
with tarfile.open(ROOT / "source-4f768d7.tar.gz") as source:
    source.extractall(SNAPSHOT.name, filter="data")
sys.path.insert(0, SNAPSHOT.name)
from netagents.codex_cli_model import audit as audit_transport
from netagents.netscale import phases, sharing
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
    out = ROOT / "netscale-slack"
    config = json.loads((out / "config.json").read_text())
    assert config["git_commit"] == "4f768d7760bc82454e79402158c8803e80e491d2"
    assert config["grains"] == [4]
    assert config["suite"] == "netscale-slack" and config["families"] == ["w8"] and config["sizes"] == [8, 16]
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines() if line]
    expected = {(f"dag/w8-g4/n{n}", seed) for n in (8, 16) for seed in (100, 101, 102)}
    present = {(r["case"], r["seed"]) for r in rows}
    assert len(present) == len(rows) and present <= expected
    if not args.allow_incomplete:
        assert present == expected, f"Missing {expected - present}"

    per_run, usage_runs, coordination = [], [], []
    totals = Counter()
    interrupted_totals = Counter()
    for row in sorted(rows, key=lambda r: (r["agents"], r["seed"])):
        assert row["grain"] == 4 and row["width"] == 8 and row["depth"] == 4 and row["llm_errors"] == 0
        assert row["call_budget"] == {8: 1344, 16: 2208}[row["agents"]]
        assert row["reference_steps"] == {8: 33, 16: 31}[row["agents"]]
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
        assert len(accepted) == row["done"] and len(tasks) == row["tasks"] == 33
        assert sum(rejected.values()) == row["wrong_submissions"]
        assert ("FINAL" in accepted) == row["solved"]
        assert not missing, f"Accepted tasks without a preceding valid apply: {missing}"
        assert row["lower_bound"] == max(-(-165 // row["agents"]), 25)
        b = row["lower_bound"] / row["solved_step"] if row["solved"] else None
        assert b is None or b <= 1

        episode = out / "episodes" / f"w8-g4-n{row['agents']}-seed{row['seed']}"
        usage, attempts, interrupted_usage, interrupted_errors = Counter(), 0, Counter(), Counter()
        interrupted_with_receipt = 0
        successes = 0
        for directory in sorted((episode / "calls").glob("*/*")):
            if not directory.is_dir():
                continue
            path = directory / "events.jsonl"
            log = [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []
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
        owners = {e["args"]["task"]: e["agent"] for e in events if e.get("op") == "submit" and e["obs"].get("ok")}
        layer_owners = [[owners.get(f"L{lv}.{i}") for i in range(8)] for lv in range(4)]
        sets = [set(x) - {None} for x in layer_owners]
        alternating = all(len(x) == 8 for x in sets) and sets[0] == sets[2] and sets[1] == sets[3] and sets[0].isdisjoint(sets[1])
        phase = phases(str(out / "traces" / row["trace"]), 4, 8) if row["solved"] else None
        if phase:
            assert len(phase["layer_excess"]) == 4 and phase["agents"] == row["agents"]
            assert 20 + sum(phase["layer_excess"]) + phase["join"] == row["solved_step"]
        coordination.append({"case": row["case"], "seed": row["seed"], "layer_owners_by_task_index": layer_owners,
                             "alternating_disjoint_layer_owners": alternating,
                             "note": "Ownership pattern is descriptive trace evidence, not a newly registered statistical test or causal intervention.",
                             "messages": [e for e in events if e.get("op") == "send"]})
        per_run.append({"phase": phase, "mean_handoff_loss": st.mean(phase["layer_excess"][1:]) if phase else None,
                        "alternating_disjoint_layer_owners": alternating, "sharing_heuristic": sharing(row),
                        "ops": dict(ops), "llm_errors": row["llm_errors"], "context_trims": row["context_trims"],
                        "peak_context": row["peak_context"], "overflows": sum(m["overflows"] for m in row["members"]),"case": row["case"], "agents": row["agents"], "seed": row["seed"],
                        "solved": row["solved"], "correctly_accepted_tasks": len(accepted),
                        "accepted_tasks_with_preceding_valid_apply": len(accepted) - len(missing),
                        "missing_apply_tasks": missing, "accepted_task_chain_evidence": chain_evidence, "successful_apply_calls": sum(applies.values()),
                        "duplicate_apply_calls": sum(v - 1 for v in applies.values()),
                        "native_duplicate_work": row["duplicate_work"], "wrong_input_apply_calls": wrong_inputs,
                        "valid_apply_before_parent_acceptance": early,
                        "submission_attempts": ops["submit"], "rejected_submissions": dict(rejected),
                        "accepted_submission_provenance": dict(provenance), "steps": row["steps"],
                        "lower_bound": row["lower_bound"], "b": b})

    frozen = json.loads((ROOT / "preregistration.json").read_text())
    import hashlib
    assert frozen["execution_source_commit"] == config["git_commit"]
    assert frozen["prediction_file_sha256"] == hashlib.sha256((ROOT / frozen["prediction_file"]).read_bytes()).hexdigest()
    assert frozen["predicted_T"] == {"8": 42, "16": 37}
    assert frozen["predicted_handoff_rounds_per_layer"] == {"8": 4.5, "16": 2.7}
    by_size = []
    for n in (8, 16):
        rs = [r for r in rows if r["agents"] == n]
        ar = [r for r in per_run if r["agents"] == n]
        if not rs:
            continue
        solved = [r for r in rs if r["solved"]]
        t = st.mean(r["solved_step"] for r in solved) if solved else None
        losses = [r["mean_handoff_loss"] for r in ar if r["mean_handoff_loss"] is not None]
        by_size.append({"agents": n, "runs": len(rs), "solved": len(solved), "mean_rounds": t,
                        "lower_bound": 25, "layered_bound": 25, "b": 25 / t if t else None,
                        "reference_steps": {8: 33, 16: 31}[n], "a": {8: 33, 16: 31}[n] / t if t else None,
                        "eta": None, "solo_speedup": None,
                        "mean_handoff_loss": st.mean(losses) if losses else None,
                        "mean_join_excess": st.mean(r["phase"]["join_excess"] for r in ar if r["phase"]) if solved else None,
                        "mean_tool_calls": st.mean(r["llm_tool_calls"] for r in rs),
                        "mean_total_tokens": st.mean(r["input_tokens"] + r["output_tokens"] for r in rs),
                        "mean_all_receipted_tokens": st.mean(r["usage"]["total_tokens"] + r["interrupted_usage_receipts"].get("input_tokens", 0) + r["interrupted_usage_receipts"].get("output_tokens", 0) for r in usage_runs if r["agents"] == n),
                        "predicted_T": frozen["predicted_T"][str(n)],
                        "signed_T_error": t - frozen["predicted_T"][str(n)] if t else None})
    paired = []
    for seed in (100, 101, 102):
        pair = {r["agents"]: r for r in per_run if r["seed"] == seed}
        raw = {r["agents"]: r for r in rows if r["seed"] == seed}
        if set(pair) != {8, 16}:
            continue
        both_solved = all(raw[n]["solved"] for n in (8, 16))
        t8, t16 = (raw[n]["solved_step"] if raw[n]["solved"] else None for n in (8, 16))
        h8, h16 = (pair[n]["mean_handoff_loss"] for n in (8, 16))
        paired.append({"seed": seed, "T8": t8, "T16": t16, "both_solved": both_solved,
                       "T16_minus_T8": t16 - t8 if both_solved else None,
                       "T8_over_T16": t8 / t16 if both_solved else None,
                       "handoff8": h8, "handoff16": h16,
                       "handoff16_minus_handoff8": h16 - h8 if both_solved else None,
                       "T16_less_than_T8": t16 < t8 if both_solved else None,
                       "handoff16_less_than_handoff8": h16 < h8 if both_solved else None,
                       "alternating_crews16": pair[16]["alternating_disjoint_layer_owners"]})
    complete = present == expected
    prediction = {"frozen_T": frozen["predicted_T"],
                  "frozen_handoff_loss": frozen["predicted_handoff_rounds_per_layer"], "paired_seeds": paired,
                  "all_seeds_16_faster": len(paired) == 3 and all(x["T16_less_than_T8"] is True for x in paired),
                  "all_seeds_16_lower_handoff_loss": len(paired) == 3 and all(x["handoff16_less_than_handoff8"] is True for x in paired),
                  "all_16_runs_have_alternating_disjoint_owners": len(paired) == 3 and all(x["alternating_crews16"] for x in paired),
                  "interpretation": "Direction, approximate numerical predictions and trace evidence reported separately. Three paired seed labels; no formal significance threshold or causal intervention. No prediction refit."}
    report = {"complete": complete, "source_commit": config["git_commit"], "formal_runs": len(rows),
              "solved_runs": sum(r["solved"] for r in rows), "correctly_accepted_tasks": sum(r["done"] for r in rows),
              "all_accepted_tasks_have_preceding_valid_apply": True,
              "all_observed_b_at_most_one": all(r["b"] is None or r["b"] <= 1 for r in per_run),
              "by_team_size": by_size, "runs": per_run, "prediction_check": prediction,
              "limits": "Only width8/depth4/grain4, three seeds, sizes8/16. No width8 single-agent LLM baseline: eta and solo speedup unavailable. Integer verifier does not require queries for arbitrary strategies; actual four-step chains audited. Communication labels are heuristic; examine messages and accepted ownership. Historical, development and chat usage excluded."}
    interrupted_totals["total_tokens"] = interrupted_totals["input_tokens"] + interrupted_totals["output_tokens"]
    usage_report = {"complete": complete, "formal_runs": len(rows), "totals": dict(totals),
                    "interrupted_usage_totals": dict(interrupted_totals),
                    "all_receipted_usage_totals": dict(totals + interrupted_totals),
                    "attempts_without_usage_receipt": sum(r["interrupted_attempts_without_usage"] for r in usage_runs),
                    "counting": "total_tokens=input_tokens+output_tokens; cached input and reasoning output are subsets. Each original successful request counted once, not per replay. Failed requests without receipts have unknown usage. Development, coding, chat and historical experiments excluded.",
                    "runs": usage_runs}
    save(out / "audit.json", report)
    save(out / "usage.json", usage_report)
    save(out / "coordination-evidence.json", {"runs": coordination})
    print(json.dumps({k:v for k,v in report.items() if k not in ("runs", "limits")}, ensure_ascii=False, indent=2))
    print("USAGE", dict(totals))


if __name__ == "__main__":
    main()

