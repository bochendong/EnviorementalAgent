"""Fidelity checks: does a ported design behave like the authors' own code, on their own benchmark?

    python -m netagents.fidelity --check debate --n 100 --out results/net/fidelity/qwen3-8b

debate: GSM8K (the test split of openai/grade-school-math, MIT), the first ``n`` questions after the
shuffle of the authors' gsm/gen_gsm.py (random.seed(0)). Four arms, one model, same questions:

    official-single   one agent, the authors' first-round prompt, one answer
    official-debate   3 agents, 2 rounds, the authors' construct_message (gsm/gen_gsm.py), majority vote
    port-single       our ReAct design on the question as a one-task math problem (solo)
    port-debate       our debate design on the same, 3 agents, 2 rounds

Every arm uses the same model settings (netagents/llm.py: Qwen3's thinking mode and its sampling), so the
official and ported arms differ only in protocol and harness. (In 20261013-qwen3-8b-ea182dd they did not:
the official arms ran with the chat template's default, thinking on, and the ports with thinking off.)

The authors' module is fetched from GitHub at run time and imported (it only defines functions at import);
nothing of it is copied into this repository. Every arm is scored the same way: the last \\boxed{} number
(else the last number) against the reference, majority over agents where there are several; an answer
that cannot be parsed is wrong. (The authors' eval_gsm.py counts an unparseable answer as correct.)

The check passes when the port's gain over its single agent is close to the official gain over its single
agent (within the bootstrap interval written to the report). For reference, the paper (Du et al. 2024,
Table 1: 100 GSM8K problems, gpt-3.5-turbo-0301, 3 agents, 2 rounds, zero-shot) reports 77.0 +- 4.2 for
a single agent and 85.0 +- 3.5 for debate: a gain of 8 points.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import random
import re
import tempfile
import urllib.request

GSM8K = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl"
DEBATE = "https://raw.githubusercontent.com/composable-models/llm_multiagent_debate/main/gsm/gen_gsm.py"
PAPER = {"single": 0.770, "debate": 0.850, "model": "gpt-3.5-turbo-0301", "n": 100}  # Du et al., Table 1
FIRST = ("Can you solve the following math problem? {} Explain your reasoning. Your final answer should be a single "
         "numerical number, in the form \\boxed{{answer}}, at the end of your response. ")


def fetch(url: str, cache: str) -> str:
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, os.path.basename(url))
    if not os.path.exists(path):
        urllib.request.urlretrieve(url, path)
    return path


def gsm8k(n: int, cache: str) -> list[dict]:
    with open(fetch(GSM8K, cache)) as f:
        qs = [json.loads(line) for line in f if line.strip()]
    random.seed(0)  # as gen_gsm.py
    random.shuffle(qs)
    return [{"question": q["question"], "answer": q["answer"].split("####")[-1].strip().replace(",", "")}
            for q in qs[:n]]


def parse(text: str) -> str | None:
    boxed = re.findall(r"\\boxed\{([^}]*)\}", text or "")
    for b in boxed[::-1]:
        b = re.sub(r"[^0-9.\-]", "", b)
        if b:
            return b
    nums = re.findall(r"-?\d+\.?\d*", (text or "").replace(",", ""))
    return nums[-1] if nums else None


def correct(pred: str | None, ref: str) -> bool:
    try:
        return pred is not None and abs(float(pred) - float(ref)) < 1e-6
    except ValueError:
        return False


def vote(preds: list) -> str | None:
    preds = [p for p in preds if p is not None]
    return max(set(preds), key=preds.count) if preds else None


# ---------------------------------------------------------------- the authors' protocol
def official(qs, agents: int, rounds: int, module, client, cfg) -> list[bool]:
    out = []
    for q in qs:
        ctx = [[{"role": "user", "content": FIRST.format(q["question"])}] for _ in range(agents)]
        for r in range(rounds):
            for i, c in enumerate(ctx):
                if r != 0:
                    c.append(module.construct_message(ctx[:i] + ctx[i + 1:], q["question"], 2 * r - 1))
                res = client.chat.completions.create(model=cfg.model, messages=c, n=1, **cfg.sampling())
                c.append({"role": "assistant", "content": res.choices[0].message.content})
        out.append(correct(vote([parse(c[-1]["content"]) for c in ctx]), q["answer"]))
    return out


# ---------------------------------------------------------------- our ports, on the environment
def port(qs, design_name: str, calls_per_question: int, cache: str) -> list[bool]:
    from worldseeds.net import NetConfig, NetworkEnv, providers

    from .client import LocalEnv
    from .designs import DESIGNS
    from .llm import LLMConfig, make_model, make_settings

    cfg = LLMConfig()  # the same sampling and thinking as the official arms
    settings = make_settings(cfg)
    d = DESIGNS[design_name]
    out = []
    for k, q in enumerate(qs):
        path = os.path.join(cache, f"gsm_{k}.json")
        with open(path, "w") as f:
            json.dump({"title": "GSM8K", "tasks": [{"id": "Q", "text": q["question"] + " (answer: a number)",
                                                    "answer": q["answer"], "final": True}]}, f)
        team = 1 if d.variant == "solo" else 3
        raw = NetworkEnv(providers.make("math", problem_file=path, free_roles=True, explorers=team, algebraists=0),
                         NetConfig(budget=calls_per_question * 2))
        raw.reset(0)
        # a fresh client per question: an async client must not outlive the event loop it was made in
        asyncio.run(d.play(LocalEnv(raw), make_model(cfg), settings, calls_per_question * team))
        out.append(raw.solved)
    return out


def bootstrap(a: list[bool], b: list[bool], reps: int = 2000) -> tuple[float, float]:
    """95% interval of mean(a) - mean(b) over resampled questions (paired)."""
    rng = random.Random(1)
    n = len(a)
    diffs = sorted(sum(a[i] - b[i] for i in idx) / n for idx in
                   ([rng.randrange(n) for _ in range(n)] for _ in range(reps)))
    return diffs[int(.025 * reps)], diffs[int(.975 * reps)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", choices=["debate"], default="debate")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--calls", type=int, default=6, help="tool calls per agent per question for the ports")
    ap.add_argument("--out", default="results/net/fidelity")
    a = ap.parse_args()
    from openai import OpenAI

    from .llm import LLMConfig

    os.makedirs(a.out, exist_ok=True)
    cache = os.path.join(a.out, "cache")
    cfg = LLMConfig()
    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
    spec = importlib.util.spec_from_file_location("gen_gsm", fetch(DEBATE, os.path.join(cache, "debate")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    qs = gsm8k(a.n, cache)
    arms = {
        "official-single": official(qs, 1, 1, module, client, cfg),
        "official-debate": official(qs, 3, 2, module, client, cfg),
        "port-single": port(qs, "react", a.calls, tempfile.mkdtemp(dir=cache)),
        "port-debate": port(qs, "debate", a.calls, tempfile.mkdtemp(dir=cache)),
    }
    acc = {k: sum(v) / len(v) for k, v in arms.items()}
    gain_off, gain_port = (acc["official-debate"] - acc["official-single"], acc["port-debate"] - acc["port-single"])
    lo, hi = bootstrap(arms["official-debate"], arms["official-single"])
    report = {"check": a.check, "model": cfg.model, "n": len(qs),
              "settings": {**cfg.sampling(), "thinking": cfg.thinking}, "accuracy": acc, "official_gain": gain_off,
              "official_gain_95": [lo, hi], "port_gain": gain_port, "port_gain_within_official_interval":
              lo <= gain_port <= hi, "paper": {**PAPER, "gain": PAPER["debate"] - PAPER["single"]},
              "per_question": arms}
    with open(os.path.join(a.out, f"{a.check}.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "per_question"}, indent=1))


if __name__ == "__main__":
    main()
