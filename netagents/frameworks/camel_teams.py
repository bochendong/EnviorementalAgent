"""CAMEL role-playing on the network environment: the authors' framework, driving our tools.

Runs in its own Python environment (pip install "camel-ai==0.2.90" "mcp>=1.3,<2"), against an environment
served over HTTP, and prints one JSON line with what it spent:

    python -m netagents.frameworks.camel_teams --remote http://127.0.0.1:8090 --team roleplay --calls 160

    roleplay   camel.societies.RolePlaying (Li et al., CAMEL: Communicative Agents for "Mind" Exploration of
               Large Language Model Society, NeurIPS 2023): an AI user gives instructions, an AI assistant
               carries them out. The assistant is the solo agent with every tool; the user has none.

Tool calls come out of one pool of ``--calls``; the conversation stops when it is empty, when the episode
is over, or when either side ends the role play.
"""

from __future__ import annotations

import argparse
import json
import os

from netagents.client import RemoteEnv
from netagents.tools import briefing


def offline_counter():
    """CAMEL's default token counter downloads a tiktoken table; compute nodes are offline. It is only used
    to trim CAMEL's context window; the tokens we report come from the server's usage."""
    from camel.utils import BaseTokenCounter

    class Approx(BaseTokenCounter):
        def count_tokens_from_messages(self, messages):
            return sum(len(str(m.get("content") or "")) // 4 + 4 for m in messages)

        def encode(self, text):
            return list(range(len(text) // 4))

        def decode(self, token_ids):
            return ""

    return Approx()


def make_tools(env, agent, pool):
    from camel.toolkits import FunctionTool

    tools = []
    for op in env.ops(agent):
        def call(_op=op["name"], **kwargs):
            if pool[0] <= 0:
                return json.dumps({"ok": False, "error": "the team has used all its tool calls"})
            pool[0] -= 1
            return json.dumps(env.step(agent, _op, {k: v for k, v in kwargs.items() if v is not None}),
                              default=str)[:6000]
        call.__name__ = op["name"]
        call.__doc__ = op["doc"]
        tools.append(FunctionTool(call, openai_tool_schema={"type": "function", "function": {
            "name": op["name"], "description": f"{op['doc']} [costs {op['cost']} action(s)]",
            "parameters": op["parameters"]}}))
    return tools


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remote", required=True)
    ap.add_argument("--team", choices=["roleplay"], default="roleplay")
    ap.add_argument("--calls", type=int, default=100)
    ap.add_argument("--tool-iterations", type=int, default=3, help="tool calls the assistant may chain in one step")
    ap.add_argument("--max-messages", type=int, default=40, help="the paper's limit (Sec. 4, termination conditions)")
    a = ap.parse_args()
    from camel.models import ModelFactory
    from camel.societies import RolePlaying
    from camel.types import ModelPlatformType

    env = RemoteEnv(a.remote)
    me = next(iter(env.public()["agents"]))
    model = ModelFactory.create(model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
                                model_type=os.environ.get("WS_MODEL", "qwen3-8b"),
                                url=os.environ.get("WS_BASE_URL", "http://localhost:8000/v1"),
                                api_key=os.environ.get("WS_API_KEY", "EMPTY"), token_counter=offline_counter(),
                                model_config_dict={"temperature": 0.3,
                                                   "max_tokens": int(os.environ.get("WS_MAX_TOKENS", "1024"))})
    pool = [a.calls]
    task = briefing(env, me) + "\nSolve the tasks: list them with 'tasks' and submit results with 'submit'."
    society = RolePlaying(assistant_role_name="Problem solver with the team's tools", user_role_name="Instructor",
                          task_prompt=task, with_task_specify=False, model=model,
                          assistant_agent_kwargs={"tools": make_tools(env, me, pool),
                                                  "max_iteration": a.tool_iterations},
                          user_agent_kwargs={"max_iteration": 1})
    tokens, error = [0, 0], ""

    def count(resp):
        u = (resp.info or {}).get("usage") or {}
        tokens[0] += u.get("prompt_tokens", 0) or 0
        tokens[1] += u.get("completion_tokens", 0) or 0

    try:
        msg = society.init_chat()
        idle = 0  # the paper's "user no instruct": the chat ends after 3 rounds without an instruction
        for _ in range(a.max_messages // 2):  # a step is two messages, the user's and the assistant's
            assistant, user = society.step(msg)
            count(assistant)
            count(user)
            if assistant.terminated or user.terminated or pool[0] <= 0 or env.observe(me)["episode_over"]:
                break
            said = user.msg.content if user.msg else ""
            if "CAMEL_TASK_DONE" in said:
                break
            idle = 0 if "Instruction:" in said else idle + 1
            if idle >= 3:
                break
            msg = assistant.msg
    except Exception as e:  # noqa: BLE001 (report what was spent even when the framework fails)
        error = f"{type(e).__name__}: {e}"[:300]
    print(json.dumps({"tool_calls": a.calls - pool[0], "input_tokens": tokens[0], "output_tokens": tokens[1],
                      "error": error}))


if __name__ == "__main__":
    main()
