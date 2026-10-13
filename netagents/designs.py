"""Published agent designs, run on the network environment with the same tools and the same budgets.

Every design gets the same model, the same environment (a preset), the same total number of LLM tool
calls (``calls``, split over its members and rounds) and the same total environment budget (the preset's
variant: one agent with the team's budget for single-agent designs, the team otherwise). They differ only
in what the papers differ in: who may do what, what each member is told about the protocol, and the
order in which members act. The environment is never changed by a design.

    react         Yao et al., ReAct (ICLR 2023): one agent interleaving reasoning and tool calls.
    reflexion     Shinn et al., Reflexion (NeurIPS 2023): ReAct plus verbal self-reflection after
                  failures, kept in an episodic memory (optionally across episodes).
    independent   Kim et al., Towards a Science of Scaling Agent Systems (2025), "independent": n agents
                  in parallel, no communication (the nonet variant).
    centralized   Kim et al. 2025 "centralized"; the orchestrator-worker pattern of AutoGen's group chat
                  manager (Wu et al. 2023) and MetaGPT's managers: one orchestrator assigns, workers
                  report, only the orchestrator submits.
    decentralized Kim et al. 2025 "decentralized"; Du et al., multiagent debate (ICML 2024): peers work,
                  publish their current results each round, read the others' and revise.
    hybrid        Kim et al. 2025 "hybrid": an orchestrator, and workers who may also talk to each other.
    blackboard    Han & Zhang 2025; Salemi et al. 2025: all communication through a shared board; a
                  control unit reads the board each round and chooses who acts.
    moa           Wang et al., Mixture-of-Agents (2024): layers of proposers, each layer reading the
                  previous layer's outputs; an aggregator gives the final answers.
    metagpt       Hong et al., MetaGPT (ICLR 2024): an assembly line of roles following a standard
                  operating procedure, publishing structured documents to a shared pool and reading
                  only the roles they depend on (publish-subscribe).

Prompts paraphrase the papers' protocols; nothing in them is specific to a task provider.
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
        if self.pool is not None:
            self.pool[0] -= len(results)
        if self._left <= 0 or self.finished():
            return ToolsToFinalOutputResult(is_final_output=True, final_output="pause")
        return ToolsToFinalOutputResult(is_final_output=False)

    async def turn(self, message: str, max_calls: int) -> str:
        """Let the agent act for up to ``max_calls`` tool calls, continuing its conversation."""
        from agents import MaxTurnsExceeded, RunConfig, Runner

        if self.pool is not None:
            max_calls = min(max_calls, self.pool[0])
        if max_calls <= 0 or self.finished():
            return ""
        self._left = max_calls
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

    def report(self) -> dict:
        return {"agent": self.name, "tool_calls": self.calls, "llm_requests": self.llm_requests,
                "input_tokens": self.tokens[0], "output_tokens": self.tokens[1]}


def _all_over(members) -> bool:
    return all(m.finished() for m in members)


async def _together(members, message, k):
    await asyncio.gather(*(m.turn(message(m) if callable(message) else message, k) for m in members))


@dataclass
class Design:
    name: str
    paper: str
    variant: str  # the preset variant it runs on: "solo" (single agent), "nonet" or "team"
    rounds: int = 4

    async def run(self, env, model, settings, calls: int) -> list[dict]:
        raise NotImplementedError

    async def play(self, env, model, settings, calls: int) -> list[dict]:
        """Run with a hard cap of ``calls`` tool calls for the whole team."""
        self._pool = [calls]
        return await self.run(env, model, settings, calls)

    def member(self, env, name, model, settings, protocol="", keep=None) -> Member:
        return Member(env, name, model, settings, protocol, keep, pool=self._pool)


# ---------------------------------------------------------------------- single agent
class ReAct(Design):
    async def run(self, env, model, settings, calls):
        m = self.member(env, next(iter(env.public()["agents"])), model, settings,
                   "Think step by step about what to do next, then act with one tool call at a time.")
        per = -(-calls // self.rounds)
        msg = "Begin."
        for _ in range(self.rounds):
            if m.finished():
                break
            await m.turn(msg, per)
            msg = "Continue: there is work left."
        return [m.report()]


class Reflexion(Design):
    memory_path = ""  # a JSON file: reflections carried from episode to episode (set before running)

    async def run(self, env, model, settings, calls):
        name = next(iter(env.public()["agents"]))
        memory = _load(self.memory_path)
        m = self.member(env, name, model, settings,
                   "Think step by step, then act with one tool call at a time. After a failure you will be asked "
                   "to reflect; your reflections are kept and shown to you before you continue.")
        per = -(-calls // self.rounds)
        seen_fail = 0
        for r in range(self.rounds):
            if m.finished():
                break
            notes = ("Reflections from earlier attempts:\n- " + "\n- ".join(memory[-8:])) if memory else ""
            await m.turn((notes + "\n\n" if notes else "") + ("Begin." if r == 0 else "Continue."), per)
            fails = sum(1 for e in env.events() if e.get("kind") == "op" and e.get("agent") == name
                        and e.get("op") == "submit" and not e["obs"].get("ok"))
            if fails > seen_fail:  # a failed submission since the last reflection: reflect
                seen_fail = fails
                text = await m.say("A submission was rejected. In two or three sentences, say what went wrong and "
                                   "what you will do differently. Do not call tools.")
                if text:
                    memory.append(text.strip()[:600])
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


# ---------------------------------------------------------------------- teams
class Independent(Design):
    async def run(self, env, model, settings, calls):
        ms = [self.member(env, a, model, settings, "You work alone; nobody else's results reach you.")
              for a in env.public()["agents"]]
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
        boss = self.member(env, o, model, settings, ORCH)
        workers = [self.member(env, a, model, settings, WORK.format(o=o, peers=peers), keep=lambda op: op != "submit")
                   for a in names[1:]]
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


DEBATE = ("You are one of several peers working the same problem; there is no leader. Work on the tasks with "
          "your tools. At the end of every round you will be asked to publish your current results on the "
          "board; at the start of the next you read the others' posts, critique them, and update your own "
          "answers. Submit a task when you are confident and, where the others have results, when they agree.")


class Decentralized(Design):
    async def run(self, env, model, settings, calls):
        ms = [self.member(env, a, model, settings, DEBATE) for a in env.public()["agents"]]
        per = max(1, -(-calls // (len(ms) * self.rounds)) - 1)
        for r in range(self.rounds):
            if _all_over(ms):
                break
            await _together(ms, "Begin." if r == 0 else "Read the board: the others' results from the last "
                            "round. Critique them, update yours, and continue.", per)
            await _together(ms, "End of round: post your current results and answers on the board "
                            f"(tag round{r + 1}).", 1)
        return [m.report() for m in ms]


BOARD = ("Everything you share goes on the shared board (post, and board to read); there are no direct "
         "messages. A control unit reads the board each round and decides who acts next. When you are called, "
         "read the board first, contribute what you can with your tools, and post what you found. Anyone may "
         "submit a task whose result the board makes clear.")


class Blackboard(Design):
    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        ms = {a: self.member(env, a, model, settings, BOARD, keep=lambda op: op not in ("send", "inbox"))
              for a in names}
        control = ms[names[0]]
        per = -(-calls // (len(names) * self.rounds))
        for r in range(self.rounds):
            if _all_over(ms.values()):
                break
            posts = env.step(names[0], "board", {}).get("posts", []) if r else []
            roles = env.public()["agents"]
            pick = await control.say(
                "You are the control unit. The board:\n" + json.dumps(posts[-20:])[:4000] +
                f"\nAgents and roles: {json.dumps(roles)}.\nWhich agents should act next? Answer with their names "
                "only, separated by spaces.")
            chosen = [a for a in names if a in pick.split() or a in pick] or names
            await _together([ms[a] for a in chosen], "You were chosen to act: read the board and contribute.",
                            per * len(names) // len(chosen))
        return [m.report() for m in ms.values()]


class MixtureOfAgents(Design):
    async def run(self, env, model, settings, calls):
        names = list(env.public()["agents"])
        ms = [self.member(env, a, model, settings,
                     "You are a proposer in a layered team. In each layer you work on the tasks and write your "
                     "results to the shared store under the key you are given; from the second layer on you "
                     "first read the previous layer's results (keys) and improve on them.") for a in names]
        agg = ms[0]
        per = -(-calls // (len(names) * (self.rounds + 1)))
        for layer in range(self.rounds):
            if _all_over(ms):
                break
            prev = f"Read the previous layer's results: keys moa/layer{layer}/<agent>. " if layer else ""
            await _together(ms, lambda m: f"Layer {layer + 1}. {prev}Work on the tasks, then put your results "
                            f"under key moa/layer{layer + 1}/{m.name}.", per)
        await agg.turn(f"You are the aggregator. Read every moa/layer{self.rounds}/<agent> result, synthesise the "
                       "best answer for each task, and submit them.", per * len(names))
        return [m.report() for m in ms]


class MetaGPT(Design):
    async def run(self, env, model, settings, calls):
        pub = env.public()
        names = list(pub["agents"])
        order = list(dict.fromkeys(pub["agents"].values()))  # the provider's roles, in its order: the SOP
        ms = {a: self.member(env, a, model, settings,
                        "Your team follows a standard operating procedure: roles act one after another, like an "
                        "assembly line. Publish your work as a structured document in the shared store under "
                        "sop/<your role>/<your name> (what you did, results, open questions for the next role), "
                        "and read only the documents of the roles before you.") for a in names}
        per = -(-calls // (len(names) * self.rounds))
        for r in range(self.rounds):
            for i, role in enumerate(order):
                group = [ms[a] for a in names if pub["agents"][a] == role]
                if _all_over(ms.values()):
                    break
                before = ", ".join(f"sop/{x}/" for x in order[:i]) or "none yet"
                await _together(group, f"Cycle {r + 1}, your step ({role}). Read the documents of earlier roles "
                                f"({before}), do your part, submit tasks you can finish, and publish your "
                                f"document.", per)
        return [m.report() for m in ms.values()]


DESIGNS: dict[str, Design] = {d.name: d for d in [
    ReAct("react", "Yao et al., ReAct: Synergizing Reasoning and Acting in Language Models, ICLR 2023", "solo"),
    Reflexion("reflexion", "Shinn et al., Reflexion: Language Agents with Verbal Reinforcement Learning, "
                           "NeurIPS 2023", "solo"),
    Independent("independent", "Kim et al., Towards a Science of Scaling Agent Systems, arXiv 2512.08296 "
                               "(2025): independent", "nonet"),
    Centralized("centralized", "Kim et al. 2025: centralized; Wu et al., AutoGen, arXiv 2308.08155 (2023)",
                "team"),
    Decentralized("decentralized", "Kim et al. 2025: decentralized; Du et al., Improving Factuality and "
                                   "Reasoning through Multiagent Debate, ICML 2024", "team"),
    Hybrid("hybrid", "Kim et al. 2025: hybrid", "team"),
    Blackboard("blackboard", "Han & Zhang, LLM Multi-Agent Systems Based on Blackboard Architecture, arXiv "
                             "2507.01701 (2025); Salemi et al., arXiv 2510.01285 (2025)", "team"),
    MixtureOfAgents("moa", "Wang et al., Mixture-of-Agents Enhances Large Language Model Capabilities, arXiv "
                           "2406.04692 (2024)", "team", rounds=3),
    MetaGPT("metagpt", "Hong et al., MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework, "
                       "ICLR 2024", "team", rounds=3),
]}
