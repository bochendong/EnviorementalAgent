"""Check the Codex transport inside the unchanged Peers/Lockstep SDK loop."""

import json

import pytest
from agents import ModelSettings

from netagents.codex_cli_model import CodexCLIModel, audit
from netagents.designs import DESIGNS
from netagents.evaluate import run_one
from netagents.testset import Case, SUITES


def test_native_peers_and_lockstep_use_one_operation_per_response(tmp_path, monkeypatch):
    model = CodexCLIModel(tmp_path)
    inputs = []

    def inference(prompt, schema, path):
        payload = json.loads(prompt.split("\n", 1)[1])
        inputs.append(payload)
        assert set(payload) == {"system_instructions", "conversation", "tools"}
        assert "Share the work among yourselves as you see fit" in payload["system_instructions"]
        assert "wait" in schema["properties"]["name"]["enum"]
        return {"name": "wait", "arguments_json": "{}"}, {"input_tokens": 10, "output_tokens": 2}

    monkeypatch.setattr(model, "_invoke", inference)
    case = Case("dag/fixed/dev", "dag/fixed", [0], opt={"agents": 3, "width": 2, "depth": 2}, lockstep=True)
    row = run_one(DESIGNS["peers"], case, 0, model, ModelSettings(tool_choice="required", parallel_tool_calls=False), 6)
    assert row["llm_errors"] == 0
    assert row["llm_tool_calls"] == row["llm_requests"] == len(inputs) == 6
    assert row["steps"] == 2 and row["acted"] == {"a0": 2, "a1": 2, "a2": 2}
    assert row["reference_steps"] > 0
    assert row["input_tokens"] == 60 and row["output_tokens"] == 12


def test_pilot_configuration():
    cases = SUITES["netscale-pilot"]
    assert [c.team_size() for c in cases] == [1, 2, 4, 8] * 2
    assert all(c.seeds == [100, 101, 102] and (c.opt["width"], c.opt["depth"]) == (16, 4) for c in cases)
    assert [c.opt["grain"] for c in cases] == [1] * 4 + [4] * 4 and all(c.lockstep for c in cases)


def test_transport_audit_rejects_outside_capabilities():
    complete = {"type": "turn.completed", "usage": {"input_tokens": 1}}
    assert audit([complete]) == {"input_tokens": 1}
    for event in ({"type": "item.completed", "item": {"type": "command_execution"}},
                  {"type": "item.started", "item": {"type": "mcp_tool_call"}}, {"type": "turn.failed"}):
        with pytest.raises(RuntimeError):
            audit([event, complete])
