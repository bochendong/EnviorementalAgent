"""Agent designs from published work, run on the network environment with matched compute.

Every design gets the same model, the same environment (a preset), the same total number of LLM tool
calls (``calls``: one pool for the whole team) and the same total environment budget (the preset's variant:
one agent with the team's budget for single-agent designs, the team otherwise). The environment is never
changed by a design.

How close each design is to its source is stated, not assumed (``Design.fidelity``):

    port            built from the authors' released code: their prompts (quoted, with the code's licence)
                    and their settings; adapted to tool use where the original answered in text
    reimplementation  built from the paper's description; no code was released (or found). To be checked
                    against the paper before publication
    framework       (netagents/frameworks/) the authors' own framework, driving our tools through an adapter

``Design.deviations`` lists what differs from the source, for a table in the paper. docs/testset.md has the
same list with the sources.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field, replace

from .tools import briefing, function_tools


@dataclass
class Member:
    """One LLM agent: its conversation persists across the segments a design schedules."""

    env: object
    name: str
    model: object
    settings: object
    protocol: str = ""
    keep: object = None  # op name -> allowed
    pool: list = None  # [tool calls the whole team has left]: compute is matched across designs
    history: list = field(default_factory=list)
    tokens: list = field(default_factory=lambda: [0, 0])
    calls: int = 0
    llm_requests: int = 0

    def __post_init__(self):
        from agents import Agent

        self.agent = Agent(name=self.name, instructions=briefing(self.env, self.name) + "\n\n" + self.protocol,
                           tools=function_tools(self.env, self.name, keep=self.keep), model=self.model,
                           model_settings=self.settings, tool_use_behavior=self._stop, reset_tool_choice=False)
        self._left = 0

    def finished(self) -> bool:
        o = self.env.observe(self.name)
        return o["episode_over"] or o["budget"] <= 0

    def _stop(self, ctx, results):
        from agents import ToolsToFinalOutputResult

        self.calls += len(results)
        self._left -= len(results)
        if self._left <= 0 or self.finished():
            return ToolsToFinalOutputResult(is_final_output=True, final_output="pause")
        return ToolsToFinalOutputResult(is_final_output=False)

    async def turn(self, message: str, max_calls: int) -> str:
        """Let the agent act for up to ``max_calls`` tool calls, continuing its conversation."""
        if self.pool is not None:  # reserve from the team's pool (members run concurrently); refund the rest
            max_calls = min(max_calls, self.pool[0])
        if max_calls <= 0 or self.finished():
            return ""
        if self.pool is not None:
            self.pool[0] -= max_calls
        self._left = max_calls
        try:
            return await self._turn(message, max_calls)
        finally:
            if self.pool is not None:
                self.pool[0] += max(0, self._left)

    async def _turn(self, message: str, max_calls: int) -> str:
        from agents import MaxTurnsExceeded, RunConfig, Runner

        try:
            res = await Runner.run(self.agent, self.history + [{"role": "user", "content": message}],
                                   max_turns=max_calls + 3, run_config=RunConfig(tracing_disabled=True))
        except MaxTurnsExceeded:
            return ""
        except Exception as e:  # noqa: BLE001 (one broken call must not stop the team)
            return f"error: {type(e).__name__}: {e}"[:300]
        self._account(res)
        self.history = res.to_input_list()
        return str(res.final_output or "")

    async def say(self, message: str) -> str:
        """A text answer without tools (reflections, a controller's choice); costs no environment budget."""
        from agents import Agent, RunConfig, Runner

        talker = Agent(name=f"{self.name}-text", instructions=self.agent.instructions, model=self.model,
                       model_settings=replace(self.settings, tool_choice=None))
        try:
            res = await Runner.run(talker, self.history + [{"role": "user", "content": message}], max_turns=1,
                                   run_config=RunConfig(tracing_disabled=True))
        except Exception:  # noqa: BLE001
            return ""
        self._account(res)
        return str(res.final_output or "")

    def _account(self, res):
        u = res.context_wrapper.usage
        self.tokens[0] += u.input_tokens
        self.tokens[1] += u.output_tokens
        self.llm_requests += u.requests

    def forget(self):
        """Start a fresh conversation (a new trial); tokens and calls keep counting."""
        self.history = []

    def report(self) -> dict:
        return {"agent": self.name, "tool_calls": self.calls, "llm_requests": self.llm_requests,
                "input_tokens": self.tokens[0], "output_tokens": self.tokens[1]}



def _all_over(members) -> bool:
    return all(m.finished() for m in members)


async def _together(members, message, k):
    await asyncio.gather(*(m.turn(message(m) if callable(message) else message, k) for m in members))


class Channel:
    """How a design's messages travel between its members.

    framework  the framework hands the text over, free and at once, as in the authors' code (the
               compatibility track)
    network    through the environment's network: a send is charged to the sender, reading the inbox to the
               receiver, latency and outages delay it, and a message to someone who is not a neighbour is lost
               (the network track). Speakers that are not agents of the environment (an orchestrator, a
               control unit) speak from a seat: the first agent.

    The board works the same way: in memory, or the environment's notice board."""

    def __init__(self, env, route: str = "framework"):
        if route not in ("framework", "network"):
            raise ValueError(f"unknown route {route!r}")
        self.env, self.route = env, route
        self.names = list(env.public()["agents"])
        self.seat = self.names[0]
        self.cfg = env.public()["config"]
        self.box: dict[str, list] = {a: [] for a in self.names}
        self.board: list[str] = []
        self.sent = self.lost = 0

    def _seat(self, who: str) -> str:
        return who if who in self.box else self.seat

    def send(self, src: str, dst: str, text: str, tag: str) -> str | None:
        """Deliver ``text`` from ``src`` to ``dst``; returns what arrived, or None if it was lost."""
        if self.route == "framework":
            self.sent += 1
            return text
        s, d = self._seat(src), self._seat(dst)
        if s == d:
            return text
        mark = f"[{tag}:{len(self.box[d])}:{self.sent}]"
        r = self.env.step(s, "send", {"to": d, "text": (mark + " " + text)[:self.cfg["max_message"] - 10]})
        if not r.get("ok"):
            self.lost += 1
            return None
        self.sent += 1
        for _ in range(2 * len(self.names) * (self.cfg["latency"] + self.cfg["outage_rounds"] + 1) + 2):
            self.box[d] += self.env.step(d, "inbox", {}).get("messages", [])
            for m in self.box[d]:
                if m["text"].startswith(mark):
                    self.box[d].remove(m)
                    return m["text"][len(mark) + 1:]
            o = self.env.observe(d)
            if o["episode_over"] or o["budget"] <= 0:
                break
            self.env.step(d, "wait", {})
        self.lost += 1
        return None

    def post(self, src: str, text: str):
        if self.route == "framework":
            self.board.append(text)
        elif not self.env.step(self._seat(src), "post", {"text": text[:self.cfg["max_message"] - 10]}).get("ok"):
            self.lost += 1
            return
        self.sent += 1

    def read(self, reader: str) -> list[str]:
        if self.route == "framework":
            return list(self.board)
        gone = getattr(self, "removed", set())
        return [p["text"] for p in self.env.step(self._seat(reader), "board", {}).get("posts", [])
                if p["by"] != "world" and p["text"] not in gone]

    def remove(self, texts: set):
        """Take messages off the board (LbMAS's cleaner); on the network the posts stay, the readers skip them."""
        self.board = [t for t in self.board if t not in texts]
        self.removed = getattr(self, "removed", set()) | set(texts)

    def report(self) -> dict:
        return {"route": self.route, "delivered": self.sent, "lost": self.lost}


SOLUTION = ("Stop and state your current solution: for every task you worked on, what you found and your answer "
            "or result so far. Do not call tools.")


@dataclass
class Design:
    name: str
    label: str
    source: str
    fidelity: str  # "port" | "reimplementation" | "framework"
    variant: str  # the preset variant it runs on: "solo", "nonet" or "team"
    deviations: tuple = ()
    rounds: int = 4

    async def run(self, env, model, settings, calls: int) -> list[dict]:
        raise NotImplementedError

    route: str = "framework"  # how messages travel (Channel); the evaluation sets it per track
    network_route = True  # False: the design's messages stay inside its framework whatever the track

    async def play(self, env, model, settings, calls: int) -> list[dict]:
        """Run with a hard cap of ``calls`` tool calls for the whole team."""
        self._pool = [calls]
        self.chan = Channel(env, self.route)
        return await self.run(env, model, settings, calls)

    def member(self, env, name, model, settings, protocol="", keep=None) -> Member:
        return Member(env, name, model, settings, protocol, keep, pool=self._pool)

    def card(self) -> dict:
        return {"name": self.name, "label": self.label, "source": self.source, "fidelity": self.fidelity,
                "variant": self.variant, "deviations": list(self.deviations)}


# ====================================================================== ports of released code
# ReAct: ysymyth/ReAct and the ReAct agent of noahshinn/reflexion (MIT licence). The instruction below is
# REACT_INSTRUCTION of reflexion/hotpotqa_runs/prompts.py with the three Wikipedia actions replaced by
# "one of your tools".
REACT_INSTRUCTION = ("Solve the task with interleaving Thought, Action, Observation steps. Thought can reason about "
                     "the current situation, and Action is one call of one of your tools; its result is the "
                     "Observation. You may take as many steps as necessary.")


class ReAct(Design):
    async def run(self, env, model, settings, calls):
        m = self.member(env, next(iter(env.public()["agents"])), model, settings, REACT_INSTRUCTION)
        per = -(-calls // self.rounds)
        msg = "Begin."
        for _ in range(self.rounds):
            if m.finished():
                break
            await m.turn(msg, per)
            msg = "Continue: there is work left."
        return [m.report()]


# Reflexion: noahshinn/reflexion (MIT licence). REFLECT_INSTRUCTION and REFLECTION_HEADER are quoted from
# hotpotqa_runs/prompts.py (the Docstore variant), with "Finish[<answer>]" read as "submit" and the
# Docstore API as "an environment". As in ReactReflectAgent.run: after a failed trial the agent reflects,
# the reflection is added to its memory, and the next trial starts from a fresh scratchpad. The memory
# shown is bounded to the last 3 reflections (the paper's Omega, Sec. 3 and 4.1-4.2: "the last 3
# self-reflections").
REFLECT_INSTRUCTION = ("You are an advanced reasoning agent that can improve based on self refection. You will be "
                       "given a previous reasoning trial in which you were given access to an environment and a "
                       "task to solve. You were unsuccessful in solving the task either because you submitted a "
                       "wrong answer, or you used up your set number of reasoning steps. In a few sentences, "
                       "Diagnose a possible reason for failure and devise a new, concise, high level plan that aims "
                       "to mitigate the same failure. Use complete sentences.")
REFLECTION_HEADER = ("You have attempted to answer following question before and failed. The following "
                     "reflection(s) give a plan to avoid failing to answer the question in the same way you did "
                     "previously. Use them to improve your strategy of correctly answering the given question.\n")


class Reflexion(Design):
    memory_size = 3  # Omega
    memory_path = ""  # a JSON file: reflections carried from episode to episode (set before running)

    async def run(self, env, model, settings, calls):
        name = next(iter(env.public()["agents"]))
        memory = _load(self.memory_path)
        m = self.member(env, name, model, settings, REACT_INSTRUCTION)
        per = -(-calls // self.rounds)
        seen_fail = 0
        for trial in range(self.rounds):
            if m.finished():
                break
            notes = (REFLECTION_HEADER + "Reflections:\n- " + "\n- ".join(memory[-self.memory_size:]) + "\n\n") if memory else ""
            await m.turn(notes + ("Begin." if trial == 0 else "Continue with the tasks still open."), per)
            fails = sum(1 for e in env.events() if e.get("kind") == "op" and e.get("agent") == name
                        and e.get("op") == "submit" and not e["obs"].get("ok"))
            if fails > seen_fail or not m.finished():  # a failed trial: a wrong submission, or steps used up
                seen_fail = fails
                text = await m.say(REFLECT_INSTRUCTION + "\n\nReflection:")
                if text:
                    memory.append(text.strip()[:800])
                m.forget()  # a new trial starts from a fresh scratchpad, with the reflections
        _save(self.memory_path, memory)
        return [m.report()]


def _load(path):
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def _save(path, memory):
    if path:
        with open(path, "w") as f:
            json.dump(memory[-50:], f, indent=1)


# Multiagent debate: composable-models/llm_multiagent_debate (no licence file: the prompt is paraphrased,
# not copied). Its gsm/gen_gsm.py: 3 agents, 2 rounds; in every round after the first, each agent is shown
# the other agents' solutions ("These are the solutions to the problem from other agents ... Using the
# solutions from other agents as additional information, can you provide your answer ...?") and answers
# again. Here every agent works with tools; its solution is what it states at the end of a round. The
# solutions reach the others through the design's channel (the framework, or the network).
class Debate(Design):
    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        ms = {a: self.member(env, a, model, settings, REACT_INSTRUCTION, keep=no_network) for a in names}
        per = -(-calls // (len(names) * self.rounds))
        solutions: dict[str, str] = {}
        for r in range(self.rounds):
            if _all_over(ms.values()):
                break
            if r == 0:
                await _together(list(ms.values()), "Can you solve the tasks? Explain your reasoning.", per)
            else:
                def message(m):
                    got = [self.chan.send(b, m.name, t, "solution") for b, t in solutions.items() if b != m.name]
                    others = "".join(f"\n\n One agent solution: ```{t}```" for t in got if t)
                    return ("These are the solutions to the tasks from other agents:" + others +
                            "\n\n Using the solutions from other agents as additional information, can you "
                            "provide your answer to the tasks? Submit the answers you are confident in.")
                await asyncio.gather(*(m.turn(message(m), per) for m in ms.values()))
            if r < self.rounds - 1:
                for m in ms.values():
                    solutions[m.name] = (await m.say(SOLUTION))[:3000]
        return [m.report() for m in ms.values()]


# Mixture-of-Agents: togethercomputer/MoA (Apache-2.0). AGGREGATE is the system prompt of
# utils.inject_references_to_messages, quoted. Layers: in layer 1 every proposer answers on its own; in
# later layers every proposer is given the previous layer's responses with that prompt; the last layer is
# one aggregator. The repository's default is rounds=1 (two layers: four proposers and one aggregator).
AGGREGATE = ("You have been provided with a set of responses from various open-source models to the latest user "
             "query. Your task is to synthesize these responses into a single, high-quality response. It is "
             "crucial to critically evaluate the information provided in these responses, recognizing that some "
             "of it may be biased or incorrect. Your response should not simply replicate the given answers but "
             "should offer a refined, accurate, and comprehensive reply to the instruction. Ensure your response "
             "is well-structured, coherent, and adheres to the highest standards of accuracy and reliability."
             "\n\nResponses from models:")


class MixtureOfAgents(Design):
    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        ms = {a: self.member(env, a, model, settings, REACT_INSTRUCTION, keep=no_network) for a in names}
        agg = ms[names[0]]
        layers = self.rounds  # proposer layers; then the aggregator
        per = -(-calls // (len(names) * layers + len(names)))
        responses: dict[str, str] = {}

        def refs(m):  # the previous layer's responses, each passed to m through the channel
            got = [self.chan.send(b, m.name, t, "response") for b, t in responses.items()]
            return "".join(f"\n{i + 1}. {t}" for i, t in enumerate(t for t in got if t))

        for layer in range(layers):
            if _all_over(ms.values()):
                break
            if layer == 0:
                await _together(list(ms.values()), "Work on the tasks.", per)
            else:
                await asyncio.gather(*(m.turn(AGGREGATE + refs(m) + "\n\nWork on the tasks.", per)
                                       for m in ms.values()))
            responses = {m.name: (await m.say(SOLUTION))[:3000] for m in ms.values()}
        await agg.turn(AGGREGATE + refs(agg) + "\n\nSynthesise the final answers and submit them.", per * len(names))
        return [m.report() for m in ms.values()]


# ====================================================================== shared by the ports below
NETWORK_OPS = {"send", "inbox", "post", "board", "put", "get", "keys", "transfer", "claim", "release"}


def no_network(op: str) -> bool:
    """In the ported frameworks, agents talk only through the framework (which passes messages for them),
    never through the environment's network: their workers have the task's tools only."""
    return op not in NETWORK_OPS


def fill(messages, **values) -> list[list[str]]:
    """Fill {{name}} variables of a [role, content] template (Kim et al.'s template syntax)."""
    out = []
    for role, content in messages:
        for k, v in values.items():
            content = content.replace("{{" + k + "}}", str(v))
        out.append([role, content])
    return out


def split(messages) -> tuple[str, str]:
    """(system text, user text) of a filled template."""
    return ("\n\n".join(c for r, c in messages if r == "system"), "\n\n".join(c for r, c in messages if r != "system"))


@dataclass
class Talker:
    """A model that only talks: Kim et al.'s orchestrator, LbMAS's control unit and predefined agents. No tools
    and no actions in the environment: it costs tokens, not tool calls. Each call is stateless, as in the
    authors' code (the template is compiled afresh every time)."""

    model: object
    settings: object
    tokens: list = field(default_factory=lambda: [0, 0])
    llm_requests: int = 0
    name: str = "talker"

    async def ask(self, system: str, user: str) -> str:
        from agents import Agent, RunConfig, Runner

        bot = Agent(name=self.name, instructions=system or None, model=self.model,
                    model_settings=replace(self.settings, tool_choice=None))
        try:
            res = await Runner.run(bot, user, max_turns=1, run_config=RunConfig(tracing_disabled=True))
        except Exception:  # noqa: BLE001
            return ""
        u = res.context_wrapper.usage
        self.tokens[0] += u.input_tokens
        self.tokens[1] += u.output_tokens
        self.llm_requests += u.requests
        return str(res.final_output or "")

    def report(self) -> dict:
        return {"agent": self.name, "tool_calls": 0, "llm_requests": self.llm_requests,
                "input_tokens": self.tokens[0], "output_tokens": self.tokens[1]}


def _json(text: str):
    """The first JSON object in a model's answer (or None)."""
    i = (text or "").find("{")
    while i >= 0:
        depth = 0
        for j in range(i, len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                try:
                    return json.loads(text[i:j + 1])
                except json.JSONDecodeError:
                    break
        i = text.find("{", i + 1)
    return None


def problem_text(env) -> str:
    """The problem as one text: the provider's description and the task list (read once, by the first agent)."""
    pub = env.public()
    first = next(iter(pub["agents"]))
    tasks = env.step(first, "tasks", {}).get("tasks", [])
    listing = "\n".join(f"- {t['id']} ({t['status']}): {t['text']}" for t in tasks)
    return f"{json.dumps(pub['info'], default=str)}\nTasks:\n{listing}"


# ====================================================================== Kim et al. 2025, ported
# Kim et al., Towards a Science of Scaling Agent Systems (arXiv 2512.08296 v3): code github.com/ybkim95/
# agent-scaling (MIT). Prompts: netagents/prompts/kim2025.py (their YAML templates). Control flow: their
# agents/multiagent_{independent,centralized,decentralized,hybrid}.py and multiagent_components/
# mas_lead_agent.py. Settings: the paper's Appendix E.2 (single agent: up to 10 iterations; independent: 3
# agents, synthesis only; centralized: 3 sub-agents and an orchestrator, at most 5 rounds, 3 iterations per
# agent per round; decentralized: 3 agents, 3 debate rounds, 3 iterations per round; hybrid: centralized
# plus a peer round). Their repository's YAML configs use larger limits (25 iterations, 10 rounds); we
# follow the paper. Iterations are tool calls here; every design stays inside the run's pool of calls.
from .prompts import kim2025 as K  # noqa: E402


def kim_worker(design, env, name, model, settings):
    system, user = split(fill(K.SUBAGENT, task_description_with_tools=briefing(env, name), task_behavior="",
                              task_instance="Use the 'tasks' operation to see the team's tasks."))
    return design.member(env, name, model, settings, system + "\n\n" + user, keep=no_network)


class KimSingle(Design):
    async def run(self, env, model, settings, calls):
        name = next(iter(env.public()["agents"]))
        system, user = split(fill(K.SINGLE, task_description_with_tools=briefing(env, name), task_behavior="",
                                  task_instance="Use the 'tasks' operation to see the tasks."))
        m = self.member(env, name, model, settings, system + "\n\n" + user)
        per = -(-calls // self.rounds)
        for r in range(self.rounds):
            if m.finished():
                break
            await m.turn("Begin." if r == 0 else "Continue.", per)
        return [m.report()]


INDEPENDENT_MESSAGE = (  # multiagent_independent.py, quoted
    "Solve the task completely on your own. Work systematically and submit when done.\n\n"
    "CRITICAL: You MUST make changes and submit within your iteration budget. Do NOT spend more than half your "
    "iterations on exploration/analysis. After understanding the problem, immediately start implementing the fix. "
    "If you reach 50% of your budget without making changes, STOP exploring and START implementing your best "
    "solution immediately.")


class KimIndependent(Design):
    async def run(self, env, model, settings, calls):
        ms = [kim_worker(self, env, a, model, settings) for a in env.public()["agents"]]
        await _together(ms, INDEPENDENT_MESSAGE, -(-calls // len(ms)))
        # synthesis_only: the answers are concatenated, without voting or comparison (kept for the record)
        self.synthesis = "\n\n".join([f"=== {m.name} ===\n{await m.say(K.SUBAGENT_SUMMARIZE[0][1])}" for m in ms])
        return [m.report() for m in ms]


class KimCentralized(Design):
    peer_round = False
    iterations = 3  # per agent per round (Appendix E.2)

    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        problem = problem_text(env)
        lead = Talker(model, settings, name="orchestrator")
        tools = "\n".join(f"- {a} ({env.public()['agents'][a]}): " + ", ".join(o["name"] for o in env.ops(a)
                                                                                if no_network(o["name"])) for a in names)
        base = fill(K.LEAD, task_description_with_tools="Your team and the tools each member can use:\n" + tools,
                    task_behavior="", task_instance=problem)

        async def ask(template, **v):
            return await lead.ask(*split(base + fill(template, **v)))

        workers = {a: kim_worker(self, env, a, model, settings) for a in names}
        ids = {f"agent_{i + 1}": a for i, a in enumerate(names)}
        plan = _json(await ask(K.LEAD_PLANNING, num_agents=len(names))) or {}
        sub = {ids.get(t.get("agent_id")): t for t in plan.get("subtasks", []) if ids.get(t.get("agent_id"))}
        for i, a in enumerate(names):  # the authors' simple plan when planning fails
            sub.setdefault(a, {"objective": f"Work on part {i + 1} of the task", "focus": f"Approach {i + 1}"})
        findings: dict[str, list[str]] = {a: [] for a in names}
        rounds = 0
        for r in range(1, self.rounds + 1):
            active = [a for a in names if not workers[a].finished()]
            if not active:
                break
            rounds = r
            team = "\n".join(f"{a}: {f[-1][:300]}" for a, f in findings.items() if f) or "(no findings yet)"
            msgs = {}
            for a in active:
                guidance = await ask(K.LEAD_COORDINATION, original_query=problem, round_num=r, agent_id=a,
                                     agent_objective=sub[a].get("objective", ""),
                                     agent_strategy=sub[a].get("focus", ""), agent_iterations=workers[a].calls,
                                     min_iterations=3, agent_status="active",
                                     agent_findings_summary="\n".join(findings[a][-3:]) or "(none yet)",
                                     team_context=team)
                text = (split(fill(K.SUBAGENT_START, orchestrator_objective=sub[a].get("objective", ""),
                                   orchestrator_guidance=guidance))[1] if r == 1 else guidance)
                msgs[a] = self.chan.send("orchestrator", a, text, "guidance") or "Continue with your objective."
            await asyncio.gather(*(workers[a].turn(msgs[a], self.iterations) for a in active))
            for a in active:
                got = self.chan.send(a, "orchestrator", await workers[a].say(K.SUBAGENT_SUMMARIZE[0][1]), "finding")
                if got:
                    findings[a].append(got)
            everything = "\n".join(f"{a} (round {i + 1}): {f}" for a, fs in findings.items() for i, f in enumerate(fs))
            decision = await ask(K.LEAD_STOPPING, query=problem, round_num=r,
                                 total_findings=sum(len(f) for f in findings.values()), total_agents=len(names),
                                 current_round_summary="\n".join(f"{a}: {findings[a][-1][:300]}" for a in active),
                                 all_findings=everything[-6000:])
            if decision.strip().upper().startswith("STOP"):
                break
        if self.peer_round:  # multiagent_hybrid.py: a final round with the peers' findings injected
            peers = {a: "\n\n## Direct Peer Findings (shared peer-to-peer)\n" + "\n".join(
                f"[PEER {b}]: {t}" for b in names if b != a and findings[b]
                for t in [self.chan.send(b, a, findings[b][-1][:400], "peer")] if t)
                for a in names}
            await asyncio.gather(*(workers[a].turn(
                "Final round with peer insights. Review your peers' work and finalize your solution." + peers[a],
                self.iterations) for a in names if not workers[a].finished()))
        everything = "\n".join(f"{a}: {f}" for a, fs in findings.items() for f in fs)
        synthesis = await ask(K.LEAD_SYNTHESIS, all_findings=everything[-8000:])
        # the authors' auto-submit goes through the first sub-agent's environment
        synthesis = self.chan.send("orchestrator", names[0], synthesis, "synthesis") or "(the synthesis was lost)"
        await workers[names[0]].turn("The lead agent's synthesis of the team's findings:\n" + synthesis +
                                     "\n\nSubmit every result that is ready.", self.iterations)
        self.rounds_used = rounds
        return [lead.report()] + [w.report() for w in workers.values()]


class KimHybrid(KimCentralized):
    peer_round = True


def kim_debate_prompt(agent: str, r: int, rounds: int, answers: dict) -> str:
    """multiagent_decentralized.py's _round_prompt, quoted."""
    if r == 1:
        return ("Round 1: produce your best candidate answer to the task independently. Use the available tools "
                "and submit your final answer when ready.")
    blocks = [f"--- Peer response from {a} (round {r - 1}) ---\n{t}" for a, t in answers.items() if a != agent and t]
    peers = "\n\n".join(blocks) or "(no peer responses available from the previous round)"
    return (f"Debate round {r} of {rounds}.\n\nBelow are your peers' answers from the previous round. Read them "
            "carefully. Identify points where you agree, points where they erred, and points where you missed "
            "something. Then produce your updated final answer for this round. You may defend your previous answer, "
            f"refine it, or replace it.\n\n{peers}\n\nProduce your updated final answer now.")


class KimDecentralized(Design):
    iterations = 3

    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        ms = {a: kim_worker(self, env, a, model, settings) for a in names}
        answers: dict[str, str] = {}
        for r in range(1, self.rounds + 1):
            active = [a for a in names if not ms[a].finished()]
            if not active:
                break
            heard = {a: {b: self.chan.send(b, a, t, "peer") for b, t in answers.items() if b != a} for a in active}
            await asyncio.gather(*(ms[a].turn(kim_debate_prompt(a, r, self.rounds, heard[a]), self.iterations)
                                   for a in active))
            for a in active:
                answers[a] = await ms[a].say(K.SUBAGENT_SUMMARIZE[0][1])
        votes = [t.strip() for t in answers.values() if t.strip()]  # consensus: majority over final answers
        self.consensus = max(set(votes), key=votes.count) if votes else ""
        return [m.report() for m in ms.values()]


# ====================================================================== LbMAS (Han & Zhang 2025), ported
# Han & Zhang, Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture (arXiv
# 2507.01701v1). Algorithm 1 and Section 3: query-related experts are generated (1-3, by an LLM), the
# predefined agents are decider, planner, critic, cleaner and conflict-resolver; each round the control unit
# chooses agents from the blackboard's contents, each chosen agent reads the whole blackboard and writes its
# output to it; the cleaner's useless messages are removed; the cycle stops when the decider gives an answer
# or after K = 4 rounds. Prompts: netagents/prompts/han2025.py (the paper's Figures 4-6). Here the team's
# members (who hold the environment's tools) join as experts of their role; the predefined and generated
# agents only talk.
from .prompts import han2025 as H  # noqa: E402


class LbMAS(Design):
    iterations = 3  # tool calls of a team member each time it is chosen

    async def run(self, env, model, settings, calls):
        pub = env.public()
        names = list(pub["agents"])
        question = problem_text(env)
        talker = Talker(model, settings, name="lbmas-talkers")
        experts = _json(await talker.ask("", H.AGENT_GENERATION.replace("{question}", question))) or {}
        experts = {str(k)[:60]: str(v)[:300] for k, v in list(experts.items())[:3]}
        roles = {**{k: v for k, v in H.DESCRIPTIONS.items()}, **experts,
                 **{a: f"a team member ({pub['agents'][a]}) who can act in the environment with its tools"
                    for a in names}}
        team = {a: self.member(env, a, model, settings, H.SYSTEM.replace("{role_name}", a).replace(
            "{question}", question) + "\n\n" + H.GENERATED_EXPERT.replace("{role}", pub["agents"][a]).replace(
            "{roles_description}", env.observe(a)["role_doc"]), keep=no_network) for a in names}
        decided = ""
        seat = names[0]

        def shown(reader: str) -> str:  # the blackboard, as the channel delivers it to ``reader``
            return "\n".join(self.chan.read(reader))[-8000:] or "(empty)"

        for _ in range(self.rounds):
            listing = "\n".join(f"{k}: {v}" for k, v in roles.items())
            pick = _json(await talker.ask("", H.CONTROL_UNIT.replace("{role_list}", listing).replace(
                "{question}", question) + "\nBlackboard:\n" + shown(seat))) or {}
            chosen = [c for c in pick.get("chosen agents", []) if c in roles] or names
            for c in chosen:  # Algorithm 1: chosen agents act one after another, each reading the blackboard
                if c in team:
                    m = team[c]
                    await m.turn("The blackboard:\n" + shown(c) + "\n\nContribute with your tools.", self.iterations)
                    text = await m.say("Write on the blackboard what you found, in the json form {\"output\":\"\"}.")
                else:
                    prompt = H.PREDEFINED.get(c) or H.GENERATED_EXPERT.replace("{role}", c).replace(
                        "{roles_description}", roles[c])
                    text = await talker.ask(H.SYSTEM.replace("{role_name}", c).replace("{question}", question),
                                            prompt + "\n\nThe blackboard:\n" + shown(c))
                if c == "cleaner":
                    useless = {x.get("useless message") for x in (_json(text) or {}).get("clean list", [])
                               if isinstance(x, dict)}
                    useless = {u for u in useless if isinstance(u, str) and u.strip()}
                    self.chan.remove({t for t in self.chan.read(seat) if any(u in t for u in useless)})
                    continue
                self.chan.post(c, f"[{c}] {text[:2000]}")
                if c == "decider" and "boxed" in text:
                    decided = text
            if decided:
                break
        # the decider's solution is handed to the team members, who hold the submit tool
        await _together(list(team.values()), "The blackboard's decision:\n" + (decided or shown(seat)[-3000:]) +
                        "\n\nSubmit every result that is ready.", self.iterations)
        return [talker.report()] + [m.report() for m in team.values()]


DESIGNS: dict[str, Design] = {d.name: d for d in [
    ReAct("react", "ReAct", "Yao et al., ReAct: Synergizing Reasoning and Acting in Language Models, ICLR 2023; "
          "code: ysymyth/ReAct, noahshinn/reflexion (MIT)", "port", "solo",
          ("native tool calls instead of Thought/Action text lines", "no few-shot examples (theirs are task-specific)",
           "the step limit is the call budget (the paper: 7 steps on HotpotQA, 5 on FEVER, 50 on ALFWorld), and "
           "the agent is prompted to continue when it stops with tasks left", "no back-off to CoT-SC")),
    Reflexion("reflexion", "Reflexion", "Shinn et al., Reflexion: Language Agents with Verbal Reinforcement "
              "Learning, NeurIPS 2023; code: noahshinn/reflexion (MIT)", "port", "solo",
              ("trials share one episode and its budget instead of re-running the same task",
               "a trial fails on a wrong submission or when its step quota runs out; the environment's verdict is "
               "the evaluator, not the paper's ALFWorld heuristic (the same action and observation more than 3 "
               "times, or more than 30 actions)", "no few-shot reflection examples")),
    Debate("debate", "Multiagent debate", "Du et al., Improving Factuality and Reasoning in Language Models through "
           "Multiagent Debate, ICML 2024; code: composable-models/llm_multiagent_debate (no licence: prompt "
           "paraphrased)", "port", "team",
           ("agents use tools between rounds; a solution is what an agent states at the end of a round",
            "solutions pass through the design's channel (the framework, or the environment's network)",
            "agents submit themselves instead of a majority vote over final answers",
            "team size is the preset's, not 3"), rounds=2),
    MixtureOfAgents("moa", "Mixture-of-Agents", "Wang et al., Mixture-of-Agents Enhances Large Language Model "
                    "Capabilities, arXiv 2406.04692 (2024); code: togethercomputer/MoA (Apache-2.0)", "port", "team",
                    ("one model in every position instead of different open-source models",
                     "proposers use tools; their responses pass through the design's channel",
                     "the aggregate prompt is a user message, not a system message",
                     "the aggregator is one of the team, with its role's tools"), rounds=1),
    KimSingle("sas", "Single-agent system (Kim et al.)", "Kim et al., Towards a Science of Scaling Agent Systems, arXiv "
              "2512.08296 v3 (2026); code: ybkim95/agent-scaling (MIT)", "port", "solo",
              ("iterations are tool calls; the single agent gets the team's whole pool of calls (the paper gives it "
               "proportionally more iterations)",), rounds=4),
    KimIndependent("independent", "Independent (Kim et al.)", "Kim et al. 2026; code: ybkim95/agent-scaling (MIT)",
                   "port", "nonet",
                   ("the agents act in one shared environment, not in a copy each",
                    "the synthesis-only aggregate is recorded but not submitted: our submissions need a task and "
                    "an artifact, so each agent submits its own",
                    "team size is the preset's, not 3")),
    KimCentralized("centralized", "Centralized (Kim et al.)", "Kim et al. 2026; code: ybkim95/agent-scaling (MIT)",
                   "port", "team",
                   ("the orchestrator reads the task list once through the first worker (one action)",
                    "the final auto-submit is a turn of the first worker given the synthesis",
                    "orchestrator-worker messages pass through the design's channel: the framework, as in the "
                    "authors' code, or the environment's network", "team size is the preset's, not 3"), rounds=5),
    KimDecentralized("decentralized", "Decentralized (Kim et al.)", "Kim et al. 2026; code: ybkim95/agent-scaling "
                     "(MIT)", "port", "team",
                     ("the consensus vote over final answers is recorded; agents submit their own results",
                      "peer answers pass through the design's channel (the framework, or the network)",
                      "team size is the preset's, not 3"), rounds=3),
    KimHybrid("hybrid", "Hybrid (Kim et al.)", "Kim et al. 2026; code: ybkim95/agent-scaling (MIT)", "port", "team",
              ("as centralized, plus the authors' final peer round", "team size is the preset's, not 3"), rounds=5),
    LbMAS("blackboard", "LbMAS blackboard system", "Han & Zhang, Exploring Advanced LLM Multi-Agent Systems Based on "
          "Blackboard Architecture, arXiv 2507.01701v1 (2025); prompts from the paper (code not released)", "port",
          "team",
          ("the team's members (with the environment's tools) join as experts of their roles, besides 1-3 "
           "generated experts", "one model for every agent instead of one drawn per agent from two models",
           "no private spaces (debate, self-reflection)", "the decider's answer is handed to the team members to "
           "submit", "solution by the decider only (not the similarity vote)"), rounds=4),
]}


def cards_markdown() -> str:
    """The table of designs, their sources, fidelity and deviations (for docs/testset.md and the paper)."""
    from .frameworks import FRAMEWORK_DESIGNS

    rows = ["| design | source | fidelity | runs on | differs from the source |", "|---|---|---|---|---|"]
    for d in [*DESIGNS.values(), *FRAMEWORK_DESIGNS.values()]:
        rows.append(f"| `{d.name}` {d.label} | {d.source} | {d.fidelity} | {d.variant} | "
                    + "; ".join(d.deviations) + " |")
    return "\n".join(rows)
