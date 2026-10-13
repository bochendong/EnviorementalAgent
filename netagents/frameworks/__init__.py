"""Agent designs that are the authors' own frameworks, run in their own Python environments.

A framework design serves the episode's environment over HTTP (worldseeds.net.server) and runs the
framework as a subprocess against it (netagents/frameworks/<framework>_teams.py), with the same model
server (WS_BASE_URL, WS_MODEL) and the same pool of tool calls as every other design. The subprocess's
Python is given by an environment variable, e.g. NETAGENTS_PY_AUTOGEN=/path/to/venv-autogen/bin/python.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import HTTPServer

from ..designs import Design


class FrameworkDesign(Design):
    module: str = ""
    team: str = ""
    python_var: str = ""
    network_route = False  # AutoGen and CAMEL pass their messages themselves

    async def run(self, env, model, settings, calls):
        from worldseeds.net.server import make_handler

        raw = env._env  # this design needs the environment in this process to serve it
        srv = HTTPServer(("127.0.0.1", 0), make_handler(raw))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        python = os.environ.get(self.python_var, sys.executable)
        try:
            out = subprocess.run([python, "-m", self.module, "--remote", f"http://127.0.0.1:{srv.server_address[1]}",
                                  "--team", self.team, "--calls", str(calls)], capture_output=True, text=True,
                                 timeout=int(os.environ.get("NETAGENTS_FRAMEWORK_TIMEOUT", "7200")),
                                 cwd=os.path.join(os.path.dirname(__file__), "..", ".."))
        finally:
            srv.shutdown()
        line = next((ln for ln in reversed(out.stdout.splitlines()) if ln.startswith("{")), None)
        if line is None:
            raise RuntimeError(f"{self.name} failed: {out.stderr[-1500:]}")
        r = json.loads(line)
        return [{"agent": "team", "tool_calls": r["tool_calls"], "llm_requests": 0,
                 "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"], "error": r.get("error", "")}]


def _autogen(name, label, team, source, deviations):
    d = FrameworkDesign(name, label, source, "framework", "team", deviations)
    d.module, d.team, d.python_var = "netagents.frameworks.autogen_teams", team, "NETAGENTS_PY_AUTOGEN"
    return d


def _camel(name, label, team, source, deviations):
    d = FrameworkDesign(name, label, source, "framework", "solo", deviations)
    d.module, d.team, d.python_var = "netagents.frameworks.camel_teams", team, "NETAGENTS_PY_CAMEL"
    return d


COMMON = ("members talk in the framework's shared conversation, outside the environment's network (not charged, "
          "no topology)",)
FRAMEWORK_DESIGNS = {d.name: d for d in [
    _autogen("autogen-roundrobin", "AutoGen round-robin group chat", "roundrobin",
             "Wu et al., AutoGen, COLM 2024 (arXiv 2308.08155); autogen-agentchat 0.7.5 (MIT)",
             COMMON + ("a fixed speaking order: a team of the AutoGen library, not one evaluated in the paper",)),
    _autogen("autogen-selector", "AutoGen group chat with a model-selected speaker", "selector",
             "Wu et al., AutoGen, COLM 2024 (arXiv 2308.08155): the dynamic group chat of Sec. 3 (A5), where a "
             "manager selects the next speaker and broadcasts its message; autogen-agentchat 0.7.5 (MIT)",
             COMMON + ("SelectorGroupChat of AutoGen 0.7 stands for the paper's GroupChatManager (AutoGen 0.2)",)),
    _autogen("magentic-one", "Magentic-One orchestrator", "magentic",
             "Fourney et al., Magentic-One, arXiv 2411.04468 (2024); autogen-agentchat 0.7.5 (MIT)",
             COMMON + ("the orchestrator directs our role agents instead of Magentic-One's web, file and code "
                       "agents",)),
    _camel("camel-roleplay", "CAMEL role playing", "roleplay",
           "Li et al., CAMEL: Communicative Agents for \"Mind\" Exploration of Large Language Model Society, "
           "NeurIPS 2023; camel-ai 0.2.90 (Apache-2.0)",
           ("the assistant is the solo agent with every tool and the team's budget; the user agent has no tools",
            "no task-specifier agent: the task given is already precise",
            "the paper's termination conditions are kept (40 messages, 3 rounds without an instruction, the "
            "end-of-task token) except role reversal, which is not detected")),
]}
