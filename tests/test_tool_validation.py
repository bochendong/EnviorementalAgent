"""Regression checks for malformed Qwen/vLLM tool calls and lockstep."""
import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("agents")
from agents import ModelSettings, OpenAIChatCompletionsModel
from agents.exceptions import ModelBehaviorError
from agents.items import ModelResponse
from agents.usage import Usage
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage

from netagents.client import LocalEnv
from netagents.lockstep import Lockstep
from netagents.tools import call, function_tools
from netagents.validated_model import ValidatedChatCompletionsModel
from worldseeds.net import NetConfig, NetworkEnv, providers


def environment():
    raw = NetworkEnv(providers.make("math"), NetConfig(budget=30))
    raw.reset(0)
    return raw


@pytest.mark.parametrize("bad", ['null', '1.2', '"hello"', '[]', '[["x",1]]', '{broken', 4, False, []])
def test_invalid_arguments_do_not_enter_environment(bad):
    raw = environment()
    before = len(raw.events)
    result = json.loads(call(LocalEnv(raw), "a0", "tasks", bad))
    assert not result["ok"] and "arguments" in result["error"]
    assert len(raw.events) == before


def test_rejected_arguments_do_not_strand_lockstep_peers():
    async def run():
        raw = environment()
        lock = Lockstep(raw)
        names = list(raw.agents)[:2]
        for name in names:
            lock.join(name)
        first = next(t for t in function_tools(lock, names[0]) if t.name == "tasks")
        second = next(t for t in function_tools(lock, names[1]) if t.name == "tasks")
        pending = asyncio.create_task(second.on_invoke_tool(None, "{}"))
        await asyncio.sleep(0)
        assert not pending.done()
        bad = json.loads(await first.on_invoke_tool(None, '"scalar"'))
        assert not bad["ok"] and "JSON object" in bad["error"]
        lock.leave(names[0])
        result = json.loads(await asyncio.wait_for(pending, timeout=1))
        assert result["ok"] and lock.round == 1
        lock.leave(names[1])
    asyncio.run(run())


def model_call(arguments=None):
    return ResponseFunctionToolCall(type="function_call", name="tasks", arguments=arguments, call_id="c1")


def message():
    return ResponseOutputMessage(id="m1", content=[], role="assistant", type="message", status="completed")


def response(items, n):
    return ModelResponse(output=items, usage=Usage(requests=1, input_tokens=n, output_tokens=2, total_tokens=n + 2),
                         response_id=None)


def test_retries_parser_failures_and_counts_every_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("NETAGENTS_VALIDATION_LOG_DIR", str(tmp_path))
    replies = iter([response([message()], 10), response([model_call('"oops"')], 20),
                    response([model_call('{}')], 30)])
    async def fake(*args, **kwargs):
        return next(replies)
    monkeypatch.setattr(OpenAIChatCompletionsModel, "get_response", fake)
    model = ValidatedChatCompletionsModel("test", AsyncOpenAI(api_key="EMPTY"))
    result = asyncio.run(model.get_response(system_instructions="", input=[],
                         model_settings=ModelSettings(tool_choice="required", parallel_tool_calls=False),
                         tools=[SimpleNamespace(name="tasks")], output_schema=None, handoffs=[], tracing=None))
    assert result.output[0].arguments == '{}'
    assert (result.usage.requests, result.usage.input_tokens, result.usage.output_tokens) == (3, 60, 6)
    logs = [json.loads(s) for s in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
    assert [x.get("reason") for x in logs[:2]] == ["required_tool_missing_or_parser_failed", "invalid_tool_arguments"]
    assert logs[2]["kind"] == "accepted_model_response" and logs[2]["usage"]["input_tokens"] == 30
    assert logs[-1]["outcome"] == "recovered" and logs[-1]["rejected_attempts"] == 2


def test_retries_are_bounded_and_failures_are_recorded(monkeypatch, tmp_path):
    monkeypatch.setenv("NETAGENTS_VALIDATION_LOG_DIR", str(tmp_path))
    attempts = []
    async def fake(*args, **kwargs):
        attempts.append(1)
        return response([model_call('1.2')], 10)
    monkeypatch.setattr(OpenAIChatCompletionsModel, "get_response", fake)
    model = ValidatedChatCompletionsModel("test", AsyncOpenAI(api_key="EMPTY"))
    with pytest.raises(ModelBehaviorError, match="after 3 attempts"):
        asyncio.run(model.get_response(system_instructions="", input=[],
                    model_settings=ModelSettings(tool_choice="required", parallel_tool_calls=False),
                    tools=[SimpleNamespace(name="tasks")], output_schema=None, handoffs=[], tracing=None))
    logs = [json.loads(s) for s in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
    assert len(attempts) == 3 and logs[-1]["outcome"] == "exhausted"
    assert sum(x["usage"]["input_tokens"] for x in logs[:-1]) == 30


def test_text_reply_allowed_when_tools_are_not_required(monkeypatch):
    async def fake(*args, **kwargs):
        return response([message()], 10)
    monkeypatch.setattr(OpenAIChatCompletionsModel, "get_response", fake)
    model = ValidatedChatCompletionsModel("test", AsyncOpenAI(api_key="EMPTY"))
    result = asyncio.run(model.get_response(system_instructions="", input=[],
                         model_settings=ModelSettings(tool_choice=None), tools=[SimpleNamespace(name="tasks")],
                         output_schema=None, handoffs=[], tracing=None))
    assert result.output[0].type == "message" and result.usage.requests == 1


def test_real_sdk_retries_invalid_arguments_and_counts_usage(monkeypatch, tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from agents import Agent, Runner, RunConfig

    monkeypatch.setenv("NETAGENTS_VALIDATION_LOG_DIR", str(tmp_path))
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            args = '1.2' if len(requests) == 1 else '{}'
            body = json.dumps({'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': 'test',
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': None,
                    'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'tasks', 'arguments': args}}]},
                    'finish_reason': 'tool_calls'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        raw = environment()
        model = ValidatedChatCompletionsModel('test', AsyncOpenAI(api_key='EMPTY', base_url=f'http://127.0.0.1:{server.server_port}/v1'))
        tool = next(t for t in function_tools(LocalEnv(raw), 'a0') if t.name == 'tasks')
        agent = Agent(name='test', model=model, tools=[tool], tool_use_behavior='stop_on_first_tool',
                      model_settings=ModelSettings(tool_choice='required', parallel_tool_calls=False))
        result = asyncio.run(Runner.run(agent, 'Inspect tasks', run_config=RunConfig(tracing_disabled=True)))
        assert len(requests) == 2
        assert (result.context_wrapper.usage.requests, result.context_wrapper.usage.input_tokens,
                result.context_wrapper.usage.output_tokens) == (2, 20, 4)
        logs = [json.loads(line) for line in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
        assert [e['kind'] for e in logs] == ['rejected_model_response', 'accepted_model_response', 'validation_outcome']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
