"""NetworkEnv: many agents, one task provider, and a configurable network between them.

The environment is a simulator, not a strategy: it offers operations and keeps score; how agents use
them (who asks whom, what to share, how to split the work) is left to whatever drives the agents.

    env = NetworkEnv(provider, NetConfig(...)); env.reset(seed)
    obs = env.step("a0", "send", {"to": "a1", "text": "..."})   # -> {"ok": ..., ...}, charged to a0

Each agent has a role (from the provider) and a budget of actions. Every call costs actions (the op's
cost); a call that fails costs 1. A *round* passes when the agents together have spent ``n_agents``
actions; message latency, outages and the provider's own changes run on rounds. Waiting and calls
made while offline take time but no budget.

Network operations (each can be switched off in ``NetConfig``):

    status    own budget, credits, reputation, role, neighbours, unread mail
    who       everyone: role, reputation, online or not
    tasks     the task market: open, claimed and done tasks
    claim / release    take a task (others see it is taken; ``exclusive`` claims lock it)
    send      a message to a neighbour (or "*" for all neighbours), delivered after ``latency`` rounds
    inbox     read the mail that has arrived
    post / board       the public notice board
    put / get / keys   the shared store: versioned, every version kept, writer and round recorded
    transfer  give credits to someone
    submit    hand in an artifact for a task; checked by the provider (``verify_cost`` actions)
    wait      let time pass (costs no budget)

Rewards: when a task is done its ``reward`` goes to the solver; ``NetConfig.team`` blends individual and
team reward (0 = all own, 1 = everything shared equally). Credits are separate: bounties for done tasks,
transfers, and the price of a store read when ``store_price`` > 0.
"""

from __future__ import annotations

import json
import random
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any

from .core import OpSpec, Role, Score, Task, TaskProvider

ALL_NET_OPS = ("status", "who", "tasks", "claim", "release", "send", "inbox", "post", "board", "put", "get",
               "keys", "transfer", "submit", "wait")


@dataclass
class NetConfig:
    agents: dict[str, int] | None = None  # role -> how many (default: the provider's counts)
    budget: int = 200  # actions per agent
    deadline: int = 0  # rounds until the episode ends (0: none). A round is one action per agent, so a
    # team of n gets n times the actions of one agent in the same time: compute and time are separate.
    messaging: bool = True
    board: bool = True
    store: bool = True
    market: str = "open"  # "open" (anyone submits anything), "claim" (claim first), "assigned" (round robin)
    exclusive: bool = False  # a claim locks the task for others
    topology: str = "full"  # full | ring | star | random
    degree: int = 2  # neighbours each in a random topology
    latency: int = 0  # rounds before a message arrives
    max_message: int = 4000  # characters
    credits: int = 0  # starting credits
    bounty: int = 10  # credits per unit of task reward
    transfers: bool = True
    store_price: int = 0  # credits paid to the writer for each read of their entry
    reputation: bool = True
    verify_cost: int = 1  # actions a submit takes
    wrong_penalty: float = 0.0  # reward lost for a wrong submission
    team: float = 0.0  # 0: reward goes to the solver; 1: shared equally
    outage: float = 0.0  # chance per agent and round of going offline
    outage_rounds: int = 2
    seed: int = 0
    log_args: bool = True

    def enabled(self) -> set[str]:
        off = set()
        if not self.messaging:
            off |= {"send", "inbox"}
        if not self.board:
            off |= {"post", "board"}
        if not self.store:
            off |= {"put", "get", "keys"}
        if not self.transfers:
            off |= {"transfer"}
        if self.market == "open":
            off |= {"claim", "release"}
        return set(ALL_NET_OPS) - off


@dataclass
class Agent:
    name: str
    role: Role
    budget: int
    credits: int = 0
    rep: float = 0.0
    reward: float = 0.0
    spent: int = 0
    offline: int = 0
    neighbours: tuple[str, ...] = ()
    mail: list = field(default_factory=list)  # delivered, unread
    solved: list = field(default_factory=list)


def _p(t: str, doc: str, **kw) -> dict:
    return {"type": t, "description": doc, **kw}


class NetworkEnv:
    def __init__(self, provider: TaskProvider, config: NetConfig | None = None):
        self.provider = provider
        self.cfg = config or NetConfig()
        self.events: list[dict] = []

    # ------------------------------------------------------------------ setup
    def reset(self, seed: int | None = None) -> dict:
        cfg = self.cfg
        self.seed = cfg.seed if seed is None else seed
        self.rng = random.Random(f"net/{self.seed}")
        self.info = self.provider.reset(self.seed)
        self.roles = {r.name: r for r in self.provider.roles()}
        self.pops = {o.name: o for o in self.provider.ops()}
        clash = set(self.pops) & set(ALL_NET_OPS)
        if clash:
            raise ValueError(f"provider ops clash with network ops: {sorted(clash)}")
        counts = cfg.agents or {r.name: r.count for r in self.roles.values()}
        self.agents: dict[str, Agent] = {}
        for rname, n in counts.items():
            for _ in range(n):
                name = f"a{len(self.agents)}"
                self.agents[name] = Agent(name, self.roles[rname], cfg.budget, cfg.credits)
        self._wire()
        self.actions = 0
        self.round = 0
        self.tasks: dict[str, Task] = {}
        self.state: dict[str, dict] = {}  # task id -> {"status", "by", "claims", "tries"}
        self.store: dict[str, list[dict]] = {}
        self.posts: list[dict] = []
        self.transit: list[tuple[int, str, dict]] = []  # (arrival round, to, message)
        self.events = []
        self._sync_tasks()
        self._log({"kind": "reset", "seed": self.seed, "provider": self.provider.name, "info": self.info,
                   "agents": {a.name: a.role.name for a in self.agents.values()},
                   "config": asdict(cfg)})
        return {"info": self.info, "agents": {a.name: a.role.name for a in self.agents.values()}}

    def _wire(self):
        names = list(self.agents)
        n, topo = len(names), self.cfg.topology
        nb: dict[str, set] = {a: set() for a in names}
        if topo == "full":
            for a in names:
                nb[a] = set(names) - {a}
        elif topo == "ring":
            for i, a in enumerate(names):
                if n > 1:
                    nb[a] |= {names[(i - 1) % n], names[(i + 1) % n]} - {a}
        elif topo == "star":
            for a in names[1:]:
                nb[a].add(names[0])
                nb[names[0]].add(a)
        elif topo == "random":
            rng = random.Random(f"topology/{self.seed}")
            for i, a in enumerate(names[1:], 1):  # a random tree keeps everyone reachable
                b = names[rng.randrange(i)]
                nb[a].add(b)
                nb[b].add(a)
            for a in names:
                while len(nb[a]) < min(self.cfg.degree, n - 1):
                    b = rng.choice(names)
                    if b != a:
                        nb[a].add(b)
                        nb[b].add(a)
        else:
            raise ValueError(f"unknown topology {topo!r}")
        for a in names:
            self.agents[a].neighbours = tuple(sorted(nb[a], key=names.index))

    # ------------------------------------------------------------------ the API
    def ops(self, agent: str) -> list[OpSpec]:
        """The operations ``agent`` may call (network ops first, then the provider's, filtered by role)."""
        role = self.agents[agent].role
        net = [o for o in self._net_specs() if o.name in self.cfg.enabled()]
        mine = [o for o in self.pops.values() if role.ops is None or o.name in role.ops]
        return net + mine

    def observe(self, agent: str) -> dict:
        """What an agent sees without spending anything (for prompts and dashboards)."""
        a = self.agents[agent]
        return {"agent": agent, "role": a.role.name, "role_doc": a.role.doc, "round": self.round,
                **({"deadline": self.cfg.deadline} if self.cfg.deadline else {}),
                "budget": a.budget, "credits": a.credits, "reputation": round(a.rep, 2),
                "unread": len(a.mail), "offline": a.offline, "neighbours": list(a.neighbours),
                "open_tasks": [t for t, s in self.state.items() if s["status"] == "open"]}

    @property
    def late(self) -> bool:
        return bool(self.cfg.deadline) and self.round >= self.cfg.deadline

    @property
    def done(self) -> bool:
        if self.late:
            return True
        finals = [t for t in self.tasks.values() if t.final]
        if finals and all(self.state[t.id]["status"] == "done" for t in finals):
            return True
        return all(a.budget <= 0 for a in self.agents.values())

    @property
    def solved(self) -> bool:
        finals = [t for t in self.tasks.values() if t.final] or list(self.tasks.values())
        return bool(finals) and all(self.state[t.id]["status"] == "done" for t in finals)

    def step(self, agent: str, op: str, args: dict | None = None) -> dict:
        args = dict(args or {})
        a = self.agents.get(agent)
        if a is None:
            return {"ok": False, "error": f"no agent {agent!r}"}
        if a.budget <= 0:
            return {"ok": False, "error": "out of budget", "budget": 0}
        if self.late:
            return {"ok": False, "error": f"the deadline (round {self.cfg.deadline}) has passed", "budget": a.budget}
        if a.offline:
            # being offline costs time, not compute
            obs = {"ok": False, "error": f"you are offline for {a.offline} more round(s)", "_cost": 0, "_time": 1}
        elif op in ALL_NET_OPS and op in self.cfg.enabled():
            try:
                obs = getattr(self, f"_op_{op}")(a, **args)
            except TypeError as e:
                obs = {"ok": False, "error": f"bad arguments: {e}"}
            obs.setdefault("_cost", self._net_cost(op))
        elif op in self.pops and (a.role.ops is None or op in a.role.ops):
            try:
                obs = self.provider.apply(agent, a.role, op, args)
            except (TypeError, ValueError, KeyError) as e:
                obs = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            except Exception as e:  # noqa: BLE001 (a provider bug must not kill the episode; it is logged)
                obs = {"ok": False, "error": f"internal error in {op}: {type(e).__name__}"}
                self._log({"kind": "provider_error", "op": op, "error": repr(e), "trace": traceback.format_exc()})
            obs.setdefault("ok", "error" not in obs)
            obs.setdefault("_cost", self.pops[op].cost if obs["ok"] else 1)
        else:
            obs = {"ok": False, "error": f"unknown or forbidden operation {op!r}"}
        cost = max(0, int(obs.pop("_cost", 1)))
        cost = min(cost, a.budget)
        time = max(cost, int(obs.pop("_time", 0)))
        a.budget -= cost
        a.spent += cost
        obs["budget"] = a.budget
        self._log({"kind": "op", "agent": agent, "op": op, "args": args if self.cfg.log_args else None,
                   "cost": cost, "obs": obs})
        self._advance(time)
        return obs

    # ------------------------------------------------------------------ time
    def _advance(self, cost: int):
        self.actions += cost
        n = max(1, len(self.agents))
        while self.actions >= (self.round + 1) * n:
            self.round += 1
            for a in self.agents.values():
                if a.offline:
                    a.offline -= 1
                elif self.cfg.outage and self.rng.random() < self.cfg.outage:
                    a.offline = self.cfg.outage_rounds
                    self._log({"kind": "outage", "agent": a.name, "rounds": a.offline})
            for e in self.provider.tick(self.round):
                self._log({"kind": "world", **e})
                if e.get("public"):
                    self.posts.append({"id": len(self.posts), "by": "world", "round": self.round,
                                       "text": e.get("text", json.dumps(e)), "tags": ["news"]})
            self._sync_tasks()
        keep = []
        for due, to, msg in self.transit:
            if due <= self.round:
                self.agents[to].mail.append(msg)
            else:
                keep.append((due, to, msg))
        self.transit = keep

    def _sync_tasks(self):
        for t in self.provider.tasks():
            if t.id not in self.tasks:
                self.state[t.id] = {"status": "open", "by": None, "claims": [], "tries": 0, "value": 0.0}
                if self.cfg.market == "assigned":
                    names = [a for a in self.agents]
                    self.state[t.id]["claims"] = [names[len(self.tasks) % len(names)]]
            self.tasks[t.id] = t  # a provider may re-issue a task with new text or spec

    def _ready(self, t: Task) -> bool:
        return all(self.state.get(d, {}).get("status") == "done" for d in t.deps)

    # ------------------------------------------------------------------ network ops
    def _net_cost(self, op: str) -> int:
        return {"submit": self.cfg.verify_cost, "status": 0, "who": 0}.get(op, 1)

    def _op_status(self, a: Agent) -> dict:
        return {"ok": True, **self.observe(a.name), "solved": a.solved, "reward": round(a.reward, 3)}

    def _op_who(self, a: Agent) -> dict:
        return {"ok": True, "agents": [{"name": b.name, "role": b.role.name, "reputation": round(b.rep, 2),
                                        "online": not b.offline, "neighbour": b.name in a.neighbours}
                                       for b in self.agents.values()]}

    def _op_tasks(self, a: Agent, status: str = "") -> dict:
        out = []
        for t in self.tasks.values():
            s = self.state[t.id]
            st = s["status"] if self._ready(t) or s["status"] == "done" else "blocked"
            if status and st != status:
                continue
            out.append({"id": t.id, "kind": t.kind, "text": t.text, "deps": list(t.deps), "status": st,
                        "reward": t.reward, "final": t.final, "spec": t.spec, "by": s["by"],
                        "claimed_by": s["claims"], "tries": s["tries"]})
        return {"ok": True, "tasks": out}

    def _op_claim(self, a: Agent, task: str) -> dict:
        s = self.state.get(task)
        if s is None:
            return {"ok": False, "error": f"no task {task!r}"}
        if s["status"] == "done":
            return {"ok": False, "error": "already done"}
        if self.cfg.exclusive and s["claims"] and a.name not in s["claims"]:
            return {"ok": False, "error": f"taken by {s['claims'][0]}"}
        if a.name not in s["claims"]:
            s["claims"].append(a.name)
        return {"ok": True, "task": task, "claimed_by": s["claims"]}

    def _op_release(self, a: Agent, task: str) -> dict:
        s = self.state.get(task)
        if s is None or a.name not in s["claims"]:
            return {"ok": False, "error": "you hold no claim on it"}
        s["claims"].remove(a.name)
        return {"ok": True}

    def _op_send(self, a: Agent, to: str, text: str, data: Any = None) -> dict:
        targets = list(a.neighbours) if to == "*" else [to]
        bad = [t for t in targets if t not in a.neighbours]
        if bad:
            return {"ok": False, "error": f"not your neighbour(s): {bad}; neighbours: {list(a.neighbours)}"}
        if len(text) + len(json.dumps(data)) > self.cfg.max_message:
            return {"ok": False, "error": f"message longer than {self.cfg.max_message} characters"}
        for t in targets:
            msg = {"from": a.name, "round": self.round, "text": text, **({"data": data} if data is not None else {})}
            self.transit.append((self.round + self.cfg.latency, t, msg))
        return {"ok": True, "sent_to": targets, "arrives_in_rounds": self.cfg.latency}

    def _op_inbox(self, a: Agent) -> dict:
        mail, a.mail = a.mail, []
        return {"ok": True, "messages": mail}

    def _op_post(self, a: Agent, text: str, tags: list | None = None) -> dict:
        if len(text) > self.cfg.max_message:
            return {"ok": False, "error": f"post longer than {self.cfg.max_message} characters"}
        p = {"id": len(self.posts), "by": a.name, "round": self.round, "text": text, "tags": list(tags or [])}
        self.posts.append(p)
        return {"ok": True, "id": p["id"]}

    def _op_board(self, a: Agent, tag: str = "", since: int = 0) -> dict:
        ps = [p for p in self.posts if p["id"] >= since and (not tag or tag in p["tags"])]
        return {"ok": True, "posts": ps[-50:]}

    def _op_put(self, a: Agent, key: str, value: Any) -> dict:
        if len(json.dumps(value)) > 20 * self.cfg.max_message:
            return {"ok": False, "error": "value too large"}
        vs = self.store.setdefault(key, [])
        vs.append({"version": len(vs), "by": a.name, "round": self.round, "value": value})
        return {"ok": True, "key": key, "version": len(vs) - 1}

    def _op_get(self, a: Agent, key: str, version: int = -1) -> dict:
        vs = self.store.get(key)
        if not vs:
            return {"ok": False, "error": f"no key {key!r}"}
        if not -len(vs) <= version < len(vs):
            return {"ok": False, "error": f"versions are 0..{len(vs) - 1}"}
        v = vs[version]
        price = self.cfg.store_price if v["by"] != a.name else 0
        if price:
            if a.credits < price:
                return {"ok": False, "error": f"it costs {price} credits; you have {a.credits}"}
            a.credits -= price
            self.agents[v["by"]].credits += price
        return {"ok": True, "key": key, **v, "versions": len(vs), "paid": price}

    def _op_keys(self, a: Agent, prefix: str = "") -> dict:
        return {"ok": True, "keys": {k: {"versions": len(v), "last_by": v[-1]["by"]}
                                     for k, v in sorted(self.store.items()) if k.startswith(prefix)}}

    def _op_transfer(self, a: Agent, to: str, amount: int) -> dict:
        if to not in self.agents or to == a.name:
            return {"ok": False, "error": f"no one called {to!r} to pay"}
        if not 0 < amount <= a.credits:
            return {"ok": False, "error": f"you can give 1..{a.credits}"}
        a.credits -= amount
        self.agents[to].credits += amount
        return {"ok": True, "credits": a.credits}

    def _op_wait(self, a: Agent) -> dict:
        return {"ok": True, "_cost": 0, "_time": 1, "round": self.round}

    def _op_submit(self, a: Agent, task: str, artifact: Any = None, key: str = "") -> dict:
        t, s = self.tasks.get(task), self.state.get(task)
        if t is None:
            return {"ok": False, "error": f"no task {task!r}"}
        if s["status"] == "done":
            return {"ok": False, "error": f"already done by {s['by']}"}
        if not self._ready(t):
            return {"ok": False, "error": f"waits for {[d for d in t.deps if self.state[d]['status'] != 'done']}"}
        if self.cfg.market != "open" and a.name not in s["claims"]:
            return {"ok": False, "error": "claim the task first" if self.cfg.market == "claim" else
                    f"assigned to {s['claims']}"}
        if key:
            vs = self.store.get(key)
            if not vs:
                return {"ok": False, "error": f"no key {key!r}"}
            artifact = vs[-1]["value"]
        s["tries"] += 1
        try:
            score: Score = self.provider.verify(t, artifact, a.name)
        except Exception as e:  # noqa: BLE001 (a malformed artifact is a wrong answer; the bug is logged)
            score = Score(False, 0.0, {"error": f"could not check this artifact ({type(e).__name__})"})
            self._log({"kind": "provider_error", "op": "verify", "error": repr(e), "trace": traceback.format_exc()})
        if score.ok:
            s.update(status="done", by=a.name, value=score.value)
            self._reward(a, t.reward * max(score.value, 0.0))
            a.credits += int(round(self.cfg.bounty * t.reward))
            a.solved.append(t.id)
            if self.cfg.reputation:
                a.rep += 1
            self._log({"kind": "done", "agent": a.name, "task": t.id, "value": score.value})
            self._sync_tasks()
        else:
            if self.cfg.wrong_penalty:
                self._reward(a, -self.cfg.wrong_penalty)
            if self.cfg.reputation:
                a.rep -= 0.25
        return {"ok": score.ok, "task": t.id, "value": score.value, **score.info,
                **({} if score.ok else {"error": score.info.get("error", "not accepted")})}

    def _reward(self, a: Agent, r: float):
        team = self.cfg.team
        a.reward += (1 - team) * r
        for b in self.agents.values():
            b.reward += team * r / len(self.agents)

    # ------------------------------------------------------------------ specs and logs
    def _net_specs(self) -> list[OpSpec]:
        S, I = "string", "integer"
        art = self.provider.artifact_schema()
        return [
            OpSpec("status", "Your role, budget, credits, reputation, neighbours and unread mail (free).", cost=0),
            OpSpec("who", "Everyone in the network: role, reputation, online, neighbour of yours (free).", cost=0),
            OpSpec("tasks", "The task market: every task with its status (open, blocked, done), dependencies and "
                            "who claimed it.", {"status": _p(S, "only tasks with this status (optional)")}),
            OpSpec("claim", "Claim a task so others see you are on it.", {"task": _p(S, "task id")}, ("task",)),
            OpSpec("release", "Drop your claim on a task.", {"task": _p(S, "task id")}, ("task",)),
            OpSpec("send", "Send a message to a neighbour ('*' for all your neighbours).",
                   {"to": _p(S, "agent name or *"), "text": _p(S, "the message"),
                    "data": {"description": "optional structured payload"}}, ("to", "text")),
            OpSpec("inbox", "Read the messages that have arrived."),
            OpSpec("post", "Post on the public notice board.",
                   {"text": _p(S, "the post"), "tags": {"type": "array", "items": {"type": S}}}, ("text",)),
            OpSpec("board", "Read the notice board.", {"tag": _p(S, "only posts with this tag"),
                                                       "since": _p(I, "only posts with id >= since")}),
            OpSpec("put", "Write a value to the shared store (a new version; old versions stay).",
                   {"key": _p(S, "key"), "value": {"description": "any JSON value"}}, ("key", "value")),
            OpSpec("get", "Read a value from the shared store.",
                   {"key": _p(S, "key"), "version": _p(I, "version (default: latest)")}, ("key",)),
            OpSpec("keys", "List the keys in the shared store.", {"prefix": _p(S, "only keys with this prefix")}),
            OpSpec("transfer", "Give credits to someone.", {"to": _p(S, "agent name"), "amount": _p(I, "credits")},
                   ("to", "amount")),
            OpSpec("submit", "Hand in your result for a task; it is checked at once.",
                   {"task": _p(S, "task id"), "artifact": {**art, "description": "the result"},
                    "key": _p(S, "or: submit the latest value under this store key")}, ("task",),
                   cost=self.cfg.verify_cost),
            OpSpec("wait", "Let time pass (one action's worth of time; it costs no budget).", cost=0),
        ]

    def _log(self, e: dict):
        e = {"t": len(self.events), "round": getattr(self, "round", 0), **e}
        self.events.append(e)

    def metrics(self) -> dict:
        done = [t for t, s in self.state.items() if s["status"] == "done"]
        msgs = sum(1 for e in self.events if e.get("op") == "send" and e["obs"].get("ok"))
        return {"provider": self.provider.name, "solved": self.solved, "rounds": self.round,
                "actions": self.actions, "tasks": len(self.tasks), "done": len(done),
                "tries": sum(s["tries"] for s in self.state.values()), "messages": msgs,
                "posts": sum(1 for p in self.posts if p["by"] != "world"),
                "store_keys": len(self.store), "reward": {a.name: round(a.reward, 3) for a in self.agents.values()},
                "credits": {a.name: a.credits for a in self.agents.values()},
                "spent": {a.name: a.spent for a in self.agents.values()}, **self.provider.summary()}

    def save_events(self, path: str):
        with open(path, "w") as f:
            for e in self.events:
                f.write(json.dumps(e, default=str) + "\n")
