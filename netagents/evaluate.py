"""Run agent designs on a test suite and tabulate the results.

    python -m netagents.evaluate --suite dev --designs react centralized decentralized
    python -m netagents.evaluate --suite test --designs all --out results/net/eval/qwen3-8b
    NETAGENTS_PY_AUTOGEN=.../venv-autogen/bin/python python -m netagents.evaluate --designs everything

Every design on a case gets the same total LLM tool calls and environment budget (netagents/testset.py).
Per run it records: solved, the share of tasks done, environment actions, LLM tool calls and tokens,
messages, board posts and store writes, and failure signals in the spirit of MAST (Cemri et al.,
"Why Do Multi-Agent LLM Systems Fail?", NeurIPS 2025 D&B):

    duplicate_work       the same costly operation with the same arguments by more than one agent
                         (system design: step repetition)
    unread_messages      messages delivered but never read by the end (inter-agent misalignment)
    wrong_submissions    submissions the environment rejected (task verification)
    stopped_early        members that stopped with budget left while the problem was unsolved

The designs' messages travel as the case's track says (the framework on the compatibility track, the
environment's network on the network track; --route overrides it, e.g. to run the compatibility cases
through the network). Designs that run inside a framework (netagents/frameworks) always use their own.

On the suites with published findings (testset.HYPOTHESES) it checks each one: the paired difference of
the two designs over seeds, a 95% bootstrap interval, and whether the finding is reproduced (the interval
lies on the published side of zero), contradicted (on the other side) or inconclusive.

Writes runs.jsonl, summary.md and (where there are findings to check) hypotheses.json to --out. Runs
already in --out/runs.jsonl are skipped, so a job that ran out of time can be resubmitted as it was.
``--summarize DIR`` writes summary.md and hypotheses.json for every runs.jsonl under DIR (e.g. one per
design, from parallel jobs) without running anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics as st
from collections import Counter
from dataclasses import replace

from .client import LocalEnv
from .designs import DESIGNS
from .frameworks import FRAMEWORK_DESIGNS
from .fidelity import bootstrap
from .testset import CALLS_PER_MEMBER, HYPOTHESES, SUITES

CHEAP = {"status", "who", "tasks", "inbox", "board", "keys", "get", "wait", "ls", "read", "log", "made",
         "signatures", "props", "similarity"}


def failure_signals(raw) -> dict:
    ops = [e for e in raw.events if e.get("kind") == "op"]
    by_call: dict[tuple, set] = {}
    for e in ops:
        if e["op"] in CHEAP or e["op"] in ("send", "post", "put", "submit", "claim", "release", "transfer"):
            continue
        if e["obs"].get("ok"):
            by_call.setdefault((e["op"], json.dumps(e.get("args"), sort_keys=True)), set()).add(e["agent"])
    return {"duplicate_work": sum(len(a) - 1 for a in by_call.values() if len(a) > 1),
            "unread_messages": sum(len(a.mail) for a in raw.agents.values()) + len(raw.transit),
            "wrong_submissions": sum(1 for e in ops if e["op"] == "submit" and not e["obs"].get("ok")),
            "stopped_early": 0 if raw.solved else sum(1 for a in raw.agents.values() if a.budget > 0)}


def save_trace(raw, path: str):
    """Every event of a run (gzipped JSON lines): what each agent did and what it saw."""
    import gzip

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt") as f:
        for e in raw.events:
            f.write(json.dumps(e, default=str) + "\n")


def run_one(design, case, seed, model, settings, calls, route: str | None = None, trace: str = "") -> dict:
    route = route or case.route
    if design.network_route:  # a copy: the registry's designs stay as they are
        design = replace(design, route=route)
    raw = case.build(design.variant)
    raw.reset(seed)
    reports = asyncio.run(design.play(LocalEnv(raw), model, settings, calls))
    chan = design.chan.report() if hasattr(design, "chan") else {"route": "framework"}
    if trace:
        save_trace(raw, trace)
    m = raw.metrics()
    msgs = Counter(e["op"] for e in raw.events if e.get("kind") == "op" and e["obs"].get("ok"))
    ops = Counter(e["op"] for e in raw.events if e.get("kind") == "op")
    failed = Counter(e["op"] for e in raw.events if e.get("kind") == "op" and not e["obs"].get("ok"))
    return {"design": design.name, "case": case.id, "seed": seed, "variant": design.variant, "call_budget": calls,
            "agents": len(raw.agents), "solved": m["solved"], "done": m["done"], "tasks": m["tasks"],
            "completion": round(m["done"] / max(1, m["tasks"]), 3), "actions": m["actions"], "rounds": m["rounds"],
            "llm_tool_calls": sum(r["tool_calls"] for r in reports),
            "llm_requests": sum(r["llm_requests"] for r in reports),
            "input_tokens": sum(r["input_tokens"] for r in reports),
            "output_tokens": sum(r["output_tokens"] for r in reports),
            "messages": msgs["send"], "posts": msgs["post"], "store_writes": msgs["put"],
            "route": chan["route"] if design.network_route else "framework", "channel": chan,
            **failure_signals(raw), "ops": dict(ops), "failed_ops": dict(failed),
            "llm_errors": sum(r.get("errors", 0) for r in reports),
            "context_trims": sum(r.get("trims", 0) for r in reports),
            "peak_context": max([r.get("peak_context", 0) for r in reports] or [0]),
            "trace": os.path.basename(trace) if trace else "", "members": reports}


def summarize(rows: list[dict]) -> str:
    cases = list(dict.fromkeys(r["case"] for r in rows))
    designs = list(dict.fromkeys(r["design"] for r in rows))
    out = ["| design | " + " | ".join(cases) + " | mean completion | tokens (k) | wrong subm. | dup. work |",
           "|---|" + "---|" * (len(cases) + 4)]
    for d in designs:
        mine = [r for r in rows if r["design"] == d]
        cells = []
        for c in cases:
            rs = [r for r in mine if r["case"] == c]
            cells.append(f"{st.mean(r['solved'] for r in rs):.2f} ({st.mean(r['completion'] for r in rs):.2f})"
                         if rs else "-")
        out.append(f"| {d} | " + " | ".join(cells) +
                   f" | {st.mean(r['completion'] for r in mine):.2f}"
                   f" | {st.mean(r['input_tokens'] + r['output_tokens'] for r in mine) / 1000:.0f}"
                   f" | {st.mean(r['wrong_submissions'] for r in mine):.1f}"
                   f" | {st.mean(r['duplicate_work'] for r in mine):.1f} |")
    return "\n".join(out) + "\n\nEach cell: share of seeds solved (share of tasks done).\n"


def diagnostics(rows: list[dict]) -> str:
    """Per design: how runs went wrong (LLM errors, trimmed context, submissions) and the most used tools."""
    out = ["| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | "
           "most used operations |", "|---|---|---|---|---|---|---|"]
    for d in dict.fromkeys(r["design"] for r in rows):
        mine = [r for r in rows if r["design"] == d]
        ops = Counter()
        for r in mine:
            ops.update(r.get("ops", {}))
        errs = sum(1 for r in mine if r.get("llm_errors") or any(m.get("error") for m in r.get("members", [])))
        top = ", ".join(f"{k} {v / len(mine):.0f}" for k, v in ops.most_common(5)) or "(not recorded)"
        out.append(f"| {d} | {len(mine)} | {errs} | {st.mean(r.get('context_trims', 0) for r in mine):.1f} | "
                   f"{max(r.get('peak_context', 0) for r in mine) / 1000:.0f} | "
                   f"{st.mean(r.get('done', 0) + r['wrong_submissions'] for r in mine):.1f} | {top} |")
    return "\n## Diagnostics\n\n" + "\n".join(out) + "\n\nOperations: mean calls per run.\n"


def check_hypotheses(rows: list[dict]) -> list[dict]:
    """Each published finding whose two designs ran on its case: the paired difference over seeds."""
    out = []
    for h in HYPOTHESES:
        a = {r["seed"]: r[h.metric] for r in rows if r["design"] == h.design and r["case"] == h.case}
        b = {r["seed"]: r[h.metric] for r in rows if r["design"] == h.baseline and r["case"] == h.case}
        common = sorted(set(a) & set(b))
        if not common:
            continue
        x, y = [float(a[s]) for s in common], [float(b[s]) for s in common]
        lo, hi = bootstrap(x, y)
        diff = (sum(x) - sum(y)) / len(common)
        verdict = ("reproduced" if (lo > 0 if h.expect > 0 else hi < 0) else
                   "contradicted" if (hi < 0 if h.expect > 0 else lo > 0) else "inconclusive")
        out.append({"design": h.design, "baseline": h.baseline, "case": h.case, "metric": h.metric,
                    "expect": "+" if h.expect > 0 else "-", "seeds": len(common), "difference": round(diff, 4),
                    "ci95": [round(lo, 4), round(hi, 4)], "verdict": verdict, "source": h.source})
    return out


def hypotheses_markdown(checks: list[dict]) -> str:
    if not checks:
        return ""
    rows = ["| case | design − baseline | published | difference [95% CI] | seeds | verdict |",
            "|---|---|---|---|---|---|"]
    for c in checks:
        rows.append(f"| {c['case']} | {c['design']} − {c['baseline']} | {c['expect']} | {c['difference']:+.3f} "
                    f"[{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}] | {c['seeds']} | {c['verdict']} |")
    sources = "\n".join(f"- {s}" for s in dict.fromkeys(c["source"] for c in checks))
    return "\n## Published findings\n\n" + "\n".join(rows) + "\n\nSources:\n" + sources + "\n"


def load_runs(root: str) -> list[dict]:
    """Every run in every runs.jsonl under ``root`` (a directory) or in ``root`` (a file)."""
    paths = [root] if os.path.isfile(root) else sorted(
        os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f == "runs.jsonl")
    rows = []
    for p in paths:
        with open(p) as f:
            rows += [json.loads(line) for line in f if line.strip()]
    return rows


def write_summary(out: str, rows: list[dict], title: str) -> str:
    checks = check_hypotheses(rows)
    if checks:
        with open(os.path.join(out, "hypotheses.json"), "w") as f:
            json.dump(checks, f, indent=1)
    text = summarize(rows) + hypotheses_markdown(checks) + diagnostics(rows)
    with open(os.path.join(out, "summary.md"), "w") as f:
        f.write(f"# {title}\n\n" + text)
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--summarize", metavar="DIR", help="only tabulate the runs under DIR")
    ap.add_argument("--suite", default="dev", choices=sorted(SUITES))
    ap.add_argument("--designs", nargs="*", default=["all"])
    ap.add_argument("--cases", nargs="*", default=None, help="only these case ids")
    ap.add_argument("--seeds", type=int, default=None, help="only the first N seeds of each case")
    ap.add_argument("--calls-per-member", type=int, default=CALLS_PER_MEMBER)
    ap.add_argument("--traces", type=int, default=1, help="save every event of the first N seeds of each case")
    ap.add_argument("--route", choices=["case", "framework", "network"], default="case",
                    help="how the designs' messages travel (default: as the case's track says)")
    ap.add_argument("--out", default="results/net/eval")
    a = ap.parse_args()
    if a.summarize:
        rows = load_runs(a.summarize)
        if not rows:
            raise SystemExit(f"no runs under {a.summarize}")
        print(write_summary(a.summarize, rows, f"{rows[0].get('suite', '')} ({rows[0].get('model', '')})"))
        return
    from .llm import LLMConfig, make_model, make_settings

    cfg = LLMConfig()
    model, settings = make_model(cfg), make_settings(cfg)
    every = {**DESIGNS, **FRAMEWORK_DESIGNS}
    if a.designs == ["all"]:
        designs = list(DESIGNS.values())
    elif a.designs == ["everything"]:  # including the framework designs (their Python environments must exist)
        designs = list(every.values())
    else:
        designs = [every[d] for d in a.designs]
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "runs.jsonl")
    rows = load_runs(path) if os.path.exists(path) else []
    done = {(r["design"], r["case"], r["seed"], r.get("route")) for r in rows}
    for case in SUITES[a.suite]:
        if a.cases and case.id not in a.cases:
            continue
        calls = a.calls_per_member * case.team_size()
        for k, seed in enumerate(case.seeds[:a.seeds] if a.seeds else case.seeds):
            for d in designs:
                route = None if a.route == "case" else a.route
                if (d.name, case.id, seed, (route or case.route) if d.network_route else "framework") in done:
                    continue
                try:
                    r = {"model": cfg.model, "suite": a.suite, **run_one(
                        d, case, seed, model, settings, calls, route,
                        os.path.join(a.out, "traces", f"{d.name}__{case.id.replace('/', '_')}__{seed}.jsonl.gz")
                        if k < a.traces else "")}
                except Exception as e:  # noqa: BLE001 (one broken run must not stop the job; a rerun retries it)
                    print(f"{case.id} seed {seed} {d.name} FAILED: {type(e).__name__}: {e}", flush=True)
                    continue
                rows.append(r)
                with open(path, "a") as f:
                    f.write(json.dumps(r) + "\n")
                print(f"{case.id:32s} seed {seed:3d} {d.name:13s} solved {r['solved']!s:5s} "
                      f"done {r['done']}/{r['tasks']} calls {r['llm_tool_calls']} "
                      f"tokens {r['input_tokens'] + r['output_tokens']} errors {r['llm_errors']} "
                      f"ops {dict(Counter(r['ops']).most_common(4))}", flush=True)
    if rows:
        print(write_summary(a.out, rows, f"{a.suite} ({cfg.model})"))


if __name__ == "__main__":
    main()
