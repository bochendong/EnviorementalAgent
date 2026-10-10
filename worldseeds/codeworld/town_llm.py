"""LLM apprentices in the town: the developer tools of llm_agent.py plus the town's money, goals and buildings.

On top of signatures / run / study / remember / notebook / compute / ask / submit (orders), an apprentice has

    town()                          purse, reputation, treasury, prices, this sprint's news, where you are      free
    goals()                         the town's grand goals: open parts, bounties, tries left                     free
    deliver_goal(part, program, batch)  deliver a goal part (batch: the raw good's grade, for the prize)        1 action
    set_price(coins)                what you charge for explaining a machine (0..PRICE_CAP)                      free
    pay(to, amount, note)           give coins to a teammate or to "treasury" (e.g. for the clock tower)         free
    buy_overtime(actions)           more actions this sprint, at the town's price (capped)                       coins
    hand_over(teammate, coins)      give your current order to a teammate and pay them for it                    free
    letter(teammate, function)      ask by letter: no walk, the answer takes a while (post office)               1 + wait
    post(text)                      pin a note on the notice board (anyone can, true or not)                     1 action
    board()                         read the notice board (and, with a roster, who knows what)                   walk + 1
    library_read(function)          read a rule written down at the library (if any; it may be wrong)            walk + 1
    library_write(function, law)    write a rule down at the library (for everyone; and the encyclopedia)        walk + 1

Walking: studying a machine means going to its workshop, asking someone means going to them (the town's
walking costs). Rules against gaming the town, all enforced by the engine and logged as ``exploits``:
money is only made by customers (transfers move it), a goal part takes at most GOAL_TRIES deliveries and a
wrong one costs a fine and reputation, reputation for an explanation counts once per asker, machine and
sprint and only if the rule was right, prices are capped, and personal scores (coins + 5 x reputation) are
scaled by how the town's goals went (0.5 .. 1).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .goals import check
from .llm_agent import LAW_HELP, Session, parse_law, run_dev
from .org import Org, OutOfBudget
from .world import Project

PRICE_CAP = 10
GOAL_TRIES = 3
FINE = 5

INSTRUCTIONS = """You are {nick} ({name}), an apprentice in SeedVille, a town of {n_workshops} workshops ({n_machines} machines)
on several maps (town, farm, beach, mountain). Every machine turns one good into another (its recipe is public) and
changes the good's grade, a number 0..100, by a hidden rule: either a*x + b, or a different a2*x + b2 when x is a
multiple of 2, 3 or 5 (mod 101). Orders and goals ask for chains of machines; many chains fit the goods, the grades
tell which one is meant.

TIME: {budget} actions this sprint. Running a machine on one grade costs 1, studying it (grades 0..7) costs 8, and
walking costs actions too (to a workshop to use its machines, to a person to ask them). Your notebook holds at most
{capacity} rules (write them with remember(machine, rule) as "a*x + b" or "a2*x + b2 if x % m == 0 else a*x + b";
the least recently used is forgotten). compute(program, x) is free with rules you know.
Write actual integer coefficients: "3*x + 5" is an example of syntax, whereas literal "a*x + b" is invalid.
Infer the numbers from the observed grades, remembering that arithmetic wraps modulo 101. After studying
a machine, infer and remember its rule; do not repeatedly request the same samples. If you cannot afford
study (8 actions plus walking), use run for a single grade (1 plus walking). Use compute to check a chain
against the current order's examples, then submit it. The complete machine list is already shown below.
run/study return actual machine outputs; compute only predicts using your notebook. A desired order
output is not an observation. Never write a rule to force a desired answer against observed samples.
If submission fails, inspect actual vs required output and test your rules before choosing another chain.
Walking to machines or teammates is automatic inside the tool call. There is no separate walk tool.
{team}
MONEY: you have {coins} coins. Customers pay for orders: half to who delivers, a royalty to the masters of the
machines used, the rest is tax for the treasury ({treasury} coins). The treasury pays a bounty of {bounty} coins for each
goal part. Explaining a machine can be paid for (set_price); you can give coins (pay), buy overtime, or hand an order
over to someone for a fee.

GOALS (see goals()): {goals}. Deliver a goal part with deliver_goal; each part allows {tries} tries, a wrong delivery
costs {fine} coins and 2 reputation.

YOUR SCORE: coins + 5 x reputation (reputation: goal parts done, correct explanations, rules written at the library),
multiplied by how the town's goals went (from 0.5 if all fail to 1 if all succeed). Others have the same score.

MACHINES (workshop.machine: input good -> output good):
{signatures}

Call one tool at a time. Your orders come one after another; goal parts are open to everyone (first to deliver
wins the bounty). Keep working until your time is spent."""

TEAM = {
    "solo": "You work alone.",
    "owners": "Others: {mates}. Each workshop has a master ({owners}); you are the master of {mine}: keep their rules, "
              "others will ask you. Ask the master of a workshop about its machines with ask(person, machine).",
    "directory": "Others: {mates}. board() lists who knows which rule; ask them with ask(person, machine). Masters: "
                 "{owners}; you are the master of {mine}.",
    "random": "Others: {mates}. You do not know who knows what; ask(person, machine) works only if they know it.",
}


@dataclass
class TownSession(Session):
    """One apprentice's sprint in the town (orders in ``queue``; goals and money shared through ``org``)."""
    started: set = field(default_factory=set)

    # ------------------------------------------------------------ helpers
    def log(self, tool, args, out):
        # Include every actual tool call in the browser replay, even unsuccessful ones.
        self.org._project = self.project.id if self.project else ""
        self.org._ev("tool", self.dev, tool=tool, args=args, out=out)
        return super().log(tool, args, out)

    def status(self) -> str:
        p = self.project
        e = self.org.econ
        money = f" | {self.dev.coins} coins, rep {self.dev.rep}" if e else ""
        return (f"\n[{self.dev.name}: {self.dev.budget} actions left{money} | notebook {len(self.dev.notebook)}/"
                f"{self.dev.notebook.capacity or 'unlimited'} | orders done {self.done} | "
                + (p.text().replace("Project", "Order").replace("program", "chain of machines")
                   .replace("functions", "machines") if p else "no orders left") + "]")

    def _begin(self):
        p = self.project
        if p is not None and p.id not in self.started:
            self.started.add(p.id)
            self.org._project = p.id
            self.org._ev("start", self.dev, text=p.text())

    def _exploit(self, what: str):
        self.org.stats["exploits"] = self.org.stats.get("exploits", 0) + 1
        self.org._ev("exploit", self.dev, what=what)

    def _walk(self, place) -> str | None:
        self.org._project = self.project.id if self.project else ""
        try:
            self.org._go(self.dev, place)
        except OutOfBudget:
            return "Out of budget (walking)."
        return None

    def _mate(self, name: str):
        return next((d for d in self.org.devs if d.name == name and d is not self.dev), None)

    # ------------------------------------------------------------ the developer tools, in the town
    def run(self, function: str, x: int) -> str:
        f = self.u.functions.get(function)
        if f is not None:
            if function in self.u.broken:
                return self.log("run", {"function": function, "x": x}, f"{function} is out of order.")
            err = self._walk(f.module)
            if err:
                return self.log("run", {"function": function, "x": x}, err)
        return super().run(function, x)

    def study(self, function: str) -> str:
        f = self.u.functions.get(function)
        if f is not None:
            if function in self.u.broken:
                self.org._ev("broken_found", self.dev, fn=function)
                return self.log("study", {"function": function}, f"{function} is out of order this sprint.")
            err = self._walk(f.module)
            if err:
                return self.log("study", {"function": function}, err)
        return super().study(function)

    def remember(self, function: str, law: str) -> str:
        before = set(self.dev.notebook.laws)
        out = super().remember(function, law)
        parsed = parse_law(law)
        if out.startswith("Noted ") and parsed is not None and function in self.u.functions:
            self.org._ev("learn", self.dev, fn=function, law=parsed.describe(),
                         forgot=sorted(before - set(self.dev.notebook.laws)),
                         correct=parsed.table == self.u.functions[function].law.table)
        return out

    def ask(self, teammate: str, function: str) -> str:
        return self._ask(teammate, function, letter=False)

    def letter(self, teammate: str, function: str) -> str:
        return self._ask(teammate, function, letter=True)

    def _ask(self, teammate: str, function: str, letter: bool) -> str:
        tool = "letter" if letter else "ask"
        args = {"teammate": teammate, "function": function}
        mate = self._mate(teammate)
        if mate is None or self.org.mode in ("solo", "independent", "pooled"):
            if teammate == self.dev.name:
                self._exploit("asked itself")
            return self.log(tool, args, "Nobody to ask by that name.")
        price = self.org.prices.get(mate.name, 0) if self.org.econ else 0
        if price > self.dev.coins:
            return self.log(tool, args, f"{teammate} charges {price} coins; you have {self.dev.coins}.")
        try:
            if letter:
                if not self.org.post:
                    return self.log(tool, args, "There is no post office in this town.")
                self.dev.spend("letter")
                self.dev.spend("wait", self.org.post_delay)
            else:
                err = self._walk(mate.loc)
                if err:
                    return self.log(tool, args, err)
                self.dev.spend("ask")
        except OutOfBudget:
            return self.log(tool, args, "Out of budget.")
        law = mate.notebook.get(function)
        if function in mate.broken:
            self.org._ev("ask", self.dev, to=mate.name, fn=function, answered=True, law="out of order", also=[])
            return self.log(tool, args, f"{teammate}: {function} is out of order.")
        if law is None or mate.budget < 1:
            self.org._ev("ask", self.dev, to=mate.name, fn=function, answered=False)
            return self.log(tool, args, f"{teammate} does not know {function}.")
        mate.spend("answer")
        self.explained[function] = law
        right = law.table == self.u.functions[function].law.table
        key = (self.dev.name, mate.name, function)
        if right and key not in self.org._answered:
            self.org._answered.add(key)
            mate.rep += 1
        self.org._ev("ask", self.dev, to=mate.name, fn=function, answered=True, law=law.describe(), also=[],
                     **({"by": "post", "delay": self.org.post_delay} if letter else {}))
        if price:
            self.org.pay(self.dev, mate, price, "answer")
        return self.log(tool, args, f"{teammate}: {function} is {law.describe()}." +
                        (f" (paid {price} coins)" if price else ""))

    def submit(self, program: list[str]) -> str:
        p = self.project
        if p is None:
            return self.log("submit", {"program": program}, "No order left.")
        down = [fn for fn in program if fn in self.u.broken]
        if down:
            return self.log("submit", {"program": program}, f"Cannot be made now: {', '.join(down)} out of order.")
        self.org._project = p.id
        before = self.done
        out = super().submit(program)
        ok = self.done > before
        self.org._ev("submit", self.dev, program=list(program), ok=ok, tried=self.submits)
        if ok:
            if self.org.econ:
                self.org._paid_order(self.dev, p, tuple(program))
            self._begin()
        return out

    # ------------------------------------------------------------ the town
    def town(self) -> str:
        o, d = self.org, self.dev
        lines = [f"You are at {d.loc or 'the plaza'}. Sprint {o.sprint_no}."]
        if o.econ:
            lines.append(f"Purse: {d.coins} coins, reputation {d.rep}. Treasury: {o.treasury} coins. "
                         f"Overtime: {o.econ.overtime_price} coins per action (at most {o.econ.overtime_cap} a sprint, "
                         f"{d._ot} bought). Prices for explanations: "
                         + ", ".join(f"{x.name} {o.prices.get(x.name, 0)}" for x in o.devs) + ".")
            lines.append("Scores now: " + ", ".join(f"{k} {v}" for k, v in o.scores().items()) +
                         f" (town factor {o.town_factor():.2f}).")
        news = [e for e in o.sprint_events if e["kind"] != "rumor"]
        if news:
            lines.append("News: " + "; ".join(_news(e) for e in news))
        if d.broken:
            lines.append("You know these are out of order: " + ", ".join(sorted(d.broken)))
        return self.log("town", {}, "\n".join(lines))

    def goals(self) -> str:
        o = self.org
        if not o.goals:
            return self.log("goals", {}, "The town has no grand goals.")
        lines = []
        for g in o.goals:
            state = (f"done in sprint {g.done_at}" if g.done_at else
                     "missed" if o.sprint_no > g.deadline else f"due by sprint {g.deadline}")
            lines.append(f"{g.title} ({g.kind}, {state}): {g.story}")
            if g.kind == "encyclopedia":
                lines.append(f"  {sum(p.get('done') is not None for p in g.parts)} of {len(g.parts)} machines written "
                             "down correctly at the library (library_write).")
                continue
            if g.kind == "fund":
                lines.append(f"  treasury {o.treasury} of {g.parts[0]['target']} coins (pay(\"treasury\", ...)).")
                continue
            for p in g.parts:
                left = GOAL_TRIES - p.get("tries", 0)
                if p.get("done") is not None:
                    lines.append(f"  {p['id']}: {p['text']} -- done by {p.get('by')}")
                else:
                    how = ("deliver_goal(part, program, batch): a chain from the raw good, and the batch grade"
                           if g.kind == "prize" else "deliver_goal(part, program)")
                    lines.append(f"  {p['id']}: {p['text']} -- open, {left} tries left, bounty "
                                 f"{o.econ.bounty if o.econ else 0}; {how}")
        return self.log("goals", {}, "\n".join(lines))

    def deliver_goal(self, part: str, program: list[str], batch: int = -1) -> str:
        o, d = self.org, self.dev
        args = {"part": part, "program": program, "batch": batch}
        found = next(((g, p) for g in o.goals for p in g.parts if p["id"] == part), None)
        if found is None:
            return self.log("deliver_goal", args, f"No goal part {part!r}.")
        g, p = found
        if g.kind in ("encyclopedia", "fund"):
            return self.log("deliver_goal", args, "That goal is not delivered like this (see goals()).")
        if p.get("done") is not None or o.sprint_no > g.deadline:
            return self.log("deliver_goal", args, "That part is closed.")
        if p.get("tries", 0) >= GOAL_TRIES:
            self._exploit("delivered a goal part after its tries")
            return self.log("deliver_goal", args, "No tries left for that part.")
        prog = [fn for fn in program if fn in self.u.functions]
        if len(prog) != len(program) or not prog:
            return self.log("deliver_goal", args, "Unknown machines in that chain.")
        try:
            d.spend("submit")
        except OutOfBudget:
            return self.log("deliver_goal", args, "Out of budget.")
        p["tries"] = p.get("tries", 0) + 1
        o._project = p["id"]
        ok = check(self.u, g, p, prog, batch if batch >= 0 else None)
        o._ev("submit", d, program=prog, ok=ok, tried=p["tries"], **({"batch_grade": batch} if batch >= 0 else {}))
        if not ok:
            d.rep -= 2
            if o.econ:
                o.pay(d, "treasury", FINE, "fine")
            return self.log("deliver_goal", args, f"Not right. {GOAL_TRIES - p['tries']} tries left for {part}.")
        p["done"], p["by"] = o.sprint_no, d.name
        d.rep += 3
        o._ev("goal_part", d, goal=g.id, part=p["id"])
        if o.econ:
            o.pay("treasury", d, o.econ.bounty, "bounty")
        return self.log("deliver_goal", args, f"Accepted: {part} is done" +
                        (f", bounty {o.econ.bounty} coins." if o.econ else "."))

    def set_price(self, coins: int) -> str:
        if not self.org.econ:
            return self.log("set_price", {"coins": coins}, "There is no money in this town.")
        if coins > PRICE_CAP or coins < 0:
            self._exploit("price outside the cap")
        self.org.prices[self.dev.name] = max(0, min(PRICE_CAP, int(coins)))
        return self.log("set_price", {"coins": coins}, f"Your price is {self.org.prices[self.dev.name]} coins.")

    def pay(self, to: str, amount: int, note: str = "") -> str:
        o, d = self.org, self.dev
        args = {"to": to, "amount": amount, "note": note}
        if not o.econ:
            return self.log("pay", args, "There is no money in this town.")
        if to == d.name:
            self._exploit("paid itself")
            return self.log("pay", args, "You cannot pay yourself.")
        if amount <= 0 or amount > d.coins:
            if amount > d.coins:
                self._exploit("paid more than it has")
            return self.log("pay", args, f"You have {d.coins} coins.")
        dest = "treasury" if to == "treasury" else self._mate(to)
        if dest is None:
            return self.log("pay", args, "Nobody by that name.")
        moved = o.pay(d, dest, int(amount), "gift" if dest == "treasury" else "transfer")
        return self.log("pay", args, f"Paid {moved} coins to {to}.")

    def buy_overtime(self, actions: int) -> str:
        o, d = self.org, self.dev
        if not o.econ:
            return self.log("buy_overtime", {"actions": actions}, "There is no money in this town.")
        actions = int(actions)
        if actions <= 0:
            return self.log("buy_overtime", {"actions": actions}, "Nothing bought.")
        if d._ot + actions > o.econ.overtime_cap:
            self._exploit("overtime above the cap")
            actions = o.econ.overtime_cap - d._ot
        cost = actions * o.econ.overtime_price
        if actions <= 0 or cost > d.coins:
            return self.log("buy_overtime", {"actions": actions}, f"Cannot buy that ({d.coins} coins, {d._ot} bought).")
        d._ot += actions
        o.pay(d, "treasury", cost, "overtime")
        d.budget += actions
        return self.log("buy_overtime", {"actions": actions}, f"Bought {actions} actions for {cost} coins.")

    def hand_over(self, teammate: str, coins: int = 0) -> str:
        o, d = self.org, self.dev
        args = {"teammate": teammate, "coins": coins}
        mate = self._mate(teammate)
        if mate is None:
            if teammate == d.name:
                self._exploit("handed an order to itself")
            return self.log("hand_over", args, "Nobody by that name.")
        if self.project is None:
            return self.log("hand_over", args, "You have no order to hand over.")
        if coins > d.coins or coins < 0:
            return self.log("hand_over", args, f"You have {d.coins} coins.")
        other = o.sessions.get(mate.name)
        if other is None:
            return self.log("hand_over", args, f"{teammate} is not working this sprint.")
        p = self.queue.pop(0)
        self.explained = {}
        other.queue.append(p)
        o._ev("hire", d, to=mate.name, project=p.id)
        if coins and o.econ:
            o.pay(d, mate, int(coins), "wage")
        self._begin()
        return self.log("hand_over", args, f"Order {p.id} is now {teammate}'s" + (f"; paid {coins} coins." if coins else "."))

    def post(self, text: str) -> str:
        try:
            self.dev.spend("write")
        except OutOfBudget:
            return self.log("post", {"text": text}, "Out of budget.")
        self.org.posts.append({"by": self.dev.name, "text": str(text)[:200], "sprint": self.org.sprint_no})
        self.org._ev("post", self.dev, text=str(text)[:200])
        return self.log("post", {"text": text}, "Pinned on the notice board.")

    def board(self) -> str:
        o, d = self.org, self.dev
        if o.u.map is not None:
            err = self._walk(o._nearest(d, "board"))
            if err:
                return self.log("board", {}, err)
        try:
            d.spend("read")
        except OutOfBudget:
            return self.log("board", {}, "Out of budget.")
        lines = [f"{x['by']}: {x['text']}" for x in o.posts[-12:]]
        lines += [f"(rumour) {e['text']}" for e in o.sprint_events if e["kind"] == "rumor"]
        if o.mode in ("owners", "directory"):
            lines += [f"(notice) {fn} is out of order" for fn in sorted(o.notices["broken"])]
            lines += [f"(notice) {fn} was re-tuned" for fn in sorted(o.notices["changed"])]
        if o.mode == "directory" or o.board:
            for x in o.devs:
                if x is not d and x.notebook.laws:
                    lines.append(f"(roster) {x.name} knows: " + ", ".join(sorted(x.notebook.laws)))
        d.broken |= o.notices["broken"]
        o._ev("board", d, entries=len(lines))
        return self.log("board", {}, "\n".join(lines) or "The board is empty.")

    def library_read(self, function: str) -> str:
        o, d = self.org, self.dev
        if not o.library:
            return self.log("library_read", {"function": function}, "There is no library in this town.")
        err = self._walk(o._nearest(d, "library"))
        if err:
            return self.log("library_read", {"function": function}, err)
        try:
            d.spend("read")
        except OutOfBudget:
            return self.log("library_read", {"function": function}, "Out of budget.")
        law = o.lib.get(function)
        if law is None:
            return self.log("library_read", {"function": function}, f"Nothing written about {function}.")
        self.explained[function] = law
        o._ev("read", d, fn=function, also=[])
        return self.log("library_read", {"function": function}, f"The library says {function} is {law.describe()}.")

    def library_write(self, function: str, law: str) -> str:
        o, d = self.org, self.dev
        args = {"function": function, "law": law}
        if not o.library:
            return self.log("library_write", args, "There is no library in this town.")
        parsed = parse_law(law)
        if parsed is None or function not in self.u.functions:
            return self.log("library_write", args, "Could not read that machine name or rule. " + LAW_HELP)
        err = self._walk(o._nearest(d, "library"))
        if err:
            return self.log("library_write", args, err)
        try:
            d.spend("write")
        except OutOfBudget:
            return self.log("library_write", args, "Out of budget.")
        new = o.lib.get(function) is None or o.lib[function].table != parsed.table
        o.lib[function] = parsed
        right = parsed.table == self.u.functions[function].law.table
        if right and new:
            d.rep += 1
            if o.econ and o.ency:
                o.pay("treasury", d, max(1, o.econ.bounty // 5), "bounty")
        o._ev("deposit", d, fn=function)
        return self.log("library_write", args, f"Written down: {function} is {parsed.describe()}.")


def _news(e: dict) -> str:
    k = e["kind"]
    return {"breakdown": f"{e.get('fn')} broke down", "repaired": f"{e.get('fn')} repaired",
            "drift": f"{e.get('fn')} was re-tuned", "festival": f"festival: {e.get('good')} wanted",
            "storm": f"storm over {e.get('area')}"}.get(k, k)


def _tools(s: TownSession):
    from agents import function_tool

    @function_tool
    def signatures(module: str = "") -> str:
        """Recipes of a workshop's machines (all workshops if empty). Free."""
        return s.signatures(module)

    @function_tool
    def run(function: str, x: int) -> str:
        """Run one machine on one grade (walk to its workshop first). 1 action."""
        return s.run(function, x)

    @function_tool
    def study(function: str) -> str:
        """Run a machine on grades 0..7 (walk to its workshop first). 8 actions."""
        return s.study(function)

    @function_tool
    def remember(function: str, law: str) -> str:
        """Write numeric coefficients, e.g. '3*x + 5'; never literal a or b. Contradicting observed samples is rejected. Free."""
        return s.remember(function, law)

    @function_tool
    def notebook() -> str:
        """Your rules, and what others explained for the current order. Free."""
        return s.notebook()

    @function_tool
    def compute(program: list[str], x: int) -> str:
        """Predict from notebook hypotheses only; does not run real machines. Wrong notes give wrong predictions. Free."""
        return s.compute(program, x)

    @function_tool
    def ask(teammate: str, function: str) -> str:
        """Walk to someone and ask them to explain a machine (they may charge). 1 action each."""
        return s.ask(teammate, function)

    @function_tool
    def submit(program: list[str]) -> str:
        """Deliver your current order: the chain of machines, in order. 1 action."""
        return s.submit(program)

    @function_tool
    def town() -> str:
        """Your purse, reputation, the treasury, prices, scores and this sprint's news. Free."""
        return s.town()

    @function_tool
    def goals() -> str:
        """The town's grand goals: open parts, bounties, tries left. Free."""
        return s.goals()

    @function_tool
    def deliver_goal(part: str, program: list[str], batch: int = -1) -> str:
        """Deliver a goal part: a chain of machines (and, for the prize, the raw good's batch grade). 1 action."""
        return s.deliver_goal(part, program, batch)

    @function_tool
    def set_price(coins: int) -> str:
        """What you charge others for explaining a machine. Free."""
        return s.set_price(coins)

    @function_tool
    def pay(to: str, amount: int, note: str = "") -> str:
        """Give coins to someone, or to "treasury". Free."""
        return s.pay(to, amount, note)

    @function_tool
    def buy_overtime(actions: int) -> str:
        """Buy more actions for this sprint with coins (capped). """
        return s.buy_overtime(actions)

    @function_tool
    def hand_over(teammate: str, coins: int = 0) -> str:
        """Give your current order to someone else, paying them coins for it. Free."""
        return s.hand_over(teammate, coins)

    @function_tool
    def letter(teammate: str, function: str) -> str:
        """Ask someone by letter: no walking, but you wait for the answer. 1 action + waiting."""
        return s.letter(teammate, function)

    @function_tool
    def post(text: str) -> str:
        """Pin a note on the notice board for everyone. 1 action."""
        return s.post(text)

    @function_tool
    def board() -> str:
        """Walk to the notice board and read it. 1 action + walking."""
        return s.board()

    @function_tool
    def library_read(function: str) -> str:
        """Walk to the library and read what is written about a machine. 1 action + walking."""
        return s.library_read(function)

    @function_tool
    def library_write(function: str, law: str) -> str:
        """Walk to the library and write a machine's rule down for everyone. 1 action + walking."""
        return s.library_write(function, law)

    o = s.org
    tools = [signatures, run, study, remember, notebook, compute, submit, town, goals, deliver_goal, board, post]
    if o.mode in ("owners", "directory", "random"):
        tools.append(ask)
        if o.post:
            tools.append(letter)
    if o.econ:
        tools += [set_price, pay, buy_overtime]
        if len(o.devs) > 1:
            tools.append(hand_over)
    if o.library:
        tools += [library_read, library_write]
    return tools


def instructions(s: TownSession) -> str:
    from .replay import LOOKS

    o, d = s.org, s.dev
    nick = {x.name: LOOKS[i % len(LOOKS)][0] for i, x in enumerate(o.devs)}
    mates = ", ".join(f"{x.name} ({nick[x.name]})" for x in o.devs if x is not d)
    owners = "; ".join(f"{m}: {x.name}" for m, x in o.owner.items())
    team = TEAM.get(o.mode, TEAM["solo"]).format(mates=mates, owners=owners, mine=", ".join(sorted(d.owns)))
    gl = "; ".join(f"{g.title} (by sprint {g.deadline})" for g in o.goals) or "none"
    return INSTRUCTIONS.format(nick=nick[d.name], name=d.name, n_workshops=len(o.u.modules), n_machines=o.u.n_functions,
                               budget=d.budget, capacity=d.notebook.capacity or "unlimited", team=team,
                               coins=d.coins, treasury=o.treasury, bounty=o.econ.bounty if o.econ else 0, goals=gl,
                               tries=GOAL_TRIES, fine=FINE, signatures=o.u.signatures_text())


async def llm_town_sprint(org: Org, projects: list[Project], budget: int, model, settings, events=None, goals=None,
                          max_turns: int = 200) -> dict:
    """One sprint in the town with LLM apprentices working at the same time."""
    org.begin_sprint(budget, events, goals)
    org.sprint_events = events or []
    sessions = [TownSession(org, d, projects[i::len(org.devs)]) for i, d in enumerate(org.devs)]
    org.sessions = {s.dev.name: s for s in sessions}
    for s in sessions:
        s._begin()
    outs = await asyncio.gather(*[run_dev(s, model, settings, max_turns, tools=_tools(s), text=instructions(s),
                                          more=lambda s=s: bool(s.queue) or _open_goals(s.org)) for s in sessions])
    results = ([{"done": True}] * sum(s.done for s in sessions) +
               [{"done": False}] * sum(len(s.queue) for s in sessions))
    m = org.end_sprint(results, gifts=False)
    m.update(input_tokens=sum(o["input_tokens"] for o in outs), output_tokens=sum(o["output_tokens"] for o in outs),
             statuses=[o["status"] for o in outs], submits=sum(s.submits for s in sessions),
             tool_calls=_tool_counts(sessions), t=time.time())
    return {"metrics": m, "traces": [{"dev": o["dev"], "trace": o["trace"]} for o in outs]}


def _open_goals(org: Org) -> bool:
    return any(g.done_at is None and org.sprint_no <= g.deadline and g.kind not in ("encyclopedia", "fund")
               and any(p.get("done") is None and p.get("tries", 0) < GOAL_TRIES for p in g.parts) for g in org.goals)


def _tool_counts(sessions) -> dict:
    out: dict = {}
    for s in sessions:
        for t in s.trace:
            out[t["tool"]] = out.get(t["tool"], 0) + 1
    return out

