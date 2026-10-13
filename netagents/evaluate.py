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

Writes runs.jsonl and summary.md to --out.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics as st
from collections import Counter

from .client import LocalEnv
from .designs import DESIGNS
from .frameworks import FRAMEWORK_DESIGNS
from .testset import CALLS_PER_MEMBER, SUITES

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


def run_one(design, case, seed, model, settings, calls) -> dict:
    raw = case.build(design.variant)
    raw.reset(seed)
    reports = asyncio.run(design.play(LocalEnv(raw), model, settings, calls))
    m = raw.metrics()
    msgs = Counter(e["op"] for e in raw.events if e.get("kind") == "op" and e["obs"].get("ok"))
    return {"design": design.name, "case": case.id, "seed": seed, "variant": design.variant, "call_budget": calls,
            "agents": len(raw.agents), "solved": m["solved"], "done": m["done"], "tasks": m["tasks"],
            "completion": round(m["done"] / max(1, m["tasks"]), 3), "actions": m["actions"], "rounds": m["rounds"],
            "llm_tool_calls": sum(r["tool_calls"] for r in reports),
            "llm_requests": sum(r["llm_requests"] for r in reports),
            "input_tokens": sum(r["input_tokens"] for r in reports),
            "output_tokens": sum(r["output_tokens"] for r in reports),
            "messages": msgs["send"], "posts": msgs["post"], "store_writes": msgs["put"],
            **failure_signals(raw), "members": reports}


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="dev", choices=sorted(SUITES))
    ap.add_argument("--designs", nargs="*", default=["all"])
    ap.add_argument("--cases", nargs="*", default=None, help="only these case ids")
    ap.add_argument("--seeds", type=int, default=None, help="only the first N seeds of each case")
    ap.add_argument("--calls-per-member", type=int, default=CALLS_PER_MEMBER)
    ap.add_argument("--out", default="results/net/eval")
    a = ap.parse_args()
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
    rows = []
    for case in SUITES[a.suite]:
        if a.cases and case.id not in a.cases:
            continue
        calls = a.calls_per_member * case.team_size()
        for seed in case.seeds[:a.seeds] if a.seeds else case.seeds:
            for d in designs:
                r = {"model": cfg.model, "suite": a.suite, **run_one(d, case, seed, model, settings, calls)}
                rows.append(r)
                with open(path, "a") as f:
                    f.write(json.dumps(r) + "\n")
                print(f"{case.id:32s} seed {seed:3d} {d.name:13s} solved {r['solved']!s:5s} "
                      f"done {r['done']}/{r['tasks']} calls {r['llm_tool_calls']} "
                      f"tokens {r['input_tokens'] + r['output_tokens']}", flush=True)
    with open(os.path.join(a.out, "summary.md"), "w") as f:
        f.write(f"# {a.suite} ({cfg.model})\n\n" + summarize(rows))
    print(summarize(rows))


if __name__ == "__main__":
    main()
