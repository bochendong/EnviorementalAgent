"""The transfer study's pieces: SeedVille scores, LAB-Bench formatting and parsing, rank statistics."""
import json
import random

from worldseeds.transfer import (REFUSE, _ranks, bootstrap_ci, format_mcq, kendall, load_labbench, mcq_summary,
                                 parse_letter, partial_spearman, seedville_scores, spearman)


def test_rank_statistics():
    assert _ranks([3, 1, 2, 2]) == [4.0, 1.0, 2.5, 2.5]
    a = [1, 2, 3, 4, 5]
    assert abs(spearman(a, [10, 20, 30, 40, 50]) - 1) < 1e-9 and abs(spearman(a, [5, 4, 3, 2, 1]) + 1) < 1e-9
    assert abs(kendall(a, [1, 3, 2, 4, 5]) - 0.8) < 1e-9
    assert abs(spearman([1, 2, 3, 4], [1, 3, 2, 4]) - 0.8) < 1e-9
    # x and y agree mostly because both follow c (model size, say): partialling c out shrinks the agreement
    c = [1, 1, 2, 2, 3, 3, 4, 4]
    x, y = [1, 2, 3, 4, 5, 6, 7, 8], [2, 1, 4, 3, 6, 5, 8, 7]
    assert spearman(x, y) > 0.9 and partial_spearman(x, y, c) < 0
    lo, hi = bootstrap_ci(spearman, [list(range(10)), list(range(10))], n=200)
    assert abs(lo - 1) < 1e-9 and abs(hi - 1) < 1e-9


def test_mcq_format_and_parse(tmp_path):
    item = {"id": "q1", "question": "Which?", "ideal": "right", "distractors": ["w1", "w2"], "subtask": "s",
            "config": "SeqQA"}
    prompt, right, refuse = format_mcq(item, random.Random(0))
    assert f"{right}) right" in prompt and f"{refuse}) {REFUSE}" in prompt and refuse == "D"
    assert parse_letter("<think>maybe A</think> so [ANSWER]B[/ANSWER]", 4) == "B"
    assert parse_letter("The answer is (C).", 4) == "C" and parse_letter("[ANSWER]Z[/ANSWER]", 4) is None
    res = [{"correct": True, "refused": False}, {"correct": False, "refused": True}, {"correct": False, "refused": False}]
    s = mcq_summary(res)
    assert abs(s["accuracy"] - 1 / 3) < 1e-9 and s["precision"] == 0.5 and abs(s["coverage"] - 2 / 3) < 1e-9
    d = tmp_path / "SeqQA"
    d.mkdir()
    (d / "train.jsonl").write_text("\n".join(json.dumps({"id": i, "question": f"q{i}", "ideal": "x",
                                                         "distractors": ["y", "z"], "subtask": "t"}) for i in range(3)))
    items = load_labbench(str(tmp_path), "SeqQA")
    assert len(items) == 3 and items[0]["config"] == "SeqQA" and load_labbench(str(tmp_path), "ProtocolQA") == []


def test_seedville_scores_from_runs(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    for name, kw in (("plain", {"conditions": ["none", "seed"]}), ("noise", {"conditions": ["seed"], "noise": 0.25})):
        run_experiment(ExpConfig(env="board", protocol="compgen", policy="heuristic", universes=[1], n_train=6,
                                 n_test=4, max_actions=200, out_dir=str(tmp_path / name), **kw))
    s = seedville_scores([tmp_path])
    assert 0 <= s["test_score"] <= 1 and "memory_gain" in s and "noise_drop" in s and "skin_gap" not in s
    assert s["memory_gain"] == s["test_score"] - s["test_score_none"] and 0 <= s["law_precision"] <= 1
    only_plain = seedville_scores([tmp_path / "plain"])
    assert "noise_drop" not in only_plain and only_plain["test_score"] == s["test_score"]
