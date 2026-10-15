"""Model factory: OpenAI Agents SDK on top of any OpenAI-compatible server.

Default target is a local vLLM server hosting an open-weight Qwen model::

    vllm serve $SCRATCH/models/Qwen3-8B --served-model-name qwen3-8b \\
        --enable-auto-tool-choice --tool-call-parser hermes

Environment variables (all optional):
    WS_BASE_URL     default http://localhost:8000/v1
    WS_MODEL        default qwen3-8b
    WS_API_KEY      default EMPTY
    WS_THINKING     "1" (default) keeps Qwen3 thinking mode on; "0" turns it off
    WS_MAX_TOKENS   default 4096 (thinking needs room: the reasoning counts towards it)
    WS_TEMPERATURE, WS_TOP_P, WS_TOP_K   default 0.6, 0.95, 20 (Qwen3's settings for thinking mode)
    WS_TOOL_CHOICE  "required" (default) or "auto"

Thinking is on by default: with tool calls required and thinking off, an agent cannot reason at all (each
step is a bare tool call), which cost Qwen3-8B 39 points on GSM8K against the same model answering in
plain chat (results/net/runs/20261013-qwen3-8b-ea182dd, fidelity). Serve the model with a reasoning
parser (slurm/start_vllm.sh: --reasoning-parser qwen3) so the reasoning stays out of the answer and out
of the conversation history. Every design and every framework uses these same settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class LLMConfig:
    base_url: str = os.environ.get("WS_BASE_URL", "http://localhost:8000/v1")
    model: str = os.environ.get("WS_MODEL", "qwen3-8b")
    api_key: str = os.environ.get("WS_API_KEY", "EMPTY")
    temperature: float = float(os.environ.get("WS_TEMPERATURE", "0.6"))
    top_p: float = float(os.environ.get("WS_TOP_P", "0.95"))
    top_k: int = int(os.environ.get("WS_TOP_K", "20"))
    max_tokens: int = int(os.environ.get("WS_MAX_TOKENS", "4096"))
    thinking: bool = os.environ.get("WS_THINKING", "1") == "1"
    tool_choice: str = os.environ.get("WS_TOOL_CHOICE", "required")
    timeout: float = float(os.environ.get("WS_TIMEOUT", "900"))  # seconds a request may take (thinking is slow)

    def extra_body(self) -> dict | None:
        """What an OpenAI-compatible request adds for vLLM: thinking on or off (Qwen3), and top_k."""
        body: dict = {"top_k": self.top_k} if self.top_k > 0 else {}
        if "qwen3" in self.model.lower():
            body["chat_template_kwargs"] = {"enable_thinking": self.thinking}
        return body or None

    def sampling(self) -> dict:
        """The sampling arguments of a chat completions request (for the frameworks and the fidelity check)."""
        out = {"temperature": self.temperature, "top_p": self.top_p, "max_tokens": self.max_tokens}
        if self.extra_body():
            out["extra_body"] = self.extra_body()
        return out


def make_model(cfg: LLMConfig):
    from agents import OpenAIChatCompletionsModel, set_tracing_disabled
    from openai import AsyncOpenAI

    set_tracing_disabled(True)  # tracing would upload to OpenAI's servers
    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.timeout, max_retries=3)
    return OpenAIChatCompletionsModel(model=cfg.model, openai_client=client)


def make_settings(cfg: LLMConfig):
    from agents import ModelSettings

    return ModelSettings(temperature=cfg.temperature, top_p=cfg.top_p, max_tokens=cfg.max_tokens,
                         tool_choice=None if cfg.tool_choice == "auto" else cfg.tool_choice,
                         parallel_tool_calls=False, extra_body=cfg.extra_body())
