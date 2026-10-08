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
from dataclasses import dataclass, field

from .knowledge import study_inputs
from .org import Dev, Org, OutOfBudget
from .world import P, Law, Project

_AFF = r"(-?\d+)\s*\*\s*x\s*(?:([+-])\s*(\d+))?"


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
        self.trace.append({"tool": tool, "args": args, "out": out[:1500], "t": time.monotonic()})
        return out + self.status()

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
        return self.log("run", {"function": function, "x": x}, f"{function}({x % P}) = {f.law(x % P)}")

    def study(self, function: str) -> str:
        f = self.u.functions.get(function)
        if f is None:
            return self.log("study", {"function": function}, f"No function {function!r}.")
        try:
            self.dev.spend("study", len(study_inputs()))
        except OutOfBudget:
            return self.log("study", {"function": function}, "Out of budget.")
        pts = ", ".join(f"{x} -> {f.law(x)}" for x in study_inputs())
        return self.log("study", {"function": function}, f"{function}: {pts}")

    def remember(self, function: str, law: str) -> str:
        if function not in self.u.functions:
            return self.log("remember", {"function": function, "law": law}, f"No function {function!r}.")
        parsed = parse_law(law)
        if parsed is None:
            return self.log("remember", {"function": function, "law": law},
                            "Could not read that law. Use 'a*x + b' or 'a2*x + b2 if x % m == 0 else a*x + b'.")
        gone = self.dev.notebook.put(function, parsed)
        return self.log("remember", {"function": function, "law": law},
                        f"Noted {function}: {parsed.describe()}." + (f" Forgot: {', '.join(gone)}." if gone else ""))

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
        return self.log("compute", {"program": program, "x": x}, f"{' -> '.join(program)} on {x}: {v}")

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
        if not self.u.type_checks(prog, p.in_type, p.out_type):
            return self.log("submit", {"program": program}, "Rejected: the program does not type-check.")
        if self.u.table(prog) != self.u.table(p.target):
            bad = next(x for x, y in p.examples if self.u.run(prog, x) != y) if any(
                self.u.run(prog, x) != y for x, y in p.examples) else None
            return self.log("submit", {"program": program},
                            "Rejected: " + (f"wrong on example {bad}." if bad is not None else "fails hidden tests."))
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
        """Write a law into your notebook: 'a*x + b' or 'a2*x + b2 if x % m == 0 else a*x + b'. Free."""
        return session.remember(function, law)

    @function_tool
    def notebook() -> str:
        """Your laws, and the laws teammates explained for the current project. Free."""
        return session.notebook()

    @function_tool
    def compute(program: list[str], x: int) -> str:
        """Run a program (list of function names, in order) on x using only laws you know. Free."""
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


async def run_dev(session: Session, model, settings, max_turns: int = 200) -> dict:
    from agents import Agent, MaxTurnsExceeded, RunConfig, Runner, ToolsToFinalOutputResult

    def stop(ctx, results):
        if not session.queue or session.dev.budget <= 0:
            return ToolsToFinalOutputResult(is_final_output=True, final_output="DONE")
        return ToolsToFinalOutputResult(is_final_output=False)

    agent = Agent(name=session.dev.name, instructions=instructions(session), tools=_tools(session), model=model,
                  model_settings=settings, tool_use_behavior=stop, reset_tool_choice=False)
    status, usage, nudges = "finished", [0, 0], 0
    run_input, turns_left = "Begin." + session.status(), max_turns
    fields = getattr(RunConfig, "__dataclass_fields__", {})
    rc = RunConfig(**{k: v for k, v in {"tracing_disabled": True,
                                        "tool_not_found_behavior": "return_error_to_model"}.items() if k in fields})
    while True:
        res = None
        try:
            res = await Runner.run(agent, run_input, max_turns=turns_left, run_config=rc)
            u = res.context_wrapper.usage
            usage[0] += u.input_tokens
            usage[1] += u.output_tokens
        except MaxTurnsExceeded:
            status = "max_turns"
        except Exception as e:  # a broken run must not end the sprint for everyone
            status = f"error: {type(e).__name__}: {e}"[:300]
        if res is None or not session.queue or session.dev.budget <= 0 or nudges >= 3:
            break
        # the model stopped talking with work left: nudge it to keep going
        nudges += 1
        turns_left = max(1, turns_left - len([i for i in res.new_items if i.type == "tool_call_item"]) - 1)
        run_input = res.to_input_list() + [{"role": "user", "content": "Projects are left and you have budget. "
                                            "Keep going: call a tool." + session.status()}]
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
