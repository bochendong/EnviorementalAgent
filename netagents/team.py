"""Drive the network with LLM agents (OpenAI Agents SDK), or with random calls (to fuzz a provider).

The LLM team runs every agent concurrently: each has its own conversation and the tools of its role,
and the environment interleaves their calls as they come. Nothing in the instructions says how to
cooperate; that is what is being studied (and, later, trained).
"""

from __future__ import annotations

import asyncio
import random

from .tools import briefing, function_tools


def _fill(schema: dict, rng: random.Random, names: list[str], tasks: list[str], name: str = ""):
    t = schema.get("type")
    if t == "array":
        return [_fill(schema.get("items", {}), rng, names, tasks, name) for _ in range(rng.randint(1, 3))]
    if t == "integer":
        return rng.randint(-1, 5)
    if t == "number":
        return rng.random() * 5
    if t == "boolean":
        return rng.random() < .5
    if t == "object":
        return {}
    if name == "to":
        return rng.choice(names + ["*"])
    if name == "task":
        return rng.choice(tasks or ["none"])
    return rng.choice(["1", "n", "x", "hello", "c1ccccc1", "tests/test_public.py", "2*n+1", "a(n+1) = 2*a(n)"])


def random_policy(env, steps: int = 300, seed: int = 0) -> None:
    """Random operations with random arguments, through the public interface: nothing may crash."""
    rng = random.Random(seed)
    names = list(env.public()["agents"])
    tasks = [t["id"] for t in env.step(names[0], "tasks").get("tasks", [])]
    for _ in range(steps):
        a = rng.choice(names)
        o = env.observe(a)
        if o["episode_over"]:
            break
        if o["budget"] <= 0:
            continue
        op = rng.choice(env.ops(a))
        props, req = op["parameters"]["properties"], op["parameters"]["required"]
        env.step(a, op["name"], {k: _fill(v, rng, names, tasks, k) for k, v in props.items()
                                 if k in req or rng.random() < .5})


async def run_agent(env, agent: str, model, settings, max_turns: int = 100) -> dict:
    from agents import Agent, MaxTurnsExceeded, RunConfig, Runner, ToolsToFinalOutputResult

    def finished() -> bool:
        o = env.observe(agent)
        return o["episode_over"] or o["budget"] <= 0

    def stop(ctx, results):
        if finished():
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
        if finished() or nudges >= 3:
            status = "done" if finished() else "stopped"
            break
        nudges += 1
        inp = res.to_input_list() + [{"role": "user", "content": "There is work left and you have budget: "
                                      "call a tool."}]
    return {"agent": agent, "status": status, "nudges": nudges, "budget": env.observe(agent)["budget"]}


async def run_llm_team(env, model, settings, max_turns: int = 100) -> list[dict]:
    return await asyncio.gather(*(run_agent(env, a, model, settings, max_turns) for a in env.public()["agents"]))
