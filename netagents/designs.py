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

    async def play(self, env, model, settings, calls: int) -> list[dict]:
        """Run with a hard cap of ``calls`` tool calls for the whole team."""
        self._pool = [calls]
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
# the reflection is added to its memory, and the next trial starts from a fresh scratchpad.
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
            notes = (REFLECTION_HEADER + "Reflections:\n- " + "\n- ".join(memory[-8:]) + "\n\n") if memory else ""
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
# again. Here every agent works with tools; its solution is what it states at the end of a round, and the
# solutions travel as messages through the network (charged and subject to its topology).
class Debate(Design):
    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        ms = {a: self.member(env, a, model, settings, REACT_INSTRUCTION) for a in names}
        per = -(-calls // (len(names) * self.rounds))
        for r in range(self.rounds):
            if _all_over(ms.values()):
                break
            if r == 0:
                await _together(list(ms.values()), "Can you solve the tasks? Explain your reasoning.", per)
            else:
                async def again(m):
                    got = env.step(m.name, "inbox", {}).get("messages", [])
                    others = "".join(f"\n\n One agent solution: ```{x['text']}```" for x in got
                                     if x["text"].startswith("solution:"))
                    await m.turn("These are the solutions to the tasks from other agents:" + others +
                                 "\n\n Using the solutions from other agents as additional information, can you "
                                 "provide your answer to the tasks? Submit the answers you are confident in.", per)
                await asyncio.gather(*(again(m) for m in ms.values()))
            if r < self.rounds - 1:
                for m in ms.values():
                    text = await m.say(SOLUTION)
                    env.step(m.name, "send", {"to": "*", "text": "solution: " + text[:3000]})
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
        ms = {a: self.member(env, a, model, settings, REACT_INSTRUCTION) for a in names}
        agg = ms[names[0]]
        layers = self.rounds  # proposer layers; then the aggregator
        per = -(-calls // (len(names) * layers + len(names)))

        def refs(m):
            got = env.step(m.name, "inbox", {}).get("messages", [])
            return "".join(f"\n{i + 1}. {x['text'][9:]}" for i, x in enumerate(
                [x for x in got if x["text"].startswith("response:")]))

        for layer in range(layers):
            if _all_over(ms.values()):
                break
            if layer == 0:
                await _together(list(ms.values()), "Work on the tasks.", per)
            else:
                await asyncio.gather(*(m.turn(AGGREGATE + refs(m) + "\n\nWork on the tasks.", per)
                                       for m in ms.values()))
            for m in ms.values():  # this layer's responses go to the next layer
                text = await m.say(SOLUTION)
                env.step(m.name, "send", {"to": "*", "text": "response: " + text[:3000]})
        await agg.turn(AGGREGATE + refs(agg) + "\n\nSynthesise the final answers and submit them.", per * len(names))
        return [m.report() for m in ms.values()]


# ====================================================================== reimplementations from papers
# Kim et al., Towards a Science of Scaling Agent Systems (arXiv 2512.08296): single, independent,
# centralized, decentralized and hybrid architectures under standardised tools, prompts and compute. No
# code was found; these follow the paper's names and summaries and must be checked against the paper.
class Independent(Design):
    async def run(self, env, model, settings, calls):
        ms = [self.member(env, a, model, settings, REACT_INSTRUCTION + " You work alone; nobody else's "
                          "results reach you.") for a in env.public()["agents"]]
        per = -(-calls // (len(ms) * self.rounds))
        for r in range(self.rounds):
            if _all_over(ms):
                break
            await _together(ms, "Begin." if r == 0 else "Continue.", per)
        return [m.report() for m in ms]


ORCH = ("You are the ORCHESTRATOR of this team. Look at the tasks, split the work, and assign it: tell each "
        "worker by message exactly what to do (send). Collect their results (inbox, and the shared store if "
        "they put things there), check them, and submit the results yourself: you are the only one who submits. "
        "Do the work yourself only when no worker can.")
WORK = ("You are a WORKER. Do what the orchestrator ({o}) assigns you, using your own tools. Report every "
        "result to the orchestrator by message (send) and, for anything long, put it in the shared store and "
        "send the key. You do not submit. {peers}")


class Centralized(Design):
    peers_talk = False

    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        o = names[0]
        peers = ("You may also message other workers when that saves work." if self.peers_talk else
                 "Talk only to the orchestrator.")
        boss = self.member(env, o, model, settings, REACT_INSTRUCTION + "\n" + ORCH)
        workers = [self.member(env, a, model, settings, REACT_INSTRUCTION + "\n" + WORK.format(o=o, peers=peers),
                               keep=lambda op: op != "submit") for a in names[1:]]
        per = -(-calls // (len(names) * self.rounds))
        for r in range(self.rounds):
            if _all_over([boss] + workers):
                break
            await boss.turn("Plan and assign." if r == 0 else "Read your inbox, check results, submit what is "
                            "ready, and assign the next work.", per)
            await _together(workers, "Read your inbox and do what you were assigned.", per)
        await boss.turn("Read your inbox and submit everything that is ready.", per)
        return [m.report() for m in [boss] + workers]


class Hybrid(Centralized):
    peers_talk = True


PEERS = ("You are one of several peers working the same problem; there is no leader. Work on the tasks with "
         "your tools and share what you find with your neighbours (send) or everyone (post). Read what others "
         "share before repeating their work. Anyone may submit.")


class Decentralized(Design):
    async def run(self, env, model, settings, calls):
        ms = [self.member(env, a, model, settings, REACT_INSTRUCTION + "\n" + PEERS) for a in env.public()["agents"]]
        per = -(-calls // (len(ms) * self.rounds))
        for r in range(self.rounds):
            if _all_over(ms):
                break
            await _together(ms, "Begin." if r == 0 else "Read what the others shared, then continue.", per)
        return [m.report() for m in ms]


# Han & Zhang, Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture (arXiv 2507.01701):
# a control unit, a blackboard and agents; the control unit picks the agents that act from the board's
# contents, until consensus. The authors' code was announced but not found; their agent roles (planner,
# critic, decider, ...) are not reproduced here.
BOARD = ("Everything you share goes on the shared board (post, and board to read); there are no direct "
         "messages. A control unit reads the board each round and decides who acts next. When you are called, "
         "read the board first, contribute what you can with your tools, and post what you found. Anyone may "
         "submit a task whose result the board makes clear.")


class Blackboard(Design):
    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        ms = {a: self.member(env, a, model, settings, REACT_INSTRUCTION + "\n" + BOARD,
                             keep=lambda op: op not in ("send", "inbox")) for a in names}
        control = ms[names[0]]
        per = -(-calls // (len(names) * self.rounds))
        for r in range(self.rounds):
            if _all_over(ms.values()):
                break
            posts = env.step(names[0], "board", {}).get("posts", []) if r else []
            pick = await control.say(
                "You are the control unit. The board:\n" + json.dumps(posts[-20:])[:4000] +
                f"\nAgents and roles: {json.dumps(env.public()['agents'])}.\nWhich agents should act next? Answer "
                "with their names only, separated by spaces.")
            chosen = [a for a in names if a in pick.split()] or names
            await _together([ms[a] for a in chosen], "You were chosen to act: read the board and contribute.",
                            per * len(names) // len(chosen))
        return [m.report() for m in ms.values()]


DESIGNS: dict[str, Design] = {d.name: d for d in [
    ReAct("react", "ReAct", "Yao et al., ReAct: Synergizing Reasoning and Acting in Language Models, ICLR 2023; "
          "code: ysymyth/ReAct, noahshinn/reflexion (MIT)", "port", "solo",
          ("native tool calls instead of Thought/Action text lines", "no few-shot examples (theirs are task-specific)")),
    Reflexion("reflexion", "Reflexion", "Shinn et al., Reflexion: Language Agents with Verbal Reinforcement "
              "Learning, NeurIPS 2023; code: noahshinn/reflexion (MIT)", "port", "solo",
              ("trials share one episode and its budget instead of re-running the same task",
               "a trial fails on a wrong submission or when its step quota runs out; the environment's verdict is "
               "the evaluator", "no few-shot reflection examples")),
    Debate("debate", "Multiagent debate", "Du et al., Improving Factuality and Reasoning in Language Models through "
           "Multiagent Debate, ICML 2024; code: composable-models/llm_multiagent_debate (no licence: prompt "
           "paraphrased)", "port", "team",
           ("agents use tools between rounds; a solution is what an agent states at the end of a round",
            "solutions travel as network messages (charged, limited to neighbours)",
            "agents submit themselves instead of a majority vote over final answers",
            "team size is the preset's, not 3"), rounds=2),
    MixtureOfAgents("moa", "Mixture-of-Agents", "Wang et al., Mixture-of-Agents Enhances Large Language Model "
                    "Capabilities, arXiv 2406.04692 (2024); code: togethercomputer/MoA (Apache-2.0)", "port", "team",
                    ("one model in every position instead of different open-source models",
                     "proposers use tools; their responses travel as network messages",
                     "the aggregate prompt is a user message, not a system message",
                     "the aggregator is one of the team, with its role's tools"), rounds=1),
    Independent("independent", "Independent", "Kim et al., Towards a Science of Scaling Agent Systems, arXiv "
                "2512.08296 (2025)", "reimplementation", "nonet",
                ("details of aggregation not checked against the paper",)),
    Centralized("centralized", "Centralized", "Kim et al. 2025", "reimplementation", "team",
                ("orchestrator protocol written from the paper's summary; prompts are ours",)),
    Decentralized("decentralized", "Decentralized", "Kim et al. 2025", "reimplementation", "team",
                  ("peer protocol written from the paper's summary; prompts are ours",)),
    Hybrid("hybrid", "Hybrid", "Kim et al. 2025", "reimplementation", "team",
           ("written from the paper's summary; prompts are ours",)),
    Blackboard("blackboard", "Blackboard", "Han & Zhang, Exploring Advanced LLM Multi-Agent Systems Based on "
               "Blackboard Architecture, arXiv 2507.01701 (2025)", "reimplementation", "team",
               ("the paper's agent roles are not reproduced", "one round per control step, a fixed number of rounds "
                "instead of until consensus", "code not released at the time of writing")),
]}


def cards_markdown() -> str:
    """The table of designs, their sources, fidelity and deviations (for docs/testset.md and the paper)."""
    rows = ["| design | source | fidelity | runs on | differs from the source |", "|---|---|---|---|---|"]
    for d in DESIGNS.values():
        rows.append(f"| `{d.name}` {d.label} | {d.source} | {d.fidelity} | {d.variant} | "
                    + "; ".join(d.deviations) + " |")
    return "\n".join(rows)
