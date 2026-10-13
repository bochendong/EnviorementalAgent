"""Drive a NetworkEnv with LLM agents (OpenAI Agents SDK) or with random calls (to fuzz a provider).

The LLM team runs every agent concurrently: each has its own conversation and the tools of its role,
and the environment interleaves their calls as they come. Nothing in the instructions says how to
cooperate; that is what is being studied.
"""

from __future__ import annotations

import asyncio
import random

from .env import NetworkEnv
from .tools import briefing, function_tools


def _fill(schema: dict, rng: random.Random, env: NetworkEnv, name: str = ""):
    t = schema.get("type")
    if t == "array":
        return [_fill(schema.get("items", {}), rng, env, name) for _ in range(rng.randint(1, 3))]
    if t == "integer":
        return rng.randint(-1, 5)
    if t == "number":
        return rng.random() * 5
    if t == "boolean":
        return rng.random() < .5
    if t == "object":
        return {}
    if name in ("to",):
        return rng.choice(list(env.agents) + ["*"])
    if name == "task":
        return rng.choice(list(env.tasks) or ["none"])
    return rng.choice(["1", "n", "x", "hello", "c1ccccc1", "tests/test_public.py", "2*n+1", "a(n+1) = 2*a(n)"])


def random_policy(env: NetworkEnv, steps: int = 300, seed: int = 0) -> dict:
    """Random operations with random arguments: the environment must never crash."""
    rng = random.Random(seed)
    names = list(env.agents)
    for _ in range(steps):
        a = rng.choice(names)
        if env.agents[a].budget <= 0:
            continue
        spec = rng.choice(env.ops(a))
        args = {k: _fill(v, rng, env, k) for k, v in spec.params.items() if k in spec.required or rng.random() < .5}
        env.step(a, spec.name, args)
        if env.done:
            break
    return env.metrics()


async def run_agent(env: NetworkEnv, agent: str, model, settings, max_turns: int = 100) -> dict:
    from agents import Agent, MaxTurnsExceeded, RunConfig, Runner, ToolsToFinalOutputResult

    def stop(ctx, results):
        if env.done or env.agents[agent].budget <= 0:
            return ToolsToFinalOutputResult(is_final_output=True, final_output="stop")
        return ToolsToFinalOutputResult(is_final_output=False)

    bot = Agent(name=agent, instructions=briefing(env, agent), tools=function_tools(env, agent), model=model,
                model_settings=settings, tool_use_behavior=stop, reset_tool_choice=False)
    status, nudges, inp = "finished", 0, "Begin."
    while True:
        try:
            res = await Runner.run(bot, inp, max_turns=max_turns, run_config=RunConfig(tracing_disabled=True))
        except MaxTurnsExceeded:
            status = "max_turns"
            break
        except Exception as e:  # noqa: BLE001 (one broken agent must not stop the team)
            status = f"error: {type(e).__name__}: {e}"[:300]
            break
        if env.done or env.agents[agent].budget <= 0 or nudges >= 3:
            status = "done" if env.done else ("out_of_budget" if env.agents[agent].budget <= 0 else "stopped")
            break
        nudges += 1
        inp = res.to_input_list() + [{"role": "user", "content": "There is work left and you have budget: "
                                      "call a tool."}]
    return {"agent": agent, "status": status, "nudges": nudges, "budget": env.agents[agent].budget}


async def run_llm_team(env: NetworkEnv, model, settings, max_turns: int = 100) -> dict:
    runs = await asyncio.gather(*(run_agent(env, a, model, settings, max_turns) for a in env.agents))
    return {**env.metrics(), "agents": runs}
