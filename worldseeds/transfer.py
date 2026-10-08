"""Does SeedVille predict real benchmarks? Tools for the transfer study (docs/experiments.md).

    seedville_scores(run_dirs)   one row of SeedVille skills for an agent configuration, from its runs
    load_labbench / run_mcq      LAB-Bench multiple choice (ProtocolQA, SeqQA, CloningScenarios, ...) against
                                 the same OpenAI-compatible server the agent uses
    spearman / kendall / partial_spearman / bootstrap_ci   rank statistics across configurations

The analysis itself is ``scripts/transfer_analysis.py``. Benchmarks with their own harness (BixBench,
DiscoveryBench, ...) enter as numbers in the study file.
"""

from __future__ import annotations

import json
import math
import random
import re
from pathlib import Path

# ---------------------------------------------------------------------------- SeedVille side


def _rows(dirs) -> list[dict]:
    rows = []
    for d in dirs:
        for f in Path(d).rglob("episodes.jsonl"):
            rows += [json.loads(x) for x in f.open() if x.strip()]
    return rows


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _score(r: dict) -> float:
    return r["board_done"] / r["board_total"] if r.get("board_total") else float(bool(r["success"]))


def seedville_scores(dirs) -> dict:
    """SeedVille skills of one agent configuration, from all its runs (any protocols and switches):

    test_score        test success / share of requests done, plain worlds, with a learned seed
    test_score_none   the same without memory (how far the agent gets on its own)
    memory_gain       test_score - test_score_none (how well it uses what earlier worlds taught)
    law_precision     correct / confident laws in its learned seeds (LLM consolidator: its own claims)
    reflection_precision   correct / valid law claims of the LLM consolidator (seed_llm runs)
    noise_drop        test_score in plain worlds minus with --noise (robustness to noisy experiments)
    skin_gap          test_score with --skin drug minus plain (does a scientific story change behaviour)
    invalid_rate      invalid actions per action (tool-use reliability)
    """
    rows = [r for r in _rows(dirs) if r.get("phase") == "test" and r.get("protocol") == "compgen"]

    def opts(r):
        return r.get("world_opts") or {}

    def plain(r):
        o = opts(r)
        return not (o.get("noise") or o.get("screen_error") is not None or o.get("confounder")
                    or o.get("festival") or o.get("zoom_budget")) and r.get("skin", "none") == "none"

    seed = [r for r in rows if r["condition"] in ("seed", "seed_llm")]
    out = {
        "test_score": _mean(_score(r) for r in seed if plain(r)),
        "test_score_none": _mean(_score(r) for r in rows if r["condition"] == "none" and plain(r)),
        "law_precision": _mean(r["seed_laws_correct"] / r["seed_laws_confident"] for r in seed
                               if r.get("seed_laws_confident")),
        "reflection_precision": _mean(r["reflection_correct"] / (r["reflection_correct"] + r["reflection_wrong"])
                                      for r in seed if r.get("reflection_correct", 0) + r.get("reflection_wrong", 0)),
        "invalid_rate": _mean(r["invalid_actions"] / r["actions"] for r in rows if r.get("actions")),
    }
    noisy = _mean(_score(r) for r in seed if opts(r).get("noise") and r.get("skin", "none") == "none")
    skinned = _mean(_score(r) for r in seed if r.get("skin") not in (None, "none") and not opts(r).get("noise"))
    if out["test_score"] is not None and out["test_score_none"] is not None:
        out["memory_gain"] = out["test_score"] - out["test_score_none"]
    if out["test_score"] is not None and noisy is not None:
        out["noise_drop"] = out["test_score"] - noisy
    if out["test_score"] is not None and skinned is not None:
        out["skin_gap"] = skinned - out["test_score"]
    out["episodes"] = len(rows)
    return {k: v for k, v in out.items() if v is not None}


# ---------------------------------------------------------------------------- LAB-Bench side
REFUSE = "Insufficient information to answer the question."
TEXT_CONFIGS = ["ProtocolQA", "SeqQA", "CloningScenarios"]  # answerable from the question text alone


def load_labbench(root: str, config: str) -> list[dict]:
    """Items of one LAB-Bench config from a local copy of the dataset (``hf download futurehouse/lab-bench
    --repo-type dataset --local-dir DIR``; compute nodes are offline). Reads parquet, jsonl or json."""
    files = sorted(p for p in Path(root).rglob("*") if p.is_file() and config.lower() in str(p).lower()
                   and p.suffix in (".parquet", ".jsonl", ".json"))
    items = []
    for f in files:
        if f.suffix == ".parquet":
            import pandas as pd  # only needed for the parquet files of the Hugging Face copy

            items += pd.read_parquet(f).to_dict("records")
        elif f.suffix == ".jsonl":
            items += [json.loads(x) for x in f.open() if x.strip()]
        else:
            d = json.loads(f.read_text())
            items += d if isinstance(d, list) else d.get("data", [])
    out = []
    for it in items:
        if it.get("question") and it.get("ideal") is not None:
            out.append({"id": str(it.get("id", len(out))), "question": it["question"], "ideal": str(it["ideal"]),
                        "distractors": [str(x) for x in list(it.get("distractors") or [])],
                        "subtask": it.get("subtask") or config, "config": config})
    return out


def format_mcq(item: dict, rng: random.Random) -> tuple[str, str, str]:
    """(prompt, letter of the right answer, letter of the refusal option); choices shuffled, LAB-Bench style."""
    choices = [item["ideal"], *item["distractors"]]
    rng.shuffle(choices)
    choices.append(REFUSE)
    letters = [chr(ord("A") + i) for i in range(len(choices))]
    body = "\n".join(f"{x}) {c}" for x, c in zip(letters, choices))
    prompt = (f"{item['question']}\n\nOptions:\n{body}\n\nAnswer with the letter of one option, as "
              "[ANSWER]X[/ANSWER]. Choose the last option if you cannot tell.")
    return prompt, letters[choices.index(item["ideal"])], letters[-1]


def parse_letter(text: str, n: int) -> str | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\[ANSWER\]\s*\(?([A-Z])\)?\s*\[/ANSWER\]", text)
    if not m:
        m = re.search(r"(?:answer is|Answer:)\s*\(?([A-Z])\)?\b", text)
    letter = m.group(1) if m else None
    return letter if letter and ord(letter) - ord("A") < n else None


async def run_mcq(items: list[dict], base_url: str, model: str, api_key: str = "EMPTY", concurrency: int = 32,
                  seed: int = 0, max_tokens: int = 2048) -> list[dict]:
    """Ask every item once (temperature 0). Each result: id, subtask, answer, correct, refused."""
    import asyncio

    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=600, max_retries=3)
    sem = asyncio.Semaphore(concurrency)
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if "qwen3" in model.lower() else None

    async def one(it, k):
        prompt, right, refuse = format_mcq(it, random.Random(f"{seed}/{it['id']}"))
        async with sem:
            try:
                r = await client.chat.completions.create(model=model, temperature=0.0, max_tokens=max_tokens,
                                                         messages=[{"role": "user", "content": prompt}],
                                                         extra_body=extra)
                text = r.choices[0].message.content or ""
            except Exception as e:  # a failed request counts as no answer
                text = f"ERROR {type(e).__name__}: {e}"
        ans = parse_letter(text, len(it["distractors"]) + 2)
        return {"id": it["id"], "subtask": it["subtask"], "config": it["config"], "answer": ans,
                "correct": ans == right, "refused": ans == refuse or ans is None}

    return await asyncio.gather(*[one(it, k) for k, it in enumerate(items)])


def mcq_summary(results: list[dict]) -> dict:
    """LAB-Bench metrics: accuracy (correct / all), precision (correct / answered), coverage (answered / all)."""
    n = len(results)
    answered = [r for r in results if not r["refused"]]
    ok = sum(r["correct"] for r in results)
    return {"n": n, "accuracy": ok / n if n else 0.0, "precision": ok / len(answered) if answered else 0.0,
            "coverage": len(answered) / n if n else 0.0}


# ---------------------------------------------------------------------------- rank statistics
def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1  # ties share the mean rank
        i = j + 1
    return ranks


def _pearson(a, b) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else float("nan")


def spearman(a, b) -> float:
    return _pearson(_ranks(list(a)), _ranks(list(b)))


def kendall(a, b) -> float:
    """Kendall's tau-b."""
    n, conc, disc, ta, tb = len(a), 0, 0, 0, 0
    for i in range(n):
        for j in range(i + 1, n):
            da, db = a[i] - a[j], b[i] - b[j]
            if da == 0 and db == 0:
                continue
            if da == 0:
                ta += 1
            elif db == 0:
                tb += 1
            elif da * db > 0:
                conc += 1
            else:
                disc += 1
    den = math.sqrt((conc + disc + ta) * (conc + disc + tb))
    return (conc - disc) / den if den else float("nan")


def partial_spearman(a, b, c) -> float:
    """Spearman correlation of a and b with c's ranks partialled out (does SeedVille predict beyond c?)."""
    ra, rb, rc = _ranks(list(a)), _ranks(list(b)), _ranks(list(c))
    r_ab, r_ac, r_bc = _pearson(ra, rb), _pearson(ra, rc), _pearson(rb, rc)
    den = math.sqrt((1 - r_ac ** 2) * (1 - r_bc ** 2))
    return (r_ab - r_ac * r_bc) / den if den else float("nan")


def bootstrap_ci(stat, cols: list[list[float]], n: int = 2000, seed: int = 0, level: float = 0.95):
    """Percentile interval of ``stat(*cols)`` over configurations resampled with replacement."""
    rng = random.Random(seed)
    m = len(cols[0])
    vals = []
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        v = stat(*[[c[i] for i in idx] for c in cols])
        if v == v:  # not nan (a resample with no variation)
            vals.append(v)
    if not vals:
        return float("nan"), float("nan")
    vals.sort()
    lo = vals[int((1 - level) / 2 * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 + level) / 2 * len(vals)))]
    return lo, hi
