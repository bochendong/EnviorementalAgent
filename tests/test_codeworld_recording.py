"""Regression tests for the failed MIG pilot: loops, budget feedback and lossless records."""
import asyncio
import json
import random
from dataclasses import replace

import pytest

from worldseeds.codeworld.org import Org
from worldseeds.codeworld.world import Universe
from worldseeds.codeworld.llm_agent import Session, run_dev
from worldseeds.recording import ACTIVE_RECORDING, EventLog


def player(budget=7):
    u = Universe(1, n_modules=4)
    org = Org(u, 1, 8, "solo")
    org.devs[0].budget = budget
    return Session(org, org.devs[0], [u.project(random.Random(1))])


def test_unaffordable_study_preserves_cheap_actions():
    s = player()
    fn = next(iter(s.u.functions))
    feedback = s.study(fn)
    assert "7 actions left" in feedback and "run costs 1" in feedback
    assert s.stop_reason(lambda: True) is None
    s.run(fn, 0)
    assert s.dev.budget == 6 and s.blocked_budget == 0
    s.study(fn)
    s.study(fn)
    assert s.stop_reason(lambda: True) == "blocked_budget"
    assert s.dev.budget == 6  # no made-up charge or destruction of leftover budget


def test_numeric_law_feedback_and_repeated_failure():
    s = player()
    fn = next(iter(s.u.functions))
    for _ in range(3):
        text = s.remember(fn, "a*x + b")
    assert "concrete integer" in text and "3*x + 5" in text
    assert len(s.dev.notebook) == 0 and s.stop_reason(lambda: True) == "repeated_tool_failure"
    s.remember(fn, "3*x + 5")
    assert len(s.dev.notebook) == 1 and s.repeated_failure == 0


def test_limit_keeps_usage_and_dialogue(tmp_path):
    from agents import ModelSettings
    from agents.testing import ScriptedModel, function_call
    from agents.usage import Usage

    s = player(100)
    fn = next(iter(s.u.functions))
    class UsageModel(ScriptedModel):
        async def get_response(self, *args, **kwargs):
            response = await super().get_response(*args, **kwargs)
            response.usage = Usage(requests=1, input_tokens=23, output_tokens=7)
            return response
    model = UsageModel([[function_call("study", {"function": fn}, call_id="c1")]])
    log = EventLog(tmp_path / "events.jsonl")
    async def go():
        token = ACTIVE_RECORDING.set((log, {"variant": "solo"}))
        try:
            return await run_dev(s, model, ModelSettings(), max_turns=1)
        finally:
            ACTIVE_RECORDING.reset(token)
    result = asyncio.run(go())
    assert result["status"] == "max_turns"
    assert (result["input_tokens"], result["output_tokens"]) == (23, 7)
    rows = [json.loads(x) for x in log.path.read_text().splitlines()]
    assert {"agent_start", "llm_start", "llm_end", "tool_result", "agent_limit", "agent_end"} <= {r["kind"] for r in rows}
    assert all(r["dev"] == "dev0" for r in rows)
    assert next(r for r in rows if r["kind"] == "tool_result")["returned"] == s.trace[0]["returned"]


def test_experiment_uses_one_loop_and_records_replay(tmp_path, monkeypatch):
    from agents.testing import ScriptedModel, function_call
    from worldseeds.codeworld import experiment
    import worldseeds.llm as llm
    from worldseeds.codeworld.replay import town_world

    fn = next(iter(town_world(1).functions))
    loops = []
    class LoopModel(ScriptedModel):
        async def get_response(self, *args, **kwargs):
            loops.append(asyncio.get_running_loop())
            return await super().get_response(*args, **kwargs)
    model = LoopModel([[function_call("run", {"function": fn, "x": 1}, call_id=f"c{i}")] for i in range(20)])
    monkeypatch.setattr(llm, "make_model", lambda _: model)
    cfg = experiment.CWConfig(policy="llm", theme="town", walk=False, universes=[1], modules=[8],
        capacities=[12], team_sizes=[1], variants=["solo", "solo_unbounded"], sprints=2,
        projects_per_dev=1, budget=1, max_turns=2, save_traces=True, out_dir=str(tmp_path))
    experiment.run(cfg)
    assert len(loops) == 4 and all(loop is loops[0] for loop in loops)
    rows = [json.loads(x) for x in (tmp_path / "codeworld.jsonl").read_text().splitlines()]
    assert len(rows) == 4 and all(not x.startswith("error:") for r in rows for x in r["statuses"])
    replays = json.loads((tmp_path / "replay.json").read_text())["replays"]
    assert len(replays) == 2 and all(len(r["sprints"]) == 2 for r in replays)
    assert all(any(e["kind"] == "tool" for e in sp["events"]) for r in replays for sp in r["sprints"])
    assert [sp["metrics"]["done"] for r in replays for sp in r["sprints"]] == [r["done"] for r in rows]
    with pytest.raises(FileExistsError):
        experiment.run(cfg)


def test_raw_http_response_keeps_reasoning_and_no_headers(tmp_path):
    # Use the actual installed SDK HTTP implementation, not a fabricated hook interface.
    from openai import DefaultAsyncHttpxClient
    import importlib
    http = importlib.import_module(DefaultAsyncHttpxClient.__mro__[1].__module__.split('.')[0])
    from worldseeds.recording import record_request, record_response
    log = EventLog(tmp_path / "events.jsonl")
    async def go():
        token = ACTIVE_RECORDING.set((log, {"dev": "dev2"}))
        try:
            async def respond(request):
                return http.Response(200, json={"choices": [{"message": {
                    "content": "visible answer", "reasoning_content": "visible reasoning text"}}],
                    "usage": {"prompt_tokens": 22, "completion_tokens": 4096}})
            async with DefaultAsyncHttpxClient(transport=http.MockTransport(respond),
                event_hooks={"request": [record_request], "response": [record_response]}) as client:
                response = await client.post("http://mock/v1/chat/completions",
                    headers={"Authorization": "secret-for-test"}, json={"messages": [{"role": "user", "content": "hi"}]})
                assert response.json()["choices"]
        finally:
            ACTIVE_RECORDING.reset(token)
    asyncio.run(go())
    text = log.path.read_text()
    assert "secret-for-test" not in text and "visible reasoning text" in text
    rows = [json.loads(x) for x in text.splitlines()]
    assert rows[0]["request_id"] == rows[1]["request_id"] and rows[1]["dev"] == "dev2"
    assert log.http_usage[log.usage_key({"dev": "dev2"})] == [22, 4096]


def test_remember_rejects_contradictions_without_using_hidden_law():
    from worldseeds.codeworld.world import Law
    s = player(100)
    fn = next(iter(s.u.functions))
    s.u.functions[fn] = replace(s.u.functions[fn], law=Law("affine", 2, 73))
    # Reproduce dev2: actual 72->15 and 32->36, desired values were 75 and 39.
    s.run(fn, 72)
    s.run(fn, 32)
    feedback = s.remember(fn, "11*x + 91")
    assert "predicts 75" in feedback and "observed 15" in feedback
    assert fn not in s.dev.notebook
    assert s.remember(fn, "2*x + 73").startswith("Noted")

    # An untested hypothesis is still permitted, even if the evaluator knows it is wrong.
    unseen = next(name for name in s.u.functions if name != fn)
    wrong = Law("affine", 3, 5)
    s.u.functions[unseen] = replace(s.u.functions[unseen], law=Law("affine", 4, 6))
    assert s.remember(unseen, wrong.describe()).startswith("Noted")


def test_compute_is_prediction_and_failed_submits_cannot_hide_behind_it():
    from worldseeds.codeworld.world import Function, Law, Project
    s = player(100)
    s.u.functions['test.real'] = Function('test.real', 'test', 'raw', 'good', Law('affine', 1, 0))
    s.u.functions['test.target'] = Function('test.target', 'test', 'raw', 'good', Law('affine', 1, 1))
    s.queue = [Project('test-order', 'raw', 'good', [(10, 11)], ('test.target',), 2)]
    # A hypothetical note can predict the desired answer without being a real observation.
    s.remember('test.real', '1*x + 1')
    for attempt in range(3):
        prediction = s.compute(['test.real'], 10)
        assert 'on 10: 11' in prediction and 'Notebook prediction only' in prediction
        feedback = s.submit(['test.real'])
        assert 'actual machine output 10' in feedback and 'required output 11' in feedback
        if attempt < 2:
            assert s.stop_reason(lambda: True) is None
    s.compute(['test.real'], 10)
    assert s.stop_reason(lambda: True) == 'repeated_submission_failure'
    assert s.done == 0 and s.dev.budget == 97


def test_rejected_note_never_appears_as_learning_in_replay():
    from worldseeds.codeworld.replay import town_world
    from worldseeds.codeworld.town_llm import TownSession
    from worldseeds.codeworld.world import Law
    org = Org(town_world(1), 1, 12, 'solo', record=True)
    org.devs[0].budget = 100
    s = TownSession(org, org.devs[0], [org.u.project(random.Random(2))])
    fn = next(iter(org.u.functions))
    org.u.functions[fn] = replace(org.u.functions[fn], law=Law('affine', 2, 73))
    s.run(fn, 72)
    s.remember(fn, '11*x + 91')
    assert not any(e['kind'] == 'learn' for e in org.events)
    assert s.trace[-1]['out'].startswith('Rejected:')


def test_handing_over_orders_is_not_reported_as_delivery():
    from worldseeds.codeworld.replay import town_world
    from worldseeds.codeworld.town_llm import TownSession
    org = Org(town_world(1), 2, 12, 'owners', record=True)
    org.begin_sprint(40, [])
    order = org.u.project(random.Random(2))
    sender = TownSession(org, org.devs[0], [order])
    receiver = TownSession(org, org.devs[1], [])
    org.sessions = {s.dev.name: s for s in (sender, receiver)}
    assert receiver.stop_reason(lambda: bool(receiver.queue)) == 'no_orders'
    assert 'now' in sender.hand_over(receiver.dev.name)
    assert sender.done == 0 and sender.handed_over == 1
    assert receiver.queue == [order]
    assert sender.stop_reason(lambda: bool(sender.queue)) == 'orders_transferred'
    # A player who delivered some orders and transferred the rest must still be distinguished.
    sender.done = 1
    assert sender.stop_reason(lambda: bool(sender.queue)) == 'orders_transferred'
    receiver.submit(list(order.target))
    assert receiver.stop_reason(lambda: bool(receiver.queue)) == 'completed'
