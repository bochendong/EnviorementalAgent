"""AutoGen teams on the network environment: the authors' framework, driving our tools.

Runs in its own Python environment (pip install "autogen-agentchat==0.7.5" "autogen-ext[openai]==0.7.5"),
against an environment served over HTTP, and prints one JSON line with what it spent:

    python -m netagents.frameworks.autogen_teams --remote http://127.0.0.1:8090 --team selector --calls 160

Teams (autogen_agentchat 0.7.5, used as released; only the participants and their tools are ours):
    roundrobin   RoundRobinGroupChat: members speak in turn in one shared conversation
    selector     SelectorGroupChat: a model picks the next speaker from the conversation (AutoGen's group chat
                 manager; Wu et al., AutoGen, arXiv 2308.08155, 2023)
    magentic     MagenticOneGroupChat: the Magentic-One orchestrator with its task and progress ledgers
                 (Fourney et al., Magentic-One, arXiv 2411.04468, 2024), directing our members

Every member is an AssistantAgent with the operations of its role as tools. Tool calls come out of one pool
of ``--calls``; when it is empty, or the episode is over, the team is stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from pydantic import ConfigDict, create_model

from netagents.client import RemoteEnv
from netagents.tools import briefing


def make_tools(env, agent, pool, stop):
    from autogen_core.tools import BaseTool

    class EnvTool(BaseTool):
        def __init__(self, op):
            props = op["parameters"]["properties"]
            req = set(op["parameters"]["required"])
            Args = create_model(f"{op['name']}_args", __config__=ConfigDict(extra="allow"),
                                **{k: (Any, ... if k in req else None) for k in props})
            super().__init__(Args, str, op["name"], f"{op['doc']} [costs {op['cost']} action(s)]")
            self._schema = op["parameters"]

        @property
        def schema(self):
            return {"name": self.name, "description": self.description, "parameters": self._schema}

        async def run(self, args, cancellation_token):
            if pool[0] <= 0:
                stop.set()
                return json.dumps({"ok": False, "error": "the team has used all its tool calls"})
            pool[0] -= 1
            obs = env.step(agent, self.name, {k: v for k, v in args.model_dump().items() if v is not None})
            if pool[0] <= 0 or env.observe(agent)["episode_over"]:
                stop.set()
            return json.dumps(obs, default=str)[:6000]

    return [EnvTool(op) for op in env.ops(agent)]


async def main_async(a):
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import ExternalTermination, MaxMessageTermination
    from autogen_agentchat.teams import MagenticOneGroupChat, RoundRobinGroupChat, SelectorGroupChat
    from autogen_ext.models.openai import OpenAIChatCompletionClient

    env = RemoteEnv(a.remote)
    client = OpenAIChatCompletionClient(
        model=os.environ.get("WS_MODEL", "qwen3-8b"), base_url=os.environ.get("WS_BASE_URL", "http://localhost:8000/v1"),
        api_key=os.environ.get("WS_API_KEY", "EMPTY"), temperature=0.3,
        max_tokens=int(os.environ.get("WS_MAX_TOKENS", "1024")),
        model_info={"vision": False, "function_calling": True, "json_output": False, "family": "unknown",
                    "structured_output": False})
    pool, stop_cond = [a.calls], ExternalTermination()

    class Stop:
        def set(self):
            stop_cond.set()

    names = list(env.public()["agents"])
    members = [AssistantAgent(n, client, tools=make_tools(env, n, pool, Stop()), system_message=briefing(env, n),
                              description=f"{n}, the team's {env.public()['agents'][n]}",
                              reflect_on_tool_use=False, max_tool_iterations=a.tool_iterations)
               for n in names]
    term = stop_cond | MaxMessageTermination(a.calls * 4)
    if a.team == "roundrobin":
        team = RoundRobinGroupChat(members, termination_condition=term)
    elif a.team == "selector":
        team = SelectorGroupChat(members, client, termination_condition=term)
    else:
        team = MagenticOneGroupChat(members, client, termination_condition=term, max_turns=a.calls)
    task = ("Solve the team's tasks. Use the 'tasks' operation to see them; submit results with 'submit'. "
            f"The problem: {json.dumps(env.public()['info'], default=str)}")
    error = ""
    try:
        await team.run(task=task)
    except Exception as e:  # noqa: BLE001 (report what was spent even when the framework fails)
        error = f"{type(e).__name__}: {e}"[:300]
    u = client.total_usage()
    print(json.dumps({"tool_calls": a.calls - pool[0], "input_tokens": u.prompt_tokens,
                      "output_tokens": u.completion_tokens, "error": error}))
    await client.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remote", required=True)
    ap.add_argument("--team", choices=["roundrobin", "selector", "magentic"], default="selector")
    ap.add_argument("--calls", type=int, default=100)
    ap.add_argument("--tool-iterations", type=int, default=3, help="tool calls an agent may chain in one turn")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
