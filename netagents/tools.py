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


def _arguments(arguments):
    """Decode tool arguments without treating a scalar or array as an object."""
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be a JSON object")
    return arguments


def _argument_error(error):
    if isinstance(error, json.JSONDecodeError):
        return f"arguments are not JSON: {error}"
    return f"invalid tool arguments: {error}"


def call(env, agent: str, name: str, arguments: str | dict | None, limit: int = 6000) -> str:
    try:
        args = _arguments(arguments)
    except (ValueError, TypeError) as e:
        obs = {"ok": False, "error": _argument_error(e)}
    else:
        obs = env.step(agent, name, args)
    text = json.dumps(obs, default=str)
    return text if len(text) <= limit else text[:limit] + " ...(cut)"


def function_tools(env, agent: str, limit: int = 6000, keep=None) -> list:
    """``keep(op_name) -> bool`` narrows the tools (agent designs that restrict who may do what)."""
    from agents import FunctionTool  # the OpenAI Agents SDK (pip package "openai-agents")

    tools = []
    for op in env.ops(agent):
        if keep is not None and not keep(op["name"]):
            continue
        async def invoke(ctx, arguments, _op=op["name"]):
            if hasattr(env, "astep"):  # lockstep time (netagents/lockstep.py): wait for the round
                try:
                    args = _arguments(arguments)
                except (ValueError, TypeError) as e:
                    return json.dumps({"ok": False, "error": _argument_error(e)})
                text = json.dumps(await env.astep(agent, _op, args), default=str)
                return text if len(text) <= limit else text[:limit] + " ...(cut)"
            return call(env, agent, _op, arguments, limit)

        tools.append(FunctionTool(name=op["name"], description=_describe(op), params_json_schema=op["parameters"],
                                  on_invoke_tool=invoke, strict_json_schema=False))
    return tools


def briefing(env, agent: str) -> str:
    pub, o = env.public(), env.observe(agent)
    others = ", ".join(f"{n} ({r})" for n, r in pub["agents"].items() if n != agent)
    ops = "\n".join(f"- {op['name']}: {_describe(op)}" for op in env.ops(agent))
    alone = len(pub["agents"]) == 1
    team = ("You work alone on the problem (there is no team)." if alone else
            f"Others: {others}. Your neighbours (who you can message): {', '.join(o['neighbours']) or 'none'}.")
    return (f"You are {agent}, a {o['role']} "
            + ("working on a problem" if alone else "in a team working on a shared problem")
            + f". {o['role_doc']}\n"
            f"The problem: {json.dumps(pub['info'], default=str)}\n{team}\n"
            f"You have {o['budget']} actions; every operation costs actions as listed. The episode ends when the "
            "final task is done or " + ("your" if alone else "everyone's") + " budget is spent"
            + (f", or at round {o['deadline']} (a round passes when the team together has taken one action per "
               "member)" if o.get("deadline") else "") + ". Tasks are listed by the 'tasks' operation; a task "
            "opens when the tasks it depends on are done. Submitting a correct result for a task scores it.\n"
            + (("\nTasks you can work on now (the 'tasks' operation lists them all, with their state):\n"
                + "\n".join(f"- {t['id']}: {t['text']}" for t in o["workable"])) if o.get("workable") else "")
            + f"\nOperations:\n{ops}")
