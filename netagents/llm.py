"""Model factory: OpenAI Agents SDK on top of any OpenAI-compatible server.

Default target is a local vLLM server hosting an open-weight Qwen model::

    vllm serve $SCRATCH/models/Qwen3-8B --served-model-name qwen3-8b \\
        --enable-auto-tool-choice --tool-call-parser hermes

Environment variables (all optional):
    WS_BASE_URL     default http://localhost:8000/v1
    WS_MODEL        default qwen3-8b
    WS_API_KEY      default EMPTY
    WS_THINKING     "1" keeps Qwen3 thinking mode on
    WS_MAX_TOKENS   default 1024
    WS_TOOL_CHOICE  "required" (default) or "auto"
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class LLMConfig:
    base_url: str = os.environ.get("WS_BASE_URL", "http://localhost:8000/v1")
    model: str = os.environ.get("WS_MODEL", "qwen3-8b")
    api_key: str = os.environ.get("WS_API_KEY", "EMPTY")
    temperature: float = 0.3
    max_tokens: int = int(os.environ.get("WS_MAX_TOKENS", "1024"))
    thinking: bool = os.environ.get("WS_THINKING", "0") == "1"
    tool_choice: str = os.environ.get("WS_TOOL_CHOICE", "required")
    timeout: float = 300.0


def make_model(cfg: LLMConfig):
    from agents import OpenAIChatCompletionsModel, set_tracing_disabled
    from openai import AsyncOpenAI

    set_tracing_disabled(True)  # tracing would upload to OpenAI's servers
    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.timeout, max_retries=3)
    return OpenAIChatCompletionsModel(model=cfg.model, openai_client=client)


def make_settings(cfg: LLMConfig):
    from agents import ModelSettings

    extra = {"chat_template_kwargs": {"enable_thinking": cfg.thinking}} if "qwen3" in cfg.model.lower() else None
    return ModelSettings(temperature=cfg.temperature, max_tokens=cfg.max_tokens,
                         tool_choice=None if cfg.tool_choice == "auto" else cfg.tool_choice,
                         parallel_tool_calls=False, extra_body=extra)
