"""Codex CLI transport for the existing Agents SDK Model interface.

Only replaces inference: original FunctionTools, Member, Peers, and Lockstep
execute and charge the action. Each response selects exactly one original tool.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall


DISABLED = ("shell_tool", "unified_exec", "apps", "plugins", "memories", "multi_agent", "in_app_browser", "skill_search")


def json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Unsupported model input: {type(value).__name__}")


def write_json(path, value):
    tmp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default) + "\n")
    tmp.replace(path)


def audit(events):
    usage = None
    for event in events:
        if event.get("type") not in {"thread.started", "turn.started", "item.started", "item.updated", "item.completed", "turn.completed"}:
            raise RuntimeError(f"Codex inference error/event: {event}")
        item = event.get("item", {})
        if item and item.get("type") not in {"agent_message", "reasoning"}:
            raise RuntimeError(f"Codex used an outside capability: {item.get('type')}")
        if event["type"] == "turn.completed":
            usage = event["usage"]
    if usage is None:
        raise RuntimeError("Codex did not complete the decision")
    return usage


class CodexCLIModel(Model):
    def __init__(self, directory, model="gpt-6.1-sol", effort="high", gate=None, timeout=180, codex=None, stop=None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.model_name, self.effort, self.timeout = model, effort, timeout
        self.codex = codex or shutil.which("codex") or "codex"
        self.gate = gate or threading.BoundedSemaphore(2)
        self.stop = stop
        self.lock = threading.Lock()
        self.indices, self.ops, self.accepted = {}, {}, set()

    def _progress(self, agent, tool):
        with self.lock:
            self.ops[tool] = self.ops.get(tool, 0) + 1
            write_json(self.directory / "progress.json", {
                "requests": sum(self.indices.values()), "per_agent": self.indices,
                "last_agent": agent, "last_operation": tool, "operations": self.ops,
                "accepted_tasks_seen": len(self.accepted), "accepted_tasks": sorted(self.accepted),
                "updated_utc_epoch": time.time(),
            })

    def _observe_outputs(self, items):
        if not isinstance(items, list):
            return
        calls = {x.get("call_id"): x for x in items if isinstance(x, dict) and x.get("type") == "function_call"}
        with self.lock:
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "function_call_output":
                    continue
                call = calls.get(item.get("call_id"), {})
                if call.get("name") != "submit":
                    continue
                try:
                    result = json.loads(item["output"])
                    if result.get("ok") and result.get("task"):
                        self.accepted.add(result["task"])
                except (ValueError, TypeError):
                    pass

    def _invoke(self, prompt, schema, path):
        if (path / "metadata.json").exists():
            if (path / "prompt.txt").read_text() != prompt or json.loads((path / "schema.json").read_text()) != schema:
                raise RuntimeError(f"Cached Codex request differs: {path}")
            events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines() if line]
            return json.loads((path / "answer.json").read_text()), audit(events)
        if path.exists():
            path.rename(path.with_name(path.name + f".interrupted-{time.time_ns()}"))
        last_error = None
        for attempt in range(3):
            if self.stop is not None and self.stop.is_set():
                raise RuntimeError("Experiment stopped after an infrastructure failure")
            if attempt:
                path.rename(path.with_name(path.name + f".interrupted-{time.time_ns()}"))
                time.sleep(15 * attempt)
            path.mkdir(parents=True)
            (path / "prompt.txt").write_text(prompt)
            write_json(path / "schema.json", schema)
            try:
                with self.gate, tempfile.TemporaryDirectory(prefix="codex-netscale-player-") as workspace:
                    if self.stop is not None and self.stop.is_set():
                        raise RuntimeError("Experiment stopped after an infrastructure failure")
                    cmd = [self.codex, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                           "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--color", "never",
                           "-C", workspace, "--model", self.model_name,
                           "-c", f'model_reasoning_effort="{self.effort}"', "-c", 'web_search="disabled"',
                           "-c", "project_doc_max_bytes=0", "--output-schema", str(path / "schema.json"),
                           "-o", str(path / "answer.json")]
                    for feature in DISABLED:
                        cmd += ["--disable", feature]
                    cmd.append("-")
                    write_json(path / "command.json", cmd)
                    env = {k: v for k, v in os.environ.items() if k in {
                        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "CODEX_HOME", "LANG", "LC_ALL",
                        "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY"}}
                    started = time.monotonic()
                    with (path / "events.jsonl").open("w") as stdout, (path / "stderr.log").open("w") as stderr:
                        process = subprocess.run(cmd, input=prompt, text=True, stdout=stdout, stderr=stderr,
                                                 timeout=self.timeout, env=env)
                    events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines() if line]
                    usage = audit(events)
                    if process.returncode:
                        raise RuntimeError(f"Codex exited {process.returncode}: {path}")
                    answer = json.loads((path / "answer.json").read_text())
                    write_json(path / "metadata.json", {"seconds": time.monotonic() - started, "usage": usage,
                                                         "tool_audit": "passed"})
                    return answer, usage
            except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
                last_error = error
                write_json(path / "failure.json", {"error": str(error), "attempt": attempt + 1})
                # A leaked extra capability is an invalid run, not a retryable service error.
                if "outside capability" in str(error) or "Experiment stopped" in str(error) or attempt == 2:
                    raise
        raise RuntimeError(str(last_error))

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs):
        match = re.match(r"You are (a\d+),", system_instructions or "")
        if not match:
            raise ValueError("Codex peers adapter requires the original agent identity in its briefing")
        agent = match.group(1)
        with self.lock:
            index = self.indices.get(agent, 0)
            self.indices[agent] = index + 1
        original_tools = [{"name": t.name, "description": t.description, "parameters": t.params_json_schema} for t in tools]
        names = [t["name"] for t in original_tools]
        if not names:
            raise ValueError("Peers requires tool selection")
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "name": {"type": "string", "enum": names}, "arguments_json": {"type": "string"}},
            "required": ["name", "arguments_json"]}
        payload = {"system_instructions": system_instructions, "conversation": input, "tools": original_tools}
        prompt = ("Act as the model in this agent conversation. Follow its system instructions and continue from its "
                  "tool results. Select exactly ONE of the supplied function tools. Return its name and arguments_json "
                  "(a JSON-encoded object matching that tool's parameter schema). The host executes the tool and returns "
                  "its observation on the next decision. Use no capabilities outside the supplied function tools "
                  "(files, shell, web, plugins, skills, or outside agents). You have only this agent's supplied "
                  "conversation; communicate with teammates through the environment's tools. "
                  "Do not execute the action yourself.\n"
                  + json.dumps(payload, ensure_ascii=False, default=json_default))
        self._observe_outputs(input)
        answer, usage = await asyncio.to_thread(self._invoke, prompt, schema, self.directory / "calls" / agent / f"{index:06d}")
        if set(answer) != {"name", "arguments_json"} or answer["name"] not in names:
            raise ValueError("Codex returned an invalid tool selection")
        arguments = json.loads(answer["arguments_json"])
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        args = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256((answer["name"] + args).encode()).hexdigest()[:12]
        call_id = f"call_{agent}_{index}_{digest}"
        self._progress(agent, answer["name"])
        return ModelResponse(output=[ResponseFunctionToolCall(
            id=f"fc_{agent}_{index}_{digest}", call_id=call_id, type="function_call", status="completed",
            name=answer["name"], arguments=args)], response_id=None,
            usage=Usage(requests=1, input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
                        total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0)))

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError("Codex peers uses non-streaming inference")
        yield  # pragma: no cover
