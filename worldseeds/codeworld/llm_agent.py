"""LLM developers in CodeWorld (OpenAI Agents SDK, any OpenAI-compatible server).

Each developer works through its share of a sprint's projects with these tools:

    signatures(module)          public signatures (all modules if empty)                       free
    run(function, x)            run one function on one input                                  1 action
    study(function)             run it on the design inputs 0..7 (shows every edge case)       8 actions
    remember(function, law)     write a law into your notebook (at most `capacity` laws;       free
                                the least recently used is forgotten). Law format:
                                "a*x + b" or "a2*x + b2 if x % m == 0 else a*x + b"  (mod 101)
    notebook()                  your laws, and what teammates explained for this project      free
    compute(program, x)         run a program on x using only laws you know                    free
    ask(teammate, function)     a teammate explains a law from their notebook                  1 + 1 action
    who_knows(function)         who has this law in their notebook (organisation "directory")  free
    submit(program)             submit a program for the current project                       1 action

Teammates answer from their notebooks automatically (no extra model call): a question costs both an
action. Laws written with ``remember`` are scored against the truth (right / wrong), like everything else.
"""

from __future__ import annotations

import asyncio
import re
import time
import traceback
from dataclasses import dataclass, field

from .knowledge import study_inputs
from .org import Dev, Org, OutOfBudget
from .world import P, Law, Project

_AFF = r"(-?\d+)\s*\*\s*x\s*(?:([+-])\s*(\d+))?"
LAW_HELP = ("Use concrete integer coefficients, not the letters a or b. Examples of syntax only: "
            "'3*x + 5' or '7*x + 1 if x % 3 == 0 else 2*x + 9'. "
            "All outputs are modulo 101; infer the numbers from your observed samples. "
            "Do not copy these example numbers as a machine's law.")


def parse_law(text: str) -> Law | None:
    """'a*x + b' or 'a2*x + b2 if x % m == 0 else a*x + b' (also 'x' for 1*x; a missing b is 0)."""
    t = (text or "").strip().lower().replace("(mod 101)", "").replace("mod 101", "").strip()
    t = re.sub(r"(\d)\s*x", r"\1*x", t)
    t = re.sub(r"(?<![\d*])x", "1*x", t)

    def aff(a, sign, b):
        return int(a) % P, (-int(b or 0) if sign == "-" else int(b or 0)) % P

    br = re.fullmatch(_AFF + r"\s+if\s+1\*x\s*%\s*(\d+)\s*==\s*0\s+else\s+" + _AFF, t)
    if br:
        g = br.groups()
        (a2, b2), (a, b) = aff(*g[0:3]), aff(*g[4:7])
        return Law("branch", a, b, int(g[3]), a2, b2) if int(g[3]) > 1 else None
    m = re.fullmatch(_AFF, t)
    return Law("affine", *aff(*m.groups())) if m else None


INSTRUCTIONS = """You are {name}, a developer in a software ecosystem of {n_modules} modules ({n_functions} functions).
Every function maps an input type to an output type (its signature is public) and computes on integers mod 101,
but what it does is hidden: either a*x + b, or a different a2*x + b2 on an edge case (x a multiple of 2, 3 or 5).
Your job: build the programs (chains of functions) that projects ask for. A project gives an input type, an output
type and examples; many chains type-check, only one fits the examples. Find it and submit it.

You have {budget} actions this sprint. Running a function costs 1, studying one (inputs 0..7) costs 8, submitting
costs 1. Knowing laws makes building cheap: compute(program, x) is free with laws you know. Your notebook holds at
most {capacity} laws; when it is full the least recently used law is forgotten. Write laws with
remember(function, law) in the form "a*x + b" or "a2*x + b2 if x % m == 0 else a*x + b".
Replace a, b, a2, b2 and m with actual integers inferred from observations. For example, the syntax is
"3*x + 5", not the literal string "a*x + b". Arithmetic wraps modulo 101. After studying a function,
infer and remember its rule before studying another; avoid repeating a study with identical inputs.
If study is too expensive, run(function, x) costs only 1 action. Use known rules to compute candidate
chains against the project's examples and submit a matching chain. Signatures are already listed below.
run/study are real observations; compute only predicts from your notebook and may be wrong.
Never infer a machine's rule from the output you WANT an order to have. Fit observed input/output
pairs instead. If a submission disagrees with compute, re-test your notebook assumptions, not the
same submission. Tool calls handle any required walking automatically; no separate walk tool is needed.
{team}
FUNCTIONS (module: function: input type -> output type):
{signatures}

Projects come one after another; after a correct submit the next one appears. Work efficiently and keep going until
your projects are done or your budget is spent. Call one tool at a time."""

TEAM = {
    "solo": "You work alone.",
    "owners": "Your teammates: {mates}. Every module has an owner ({owners}). You own {mine}: keep their laws in "
              "your notebook, teammates will ask you. Ask the owner of a module about its functions with "
              "ask(teammate, function) (1 action for you, 1 for them) instead of studying them yourself.",
    "directory": "Your teammates: {mates}. who_knows(function) tells you who has a law in their notebook; ask them "
                 "with ask(teammate, function) (1 action for you, 1 for them). Module owners: {owners}; you own {mine}.",
    "random": "Your teammates: {mates}. You do not know who knows what; you may ask(teammate, function) (1 action "
              "for you, 1 for them), they answer only if the law is in their notebook.",
}


@dataclass
class Session:
    """One developer's sprint: its projects, working memory, and tool implementations."""
    org: Org
    dev: Dev
    queue: list[Project]
    done: int = 0
    submits: int = 0
    trace: list = field(default_factory=list)
    explained: dict = field(default_factory=dict)  # this project's working memory: laws teammates explained
    blocked_budget: int = 0
    repeated_failure: int = 0
    _last_failure: object = None
    model_requests: int = 0
    observations: dict = field(default_factory=dict)  # this sprint's actual machine samples, not task targets
    failed_programs: dict = field(default_factory=dict)  # persists across intervening free computations

    @property
    def u(self):
        return self.org.u

    @property
    def project(self) -> Project | None:
        return self.queue[0] if self.queue else None

    def status(self) -> str:
        p = self.project
        return (f"\n[{self.dev.name}: {self.dev.budget} actions left | notebook {len(self.dev.notebook)}/"
                f"{self.dev.notebook.capacity or 'unlimited'} | done {self.done} | "
                + (p.text() if p else "no projects left") + "]")

    def log(self, tool, args, out) -> str:
        import json
        budget_error = out.startswith("Out of budget")
        self.blocked_budget = self.blocked_budget + 1 if budget_error else 0
        failure = budget_error or out.startswith(("Could not read", "Rejected:", "No function"))
        key = (tool, json.dumps(args, sort_keys=True)) if failure else None
        self.repeated_failure = self.repeated_failure + 1 if key and key == self._last_failure else int(failure)
        self._last_failure = key
        if budget_error:
            out += (f" This operation cannot be afforded with {self.dev.budget} actions left. "
                    "Do not repeat it. Use a cheaper action (run costs 1), compute with known rules, "
                    "submit if possible, or buy overtime if available. Two consecutive unaffordable "
                    "calls end this player's run.")
        returned = out + self.status()
        entry = {"tool": tool, "args": args, "out": out, "returned": returned, "t": time.monotonic(),
                 "time": time.time(), "budget_after": self.dev.budget, "location": self.dev.loc,
                 "project": self.project.id if self.project else None}
        self.trace.append(entry)
        from ..recording import ACTIVE_RECORDING
        active = ACTIVE_RECORDING.get()
        if active:
            active[0].write("tool_result", active[1], **entry)
        return returned

    def stop_reason(self, more) -> str | None:
        if not more():
            return "completed"
        if self.dev.budget <= 0:
            return "out_of_budget"
        if self.blocked_budget >= 2:
            return "blocked_budget"
        if self.repeated_failure >= 3:
            return "repeated_tool_failure"
        if any(count >= 3 for count in self.failed_programs.values()):
            return "repeated_submission_failure"
        return None

    def observation_conflict(self, function, law):
        for x, observed in self.observations.get(function, {}).items():
            predicted = law(x)
            if predicted != observed:
                return (f"Rejected: your rule predicts {predicted} for input {x}, but you observed "
                        f"{observed} from {function}. No note was saved. "
                        "Fit the observed values, not the order's desired output. "
                        "Use run/study for additional real samples if needed.")
        return None

    def _law(self, fn: str) -> Law | None:
        return self.dev.notebook.get(fn) or self.explained.get(fn)

    # ------------------------------------------------------------ tools
    def signatures(self, module: str = "") -> str:
        mods = [module] if module in self.u.modules else None
        return self.log("signatures", {"module": module}, self.u.signatures_text(mods))

    def run(self, function: str, x: int) -> str:
        f = self.u.functions.get(function)
        if f is None:
            return self.log("run", {"function": function, "x": x}, f"No function {function!r}.")
        try:
            self.dev.spend("study")
        except OutOfBudget:
            return self.log("run", {"function": function, "x": x}, "Out of budget.")
        observed = f.law(x % P)
        self.observations.setdefault(function, {})[x % P] = observed
        return self.log("run", {"function": function, "x": x},
                        f"{function}({x % P}) = {observed}. Real machine observation, not a notebook prediction.")

    def study(self, function: str) -> str:
        f = self.u.functions.get(function)
        if f is None:
            return self.log("study", {"function": function}, f"No function {function!r}.")
        try:
            self.dev.spend("study", len(study_inputs()))
        except OutOfBudget:
            return self.log("study", {"function": function}, "Out of budget.")
        samples = {x: f.law(x) for x in study_inputs()}
        self.observations.setdefault(function, {}).update(samples)
        pts = ", ".join(f"{x} -> {y}" for x, y in samples.items())
        return self.log("study", {"function": function},
                        f"{function}: {pts}. These are real observations. Infer numeric coefficients and remember them.")

    def remember(self, function: str, law: str) -> str:
        if function not in self.u.functions:
            return self.log("remember", {"function": function, "law": law}, f"No function {function!r}.")
        parsed = parse_law(law)
        if parsed is None:
            return self.log("remember", {"function": function, "law": law},
                            "Could not read that law. " + LAW_HELP)
        conflict = self.observation_conflict(function, parsed)
        if conflict:
            return self.log("remember", {"function": function, "law": law}, conflict)
        gone = self.dev.notebook.put(function, parsed)
        n = len(self.observations.get(function, {}))
        return self.log("remember", {"function": function, "law": law},
                        f"Noted {function}: {parsed.describe()}. Checked against {n} observed samples; "
                        "this is a hypothesis, not a guarantee on untested inputs."
                        + (f" Forgot: {', '.join(gone)}." if gone else ""))

    def notebook(self) -> str:
        lines = [f"{n}: {law.describe()}" for n, law in self.dev.notebook.laws.items()]
        lines += [f"{n}: {law.describe()} (explained by a teammate, this project only)" for n, law in self.explained.items()]
        return self.log("notebook", {}, "\n".join(lines) or "(empty)")

    def compute(self, program: list[str], x: int) -> str:
        v = x % P
        for fn in program:
            law = self._law(fn)
            if law is None:
                return self.log("compute", {"program": program, "x": x}, f"You do not know the law of {fn}.")
            v = law(v)
        return self.log("compute", {"program": program, "x": x},
                        f"{' -> '.join(program)} on {x}: {v}. Notebook prediction only; no machine was run. "
                        "A matching prediction does not prove the chain works; wrong notes give wrong predictions.")

    def ask(self, teammate: str, function: str) -> str:
        mate = next((d for d in self.org.devs if d.name == teammate and d is not self.dev), None)
        args = {"teammate": teammate, "function": function}
        if mate is None or self.org.mode in ("solo", "independent", "pooled"):
            return self.log("ask", args, "Nobody to ask by that name.")
        try:
            self.dev.spend("ask")
        except OutOfBudget:
            return self.log("ask", args, "Out of budget.")
        law = mate.notebook.get(function)
        if law is None or mate.budget < 1:
            return self.log("ask", args, f"{teammate} does not know {function}.")
        mate.spend("answer")
        self.explained[function] = law
        return self.log("ask", args, f"{teammate}: {function} is {law.describe()}.")

    def who_knows(self, function: str) -> str:
        if self.org.mode != "directory":
            return self.log("who_knows", {"function": function}, "There is no directory in this team.")
        names = [d.name for d in self.org.devs if function in d.notebook and d is not self.dev]
        return self.log("who_knows", {"function": function}, ", ".join(names) or "nobody")

    def submit(self, program: list[str]) -> str:
        p = self.project
        if p is None:
            return self.log("submit", {"program": program}, "No project left.")
        try:
            self.dev.spend("submit")
        except OutOfBudget:
            return self.log("submit", {"program": program}, "Out of budget.")
        self.submits += 1
        prog = tuple(program)
        def reject(message):
            key = (p.id, prog)
            self.failed_programs[key] = self.failed_programs.get(key, 0) + 1
            return self.log("submit", {"program": program}, "Rejected: " + message +
                            " This tests the real machines, not your notes. Do not resubmit the same chain "
                            "without changing it. Three rejections of one chain end your run even if "
                            "you call compute between submissions.")
        if not self.u.type_checks(prog, p.in_type, p.out_type):
            return reject("the program does not type-check.")
        if self.u.table(prog) != self.u.table(p.target):
            bad = next(x for x, y in p.examples if self.u.run(prog, x) != y) if any(
                self.u.run(prog, x) != y for x, y in p.examples) else None
            if bad is not None:
                desired = dict(p.examples)[bad]
                actual = self.u.run(prog, bad)
                return reject(f"wrong on example {bad}: actual machine output {actual}; required output {desired}.")
            return reject("fails hidden tests; your hypotheses may fail on inputs not covered by the examples.")
        self.done += 1
        self.queue.pop(0)
        self.explained = {}
        return self.log("submit", {"program": program}, "Accepted!")


def _tools(session: Session):
    from agents import function_tool

    @function_tool
    def signatures(module: str = "") -> str:
        """Public signatures of a module's functions (all modules if module is empty). Free."""
        return session.signatures(module)

    @function_tool
    def run(function: str, x: int) -> str:
        """Run one function on one input. 1 action."""
        return session.run(function, x)

    @function_tool
    def study(function: str) -> str:
        """Run a function on the inputs 0..7 (covers every edge case). 8 actions."""
        return session.study(function)

    @function_tool
    def remember(function: str, law: str) -> str:
        """Write a rule with numeric coefficients, e.g. '3*x + 5'; never literal a or b. Modulo 101. Free."""
        return session.remember(function, law)

    @function_tool
    def notebook() -> str:
        """Your laws, and the laws teammates explained for the current project. Free."""
        return session.notebook()

    @function_tool
    def compute(program: list[str], x: int) -> str:
        """Predict using notebook hypotheses only; does not execute real machines. Wrong notes give wrong predictions. Free."""
        return session.compute(program, x)

    @function_tool
    def ask(teammate: str, function: str) -> str:
        """Ask a teammate to explain a function's law from their notebook. 1 action for you, 1 for them."""
        return session.ask(teammate, function)

    @function_tool
    def who_knows(function: str) -> str:
        """Who has this function's law in their notebook (directory teams only). Free."""
        return session.who_knows(function)

    @function_tool
    def submit(program: list[str]) -> str:
        """Submit a program (list of function names, in order) for the current project. 1 action."""
        return session.submit(program)

    tools = [signatures, run, study, remember, notebook, compute, submit]
    if session.org.mode in ("owners", "directory", "random"):
        tools.append(ask)
    if session.org.mode == "directory":
        tools.append(who_knows)
    return tools


def instructions(session: Session) -> str:
    org, dev = session.org, session.dev
    mates = ", ".join(d.name for d in org.devs if d is not dev)
    owners = "; ".join(f"{m}: {d.name}" for m, d in org.owner.items())
    team = TEAM.get(org.mode, TEAM["solo"]).format(mates=mates, owners=owners, mine=", ".join(sorted(dev.owns)))
    return INSTRUCTIONS.format(name=dev.name, n_modules=len(org.u.modules), n_functions=org.u.n_functions,
                               budget=dev.budget, capacity=dev.notebook.capacity or "unlimited", team=team,
                               signatures=org.u.signatures_text())


async def run_dev(session: Session, model, settings, max_turns: int = 200, tools=None, text=None, more=None) -> dict:
    """Run one developer's sprint. ``tools`` / ``text`` replace the default tools and instructions; ``more()``
    says whether there is work left (default: projects in the queue)."""
    from agents import Agent, MaxTurnsExceeded, RunConfig, RunHooks, Runner, ToolsToFinalOutputResult
    from ..recording import ACTIVE_RECORDING

    more = more or (lambda: bool(session.queue))

    def stop(ctx, results):
        reason = session.stop_reason(more)
        if reason:
            return ToolsToFinalOutputResult(is_final_output=True, final_output=reason)
        return ToolsToFinalOutputResult(is_final_output=False)

    active = ACTIVE_RECORDING.get()
    if active:
        token = ACTIVE_RECORDING.set((active[0], {**active[1], "dev": session.dev.name}))
    else:
        token = None

    def event(kind, **data):
        a = ACTIVE_RECORDING.get()
        if a:
            a[0].write(kind, a[1], **data)

    class RecordingHooks(RunHooks):
        async def on_llm_start(self, context, agent, system_prompt, input_items):
            session.model_requests += 1
            event("llm_start", turn=session.model_requests, system_prompt=system_prompt,
                  input_items=input_items, settings=settings)

        async def on_llm_end(self, context, agent, response):
            # Count each response immediately, even if a later turn fails or hits the limit.
            usage[0] += response.usage.input_tokens
            usage[1] += response.usage.output_tokens
            event("llm_end", turn=session.model_requests, response=response)

    agent = Agent(name=session.dev.name, instructions=text or instructions(session),
                  tools=tools if tools is not None else _tools(session), model=model,
                  model_settings=settings, tool_use_behavior=stop, reset_tool_choice=False)
    status, usage, nudges = "finished", [0, 0], 0
    run_input, turns_left = "Begin." + session.status(), max_turns
    event("agent_start", instructions=agent.instructions, input=run_input, budget=session.dev.budget,
          max_turns=max_turns, tools=[{"name": t.name, "description": t.description,
                                    "schema": t.params_json_schema} for t in agent.tools])
    fields = getattr(RunConfig, "__dataclass_fields__", {})
    rc = RunConfig(**{k: v for k, v in {"tracing_disabled": True,
                                        "tool_not_found_behavior": "return_error_to_model"}.items() if k in fields})
    while True:
        res = None
        reason = session.stop_reason(more)
        if reason:
            status = reason
            break
        try:
            res = await Runner.run(agent, run_input, max_turns=turns_left, run_config=rc, hooks=RecordingHooks())
        except MaxTurnsExceeded:
            status = "max_turns"
            event("agent_limit", status=status)
        except Exception as e:  # a broken run must not end the sprint for everyone
            status = f"error: {type(e).__name__}: {e}"[:300]
            event("agent_error", error_type=type(e).__name__, message=str(e), traceback=traceback.format_exc())
        reason = session.stop_reason(more)
        if reason and not status.startswith("error:"):
            status = reason
        if res is None or reason or nudges >= 3:
            if res is not None and not reason:
                status = "stopped_with_work_left"
            break
        # the model stopped talking with work left: nudge it to keep going
        nudges += 1
        turns_left = max_turns - session.model_requests
        if turns_left <= 0:
            status = "max_turns"
            break
        run_input = res.to_input_list() + [{"role": "user", "content": "Work is left and you have budget. "
                                            "Keep going: call a tool." + session.status()}]
    bound = ACTIVE_RECORDING.get()
    if bound:
        raw_usage = bound[0].http_usage.get(bound[0].usage_key(bound[1]))
        if raw_usage is not None:
            usage = list(raw_usage)
    event("agent_end", status=status, done=session.done, remaining_orders=len(session.queue),
          budget=session.dev.budget, model_requests=session.model_requests,
          input_tokens=usage[0], output_tokens=usage[1])
    if token is not None:
        ACTIVE_RECORDING.reset(token)
    return {"dev": session.dev.name, "done": session.done, "status": status, "nudges": nudges,
            "input_tokens": usage[0],
            "output_tokens": usage[1], "trace": session.trace}


async def llm_sprint(org: Org, projects: list[Project], budget: int, model, settings, max_turns: int = 200) -> dict:
    """One sprint with LLM developers working at the same time; returns the org's metrics plus LLM stats."""
    for d in org.devs:
        d.budget = budget
        for k in d.spent:
            d.spent[k] = 0
    sessions = [Session(org, d, projects[i::len(org.devs)]) for i, d in enumerate(org.devs)]
    outs = await asyncio.gather(*[run_dev(s, model, settings, max_turns) for s in sessions])
    m = org.metrics([{"done": True}] * sum(s.done for s in sessions) +
                    [{"done": False}] * sum(len(s.queue) for s in sessions))
    m.update(input_tokens=sum(o["input_tokens"] for o in outs), output_tokens=sum(o["output_tokens"] for o in outs),
             statuses=[o["status"] for o in outs], submits=sum(s.submits for s in sessions))
    return {"metrics": m, "traces": [{"dev": o["dev"], "trace": o["trace"]} for o in outs]}
