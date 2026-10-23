"""Audit the preserved ad95c03 pilot without running any model or importing newer experiment code."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / "runs/20261021-netscale-pilot"
accounting = json.loads((HERE / "20261021-netscale-pilot-final-accounting.json").read_text())
assert accounting["source_commit"] == "ad95c039c11239ff029e5d36eaaa8b6102ef5677"
assert not accounting["source_status"]
for name, digest in accounting["files"].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name

rows = [json.loads(line) for line in (ROOT / "netscale-pilot/all/runs.jsonl").read_text().splitlines()]
expected = {("peers", f"dag/fixed/n{n}", seed, "network")
            for n in (1, 2, 4, 8) for seed in (100, 101, 102)}
observed = [(r["design"], r["case"], r["seed"], r["route"]) for r in rows]
assert len(observed) == len(set(observed)) == 10
assert set(observed) <= expected
assert all(r["tasks"] == 65 and r["call_budget"] == 915 for r in rows)
assert all(not r["solved"] and r["solved_step"] is None and r["llm_errors"] > 0 for r in rows)

groups = {}
for n in (1, 2, 4, 8):
    rs = [r for r in rows if r["agents"] == n]
    ops = Counter()
    for r in rs:
        ops.update(r["ops"])
    groups[n] = dict(
        runs=len(rs), solved=sum(r["solved"] for r in rs),
        done=[r["done"] for r in rs],
        mean_task_completion=statistics.mean(r["done"] / r["tasks"] for r in rs),
        reference_steps=rs[0]["reference_steps"],
        T=None, closeness=None, eta=None, speedup=None,
        input_tokens=sum(r["input_tokens"] for r in rs),
        output_tokens=sum(r["output_tokens"] for r in rs),
        llm_errors=sum(r["llm_errors"] for r in rs),
        wrong_submissions=sum(r["wrong_submissions"] for r in rs),
        duplicate_work=sum(r["duplicate_work"] for r in rs),
        ops_total=dict(ops), ops_mean={op: count / len(rs) for op, count in ops.items()},
    )

trace_checks = []
for n in (1, 2, 4, 8):
    p = ROOT / f"netscale-pilot/all/traces/peers__dag_fixed_n{n}__100.jsonl.gz"
    with gzip.open(p, "rt") as stream:
        events = [json.loads(line) for line in stream]
    transcript = [e for e in events if e.get("kind") == "transcripts"]
    assert len(transcript) == 1 and len(transcript[0]["members"]) == n
    row = next(r for r in rows if r["agents"] == n and r["seed"] == 100)
    ops = Counter(e["op"] for e in events if e.get("kind") == "op")
    assert dict(ops) == row["ops"], (n, ops, row["ops"])
    trace_checks.append(dict(size=n, seed=100, events=len(events), operations=sum(ops.values()),
                             retained_member_transcripts=n, ops_agree=True))

summary = (ROOT / "netscale-pilot/summary.md").read_text()
assert summary == (ROOT / "netscale-pilot/all/summary.md").read_text()
for n, g in groups.items():
    assert f"| {n} | 16 x 4 | {g['runs']} | 0.00 | - | {g['reference_steps']:.1f} | - | - | - |" in summary

log = (ROOT / "logs/net-netscale-pilot-24729787.out").read_text()
assert "stopped: 10 runs in a row with model errors" in log
assert "APITimeoutError" in log and "57345 input tokens" in log
gpu = next(v["stdout"] for k, v in accounting["accounting"].items() if "ElapsedRaw" in k)
gpu_row = next(line.split("|") for line in gpu.splitlines() if line.startswith("24729787|"))
assert gpu_row[2] == "FAILED" and gpu_row[7] == "1:0"
elapsed = int(gpu_row[6])

result = dict(
    source_commit=accounting["source_commit"], status="failed_incomplete",
    expected_runs=12, recorded_runs=len(rows), solved_runs=0,
    missing=[list(x) for x in sorted(expected - set(observed))],
    groups=groups, trace_checks=trace_checks,
    totals={k: sum(r[k] for r in rows) for k in (
        "input_tokens", "output_tokens", "llm_errors", "wrong_submissions", "duplicate_work", "llm_requests")},
    gpu_elapsed_seconds=elapsed, h100_hours=elapsed / 3600,
    actual_start_toronto=gpu_row[3], actual_end_toronto=gpu_row[4],
    termination="Harness stopped after successive recorded runs with model errors; not a Slurm time-limit termination.",
    interpretation="Transport/context failures contaminate the result. No successful single-agent baseline; T, eta, speedup and USL parameters are unavailable, not zero. Cannot infer mathematical difficulty or coordination failure from this run.",
    remote_original_sha256=accounting["files"],
)
(HERE / "20261021-netscale-pilot-final-summary.json").write_text(json.dumps(result, indent=2) + "\n")

# Preserve the original log locally; the public archive also carries a lossless compressed copy.
raw = (ROOT / "logs/vllm-24729787.log").read_bytes()
compressed = ROOT / "logs/vllm-24729787.log.gz"
compressed.write_bytes(gzip.compress(raw, mtime=0))
assert gzip.decompress(compressed.read_bytes()) == raw
print(json.dumps({"runs": len(rows), "missing": result["missing"], "h100_hours": result["h100_hours"],
                  "totals": result["totals"], "raw_files_verified": len(accounting["files"]),
                  "compressed_vllm_bytes": compressed.stat().st_size}, indent=2))
