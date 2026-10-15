"""A few minutes on the GPU before any real run: does the model server answer every kind of request the
designs make, and does one tiny run of each kind of design go through without model errors?

    python -m netagents.smoke --out results/net/smoke          # against WS_BASE_URL (slurm/net_smoke.sh)

Requests (each with the settings of netagents/llm.py unless stated):

    chat              plain chat (the fidelity check's official arms, the orchestrators, the talkers)
    tool-required     one tool, tool_choice="required" (every design's members)
    tool-auto         the same with tool_choice="auto"
    tool-no-thinking  tool_choice="required" with thinking off
    json              response_format json_object (Magentic-One's ledgers)
    long              a prompt of about 40k tokens (the context window, YaRN)

Then one run each of sas (a single agent) and centralized (an orchestrator and members) on math/easy, seed
0, a few tool calls per member. Prints a table and writes smoke.json: every error in full.
Exit status 1 if anything failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

TOOL = {"type": "function", "function": {
    "name": "evaluate", "description": "Evaluate an arithmetic expression.",
    "parameters": {"type": "object", "properties": {"expr": {"type": "string"}}, "required": ["expr"]}}}
ASK = [{"role": "user", "content": "What is 17 * 23? Use the evaluate tool."}]


def request(client, cfg, name: str, **kw) -> dict:
    args = {"model": cfg.model, "messages": ASK, **cfg.sampling()}
    if name == "tool-no-thinking":
        args["extra_body"] = {**(args.get("extra_body") or {}), "chat_template_kwargs": {"enable_thinking": False}}
    args.update(kw)
    t = time.time()
    try:
        r = client.chat.completions.create(**args)
    except Exception as e:  # noqa: BLE001 (the point is to see the error)
        return {"request": name, "ok": False, "error": f"{type(e).__name__}: {e}", "seconds": round(time.time() - t, 1)}
    m = r.choices[0].message
    calls = m.tool_calls or []
    reasoning = getattr(m, "reasoning_content", None) or (m.model_extra or {}).get("reasoning_content")
    out = {"request": name, "ok": True, "finish": r.choices[0].finish_reason, "tool_calls": len(calls),
           "reasoning_chars": len(reasoning or ""), "content": (m.content or "")[:200],
           "think_tag_in_content": "<think>" in (m.content or ""),
           "usage": r.usage.model_dump() if r.usage else None, "seconds": round(time.time() - t, 1)}
    if name.startswith("tool") and kw.get("tool_choice") == "required" and not calls:
        out.update(ok=False, error="tool_choice=required but no tool call came back")
    if name == "json":
        try:
            json.loads(m.content or "")
        except ValueError:
            out.update(ok=False, error="response_format json_object but the content is not JSON")
    return out


def requests_check(cfg) -> list[dict]:
    from openai import OpenAI

    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=600)
    long_text = "Here is a list of numbers: " + " ".join(str(i % 97) for i in range(28000)) + \
        ". How many numbers are in the list, roughly? Answer in one sentence."
    return [
        request(client, cfg, "chat"),
        request(client, cfg, "tool-required", tools=[TOOL], tool_choice="required"),
        request(client, cfg, "tool-auto", tools=[TOOL], tool_choice="auto"),
        request(client, cfg, "tool-no-thinking", tools=[TOOL], tool_choice="required"),
        request(client, cfg, "json", response_format={"type": "json_object"},
                messages=[{"role": "user", "content": 'Reply with a JSON object {"answer": 17*23}.'}]),
        request(client, cfg, "long", messages=[{"role": "user", "content": long_text}]),
    ]


def runs_check(cfg) -> list[dict]:
    from .designs import DESIGNS
    from .evaluate import run_one
    from .llm import make_model, make_settings
    from .testset import Case

    model, settings = make_model(cfg), make_settings(cfg)
    case = Case("math/easy", "math/easy", [0])
    out = []
    for name in ("sas", "centralized"):
        t = time.time()
        try:
            r = run_one(DESIGNS[name], case, 0, model, settings, 5 * case.team_size())
            errs = [m["error"] for m in r["members"] if m.get("error")]
            out.append({"design": name, "ok": r["llm_errors"] == 0, "llm_errors": r["llm_errors"],
                        "llm_requests": r["llm_requests"], "tool_calls": r["llm_tool_calls"], "done": r["done"],
                        "ops": r["ops"], "member_errors": errs, "seconds": round(time.time() - t, 1)})
        except Exception as e:  # noqa: BLE001
            out.append({"design": name, "ok": False, "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-2000:]})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/net/smoke")
    ap.add_argument("--skip-runs", action="store_true")
    a = ap.parse_args()
    from .llm import LLMConfig

    cfg = LLMConfig()
    report = {"model": cfg.model, "base_url": cfg.base_url, "settings": {**cfg.sampling(), "thinking": cfg.thinking,
                                                                         "tool_choice": cfg.tool_choice},
              "requests": requests_check(cfg)}
    report["runs"] = [] if a.skip_runs else runs_check(cfg)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "smoke.json"), "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"{'check':18s} {'ok':5s} detail")
    for r in report["requests"]:
        detail = r.get("error") or (f"finish={r['finish']} tool_calls={r['tool_calls']} "
                                    f"reasoning={r['reasoning_chars']} think_in_content={r['think_tag_in_content']} "
                                    f"{r['seconds']}s")
        print(f"{r['request']:18s} {str(r['ok']):5s} {detail[:300]}")
    for r in report["runs"]:
        detail = r.get("error") or (f"errors={r['llm_errors']}/{r['llm_requests']} calls={r['tool_calls']} "
                                    f"done={r['done']} {r['seconds']}s " + "; ".join(r["member_errors"])[:300])
        print(f"{'run ' + r['design']:18s} {str(r['ok']):5s} {detail}")
    print(f"full report: {os.path.join(a.out, 'smoke.json')}")
    sys.exit(0 if all(r["ok"] for r in report["requests"] + report["runs"]) else 1)


if __name__ == "__main__":
    main()
