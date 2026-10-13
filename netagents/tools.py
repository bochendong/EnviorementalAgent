"""Tools for any agent framework, generated from the environment's op specs.

    call(env, agent, name, arguments)   run one tool call, return the observation as JSON text
    function_tools(env, agent)          OpenAI Agents SDK FunctionTools
    briefing(env, agent)                neutral instructions: who you are, the operations; no strategy

``env`` is a client (``LocalEnv`` or ``RemoteEnv``); ``env.tools(agent)`` already gives the OpenAI
chat-completions "tools" list for frameworks that take it directly.
"""

from __future__ import annotations

import json


def _describe(op: dict) -> str:
    return f"{op['doc']} [costs {op['cost']} action{'s' if op['cost'] != 1 else ''}]"


def call(env, agent: str, name: str, arguments: str | dict | None, limit: int = 6000) -> str:
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except json.JSONDecodeError as e:
        obs = {"ok": False, "error": f"arguments are not JSON: {e}"}
    else:
        obs = env.step(agent, name, args)
    text = json.dumps(obs, default=str)
    return text if len(text) <= limit else text[:limit] + " ...(cut)"


def function_tools(env, agent: str, limit: int = 6000) -> list:
    from agents import FunctionTool  # the OpenAI Agents SDK (pip package "openai-agents")

    tools = []
    for op in env.ops(agent):
        async def invoke(ctx, arguments, _op=op["name"]):
            return call(env, agent, _op, arguments, limit)

        tools.append(FunctionTool(name=op["name"], description=_describe(op), params_json_schema=op["parameters"],
                                  on_invoke_tool=invoke, strict_json_schema=False))
    return tools


def briefing(env, agent: str) -> str:
    pub, o = env.public(), env.observe(agent)
    others = ", ".join(f"{n} ({r})" for n, r in pub["agents"].items() if n != agent)
    ops = "\n".join(f"- {op['name']}: {_describe(op)}" for op in env.ops(agent))
    return (f"You are {agent}, a {o['role']} in a team working on a shared problem. {o['role_doc']}\n"
            f"The problem: {json.dumps(pub['info'], default=str)}\n"
            f"Others: {others or 'nobody'}. Your neighbours (who you can message): {', '.join(o['neighbours']) or 'none'}.\n"
            f"You have {o['budget']} actions; every operation costs actions as listed. The episode ends when the "
            "final task is done or everyone's budget is spent"
            + (f", or at round {o['deadline']} (a round passes when the team together has taken one action per "
               "member)" if o.get("deadline") else "") + ". Tasks are listed by the 'tasks' operation; a task "
            "opens when the tasks it depends on are done. Submitting a correct result for a task scores it.\n"
            f"Operations:\n{ops}")
