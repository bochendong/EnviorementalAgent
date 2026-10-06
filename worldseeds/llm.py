"""Model factory: OpenAI Agents SDK on top of any OpenAI-compatible server.

Default target is a local vLLM server hosting an open-weight Qwen model, e.g. on a
Nibi GPU node::

    vllm serve $SCRATCH/models/Qwen3-8B --served-model-name qwen3-8b \
        --enable-auto-tool-choice --tool-call-parser hermes

Environment variables (all optional):
    WS_BASE_URL   default http://localhost:8000/v1
    WS_MODEL      default qwen3-8b
    WS_API_KEY    default EMPTY (vLLM ignores it unless started with --api-key)
    WS_THINKING   "1" to keep Qwen3 thinking mode on (slower, sometimes better)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from agents import ModelSettings, OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI


@dataclass
class LLMConfig:
    base_url: str = os.environ.get("WS_BASE_URL", "http://localhost:8000/v1")
    model: str = os.environ.get("WS_MODEL", "qwen3-8b")
    api_key: str = os.environ.get("WS_API_KEY", "EMPTY")
    temperature: float = 0.3
    max_tokens: int = 1024
    thinking: bool = os.environ.get("WS_THINKING", "0") == "1"
    # "required" forces a tool call every turn (episodes end via the environment, not by
    # the model chatting). Set WS_TOOL_CHOICE=auto for servers without support.
    tool_choice: str = os.environ.get("WS_TOOL_CHOICE", "required")
    timeout: float = 300.0


def make_model(cfg: LLMConfig) -> OpenAIChatCompletionsModel:
    # Tracing would try to upload to OpenAI's servers; there is no OpenAI key on Nibi.
    set_tracing_disabled(True)
    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.timeout, max_retries=3)
    return OpenAIChatCompletionsModel(model=cfg.model, openai_client=client)


def make_settings(cfg: LLMConfig, tool_choice: str | None = "default") -> ModelSettings:
    if tool_choice == "default":
        tool_choice = None if cfg.tool_choice == "auto" else cfg.tool_choice
    extra_body = {}
    if "qwen3" in cfg.model.lower() or "qwen-3" in cfg.model.lower():
        # Qwen3 chat template switch; harmless for servers that ignore it.
        extra_body["chat_template_kwargs"] = {"enable_thinking": cfg.thinking}
    return ModelSettings(
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        tool_choice=tool_choice,
        parallel_tool_calls=False,
        extra_body=extra_body or None,
    )
