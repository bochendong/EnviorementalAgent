"""Validate OpenAI-compatible tool replies before the SDK sees them.

vLLM may return a malformed tool envelope or scalar arguments even for a
required tool. Retry the same model request at most twice; never manufacture an
action or pass malformed arguments into the environment. Rejected replies are
logged independently and their usage is added to a recovered response.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid

from agents import OpenAIChatCompletionsModel
from agents.exceptions import ModelBehaviorError
from agents.usage import Usage

from .tools import _arguments


def _invalid_reason(response, tools, settings):
    calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
    if settings.tool_choice == "required" and tools and not calls:
        return "required_tool_missing_or_parser_failed"
    if settings.parallel_tool_calls is False and len(calls) > 1:
        return "multiple_tool_calls"
    names = {tool.name for tool in tools if hasattr(tool, "name")}
    for item in calls:
        if item.name not in names:
            return "unknown_tool"
        try:
            _arguments(item.arguments)
        except (ValueError, TypeError):
            return "invalid_tool_arguments"
    return None


def _record(event):
    directory = os.environ.get("NETAGENTS_VALIDATION_LOG_DIR")
    if not directory:
        return
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    # One file per process: workers do not concurrently append to a shared NFS file.
    path = root / f"{os.getpid()}.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def _usage_data(usage):
    return {"requests": usage.requests, "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens, "total_tokens": usage.total_tokens,
            "cached_input_tokens": getattr(usage.input_tokens_details, "cached_tokens", 0),
            "reasoning_output_tokens": getattr(usage.output_tokens_details, "reasoning_tokens", 0)}


class ValidatedChatCompletionsModel(OpenAIChatCompletionsModel):
    async def get_response(self, *args, **kwargs):
        settings = kwargs.get("model_settings") if "model_settings" in kwargs else args[2]
        tools = kwargs.get("tools") if "tools" in kwargs else args[3]
        usage, group = Usage(), uuid.uuid4().hex
        for attempt in range(3):
            response = await super().get_response(*args, **kwargs)
            usage.add(response.usage)
            reason = _invalid_reason(response, tools, settings)
            if reason is None:
                _record({"kind": "accepted_model_response", "group": group, "attempt": attempt + 1,
                         "usage": _usage_data(response.usage), "time": time.time()})
                response.usage = usage
                if attempt:
                    _record({"kind": "validation_outcome", "group": group, "outcome": "recovered",
                             "rejected_attempts": attempt, "time": time.time()})
                return response
            _record({"kind": "rejected_model_response", "group": group, "attempt": attempt + 1,
                     "reason": reason, "usage": _usage_data(response.usage), "time": time.time()})
        _record({"kind": "validation_outcome", "group": group, "outcome": "exhausted",
                 "rejected_attempts": 3, "time": time.time()})
        raise ModelBehaviorError(f"Invalid tool response after 3 attempts: {reason}")
