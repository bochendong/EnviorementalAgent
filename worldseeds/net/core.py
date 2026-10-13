"""The contract between the network and a task.

The network (``env.py``) knows nothing about what is being worked on. It moves messages, keeps the task
market, the shared store, credits and reputation, and charges every action against an agent's budget.
What is worked on comes from a *task provider*: a math problem cut into lemmas, a website cut into
features, a molecule to design, the synthetic CodeWorld. A provider says

    roles()      who can take part and which of its operations each role may use
    ops()        the operations it offers (name, help, JSON-schema parameters, cost in actions)
    reset(seed)  start a fresh instance; returns a public description
    apply(...)   carry out one operation for one agent and return what the agent sees
    tasks()      the tasks that exist now (a DAG: a task opens when the tasks it depends on are done)
    verify(...)  score a submitted artifact for a task (the ground truth lives only here)
    tick(round)  optional: let the world change (drift, new requirements, new tasks)

Swapping a provider swaps the work and keeps everything else: the same network switches, the same logs,
the same automatically generated LLM tools, the same HTTP API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OpSpec:
    """One operation an agent can call. ``params`` maps a parameter name to a JSON schema."""

    name: str
    doc: str
    params: dict[str, dict] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    cost: int = 1  # actions it takes (an observation may report a different cost in "_cost")

    def schema(self) -> dict:
        return {"type": "object", "properties": self.params, "required": list(self.required),
                "additionalProperties": False}

    def to_dict(self) -> dict:
        return {"name": self.name, "doc": self.doc, "parameters": self.schema(), "cost": self.cost}


@dataclass
class Role:
    """A kind of participant. ``ops`` limits the provider operations it may use (None: all of them);
    ``scope`` is free-form data the provider reads (the modules one owns, the paths one may write ...)."""

    name: str
    doc: str = ""
    ops: tuple[str, ...] | None = None
    count: int = 1
    scope: dict = field(default_factory=dict)


@dataclass
class Task:
    id: str
    text: str
    kind: str = "task"
    deps: tuple[str, ...] = ()
    reward: float = 1.0  # in score; the bounty in credits is ``reward * NetConfig.bounty``
    spec: dict = field(default_factory=dict)  # public, machine-readable details
    final: bool = False  # the goal of the whole episode (the episode is solved when every final task is done)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Score:
    ok: bool
    value: float = 0.0  # in [0, 1]; partial credit where the task allows it
    info: dict = field(default_factory=dict)  # what the submitter is told (never the hidden answer)


class TaskProvider(ABC):
    name = "provider"

    @abstractmethod
    def reset(self, seed: int = 0) -> dict: ...

    @abstractmethod
    def roles(self) -> list[Role]: ...

    @abstractmethod
    def ops(self) -> list[OpSpec]: ...

    @abstractmethod
    def apply(self, agent: str, role: Role, op: str, args: dict) -> dict: ...

    @abstractmethod
    def tasks(self) -> list[Task]: ...

    @abstractmethod
    def verify(self, task: Task, artifact: Any, agent: str) -> Score: ...

    def tick(self, round: int) -> list[dict]:
        """Called once per round; returns events (public ones carry ``"public": True``)."""
        return []

    def artifact_schema(self) -> dict:
        """The JSON schema of what ``submit`` takes for this provider."""
        return {"type": "string"}

    def summary(self) -> dict:
        return {}
