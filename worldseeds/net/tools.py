"""Turn the operations of a NetworkEnv into tools for any agent framework.

    openai_tools(env, agent)    the OpenAI chat-completions "tools" list (works with any compatible client)
    function_tools(env, agent)  OpenAI Agents SDK FunctionTools that call env.step
    briefing(env, agent)        neutral instructions: who you are, the operations, the tasks; no strategy

Nothing here is specific to a provider: the tools come from the provider's OpSpecs and the network's own.
"""

from __future__ import annotations

import json

from .env import NetworkEnv


def _describe(spec) -> str:
    return f"{spec.doc} [costs {spec.cost} action{'s' if spec.cost != 1 else ''}]"


def openai_tools(env: NetworkEnv, agent: str) -> list[dict]:
    return [{"type": "function", "function": {"name": s.name, "description": _describe(s), "parameters": s.schema()}}
            for s in env.ops(agent)]


def call(env: NetworkEnv, agent: str, name: str, arguments: str | dict | None, limit: int = 6000) -> str:
    """Run one tool call and return the observation as JSON text (for frameworks that pass raw strings)."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except json.JSONDecodeError as e:
        args, bad = {}, str(e)
    else:
        bad = ""
    obs = {"ok": False, "error": f"arguments are not JSON: {bad}"} if bad else env.step(agent, name, args)
    text = json.dumps(obs, default=str)
    return text if len(text) <= limit else text[:limit] + " ...(cut)"


def function_tools(env: NetworkEnv, agent: str, limit: int = 6000) -> list:
    from agents import FunctionTool

    tools = []
    for s in env.ops(agent):
        async def invoke(ctx, arguments, _op=s.name):
            return call(env, agent, _op, arguments, limit)

        tools.append(FunctionTool(name=s.name, description=_describe(s), params_json_schema=s.schema(),
                                  on_invoke_tool=invoke, strict_json_schema=False))
    return tools


def briefing(env: NetworkEnv, agent: str) -> str:
    o = env.observe(agent)
    others = ", ".join(f"{b.name} ({b.role.name})" for b in env.agents.values() if b.name != agent)
    ops = "\n".join(f"- {s.name}: {_describe(s)}" for s in env.ops(agent))
    info = json.dumps(env.info, default=str)
    return (f"You are {agent}, a {o['role']} in a team working on a shared problem. {o['role_doc']}\n"
            f"The problem: {info}\n"
            f"Others: {others or 'nobody'}. Your neighbours (who you can message): {', '.join(o['neighbours']) or 'none'}.\n"
            f"You have {o['budget']} actions; every operation costs actions as listed. The episode ends when the "
            "final task is done or everyone's budget is spent"
            + (f", or at round {o['deadline']} (a round passes when the team together has taken one action per "
               "member)" if o.get("deadline") else "") + ". Tasks are listed by the 'tasks' operation; a task "
            "opens when the tasks it depends on are done. Submitting a correct result for a task scores it.\n"
            f"Operations:\n{ops}")
