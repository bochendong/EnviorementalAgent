import json

import pytest

from worldseeds.codeworld.arithmetic import evaluate
from worldseeds.codeworld.foundations import (
    CONDITIONS, FoundationConfig, instructions, learning_metrics, make_case, run,
)
from worldseeds.codeworld.tutorial import MACHINES, make_sessions


@pytest.mark.parametrize("expression,answer", [
    ("(53-69)%101", 85), ("(70-15)%101", 55), ("-(12+7)//3", -7),
    ("(25-5)*inv(5,101)%101", 4),
])
def test_integer_calculator(expression, answer):
    assert evaluate(expression) == answer


@pytest.mark.parametrize("expression", [
    "__import__('os').system('id')", "(1).__class__", "[1][0]", "2**1000000000",
    "True+1", "1.5+2", "1/2", "x+1", "inv(0,101)", "1//0", "1%0",
    "1000000000000*1000000000000", "inv(2,1000000000000)", "1+" * 200,
])
def test_calculator_rejects_non_arithmetic_and_unbounded_expressions(expression):
    with pytest.raises((ValueError, SyntaxError, ZeroDivisionError)):
        evaluate(expression)


def test_comparisons_have_matched_prompts_and_worlds():
    for seed in (11, 22, 33):
        _, (original,) = make_sessions(seed, "solo", 32)
        for condition in CONDITIONS:
            _, s, order = make_case(seed, condition)
            assert s.dev.notebook.capacity == 2 and s.dev.budget == 32
            assert [x for x, _ in order.examples] == [2, 7]
            if condition.world == "small":
                assert s.u.table(MACHINES) == original.u.table(MACHINES)
                assert order.examples == original.project.examples
        sessions = [make_case(seed, c)[1] for c in CONDITIONS]
        assert len({instructions(s) for s in sessions}) == 1


def test_ungated_delivery_does_not_count_as_learning():
    _, s, order = make_case(11, CONDITIONS[1])
    assert s.submit(list(MACHINES)).startswith("Accepted")
    assert learning_metrics(s, order)["order_passed"]
    assert not learning_metrics(s, order)["learning_passed"]
    _, gated, _ = make_case(11, CONDITIONS[0])
    assert gated.submit(list(MACHINES)).startswith("Rejected")


def test_explicit_guidance_is_shared_and_does_not_supply_coefficients():
    for seed in (11, 22, 33):
        _, raw, _ = make_case(seed, CONDITIONS[3])
        _, calc, _ = make_case(seed, CONDITIONS[4])
        text = instructions(raw, True)
        assert text == instructions(calc, True)
        assert '(output_at_1-output_at_0)%101' in text and 'minus sign' in text
        assert 'once' in text.lower() and text != instructions(raw)
        assert all(f.law.describe() not in text for f in raw.u.functions.values())


def test_model_pipeline_calculator_records_and_learning_checks(tmp_path):
    from agents import ModelSettings
    from agents.testing import ScriptedModel, function_call
    calls = []
    for c in CONDITIONS:
        _, s, _ = make_case(11, c)
        for fn in MACHINES:
            for x in (0, 1, 2):
                calls.append(("run", {"function": fn, "x": x}))
            b = s.u.functions[fn].law(0)
            y1 = s.u.functions[fn].law(1)
            if c.calculator:
                calls.append(("calculate", {"expression": f"({y1}-{b})%101"}))
            calls.append(("remember", {"function": fn, "law": f"{(y1-b)%101}*x+{b}"}))
        calls.extend(("compute", {"program": list(MACHINES), "x": x}) for x in (2, 7))
        calls.append(("submit", {"program": list(MACHINES)}))
    model = ScriptedModel([[function_call(name, args, call_id=f"c{i}")]
                           for i, (name, args) in enumerate(calls)])
    run(FoundationConfig(str(tmp_path), seeds=(11,)), model, ModelSettings())
    rows = [json.loads(line) for line in (tmp_path / "codeworld.jsonl").read_text().splitlines()]
    assert len(rows) == 5 and all(r["learning_passed"] and r["order_passed"] for r in rows)
    assert all(r["actions"] == 7 for r in rows)  # calculator is free, but uses model turns
    assert [r["tool_calls"].get("calculate", 0) for r in rows] == [0, 0, 2, 0, 2]
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    starts = [r for r in events if r["kind"] == "agent_start"]
    assert ["calculate" in [t["name"] for t in r["tools"]] for r in starts] == [False, False, True, False, True]
    assert len(json.loads((tmp_path / "summary.json").read_text())["conditions"]) == 5
    with pytest.raises(FileExistsError):
        run(FoundationConfig(str(tmp_path), seeds=(11,)), model, ModelSettings())
