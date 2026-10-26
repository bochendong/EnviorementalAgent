"""Synchronous time for a team of LLM agents: every round, every agent takes one action.

LLM agents run concurrently and at different speeds, so the environment's own clock (a round passes when
the team has spent one action per member) says nothing about how long a team took when one member works
and the others idle. ``Lockstep`` makes time the parallel computer's: an agent's action waits until every
agent still working has chosen its action for the round; then the round's actions are applied, in the
environment's agent order (as netagents/scaling.py's scripted team), and the round ends. An operation that
costs k actions keeps its agent busy for k rounds. ``round`` at the end is the team's time, comparable to
the scripted reference's rounds.

An agent takes part while a member is in a turn (``join`` / ``leave``, called by designs.Member): a member
between turns, or one that stopped, does not hold the others up.
"""

from __future__ import annotations

import asyncio

from .client import LocalEnv


class Lockstep(LocalEnv):
    def __init__(self, env):
        super().__init__(env)
        self.order = list(env.agents)
        self.live: set[str] = set()
        self.pending: dict[str, tuple] = {}  # agent -> (op, args, future)
        self.busy: dict[str, tuple] = {}  # agent -> (round it is free again, future, observation)
        self.locks = {a: asyncio.Lock() for a in self.order}
        self.round = 0
        self.solved_at: int | None = None
        self.acted = {a: 0 for a in self.order}  # rounds in which each agent acted
        self.on_round = None  # called after every round (evaluate.run_one saves a run's progress with it)

    def join(self, agent: str):
        self.live.add(agent)

    def leave(self, agent: str):
        self.live.discard(agent)
        self._fire()

    async def astep(self, agent: str, op: str, args: dict | None = None) -> dict:
        async with self.locks[agent]:  # one action per agent per round, however many calls a reply holds
            fut = asyncio.get_running_loop().create_future()
            self.pending[agent] = (op, args or {}, fut)
            self._fire()
            return await fut

    def _waiting_for(self) -> set[str]:
        return {a for a in self.live if a not in self.busy}

    def _fire(self):
        """Close rounds while every free working agent has an action waiting; when every working agent is
        busy with a long operation, empty rounds pass."""
        while True:
            free = self._waiting_for()
            if self.pending and set(self.pending) >= free:
                for a in [a for a in self.order if a in self.pending]:
                    op, args, fut = self.pending.pop(a)
                    n = len(self._env.events)
                    obs = self._env.step(a, op, args)
                    took = max([1] + [e.get("cost", 0) for e in self._env.events[n:] if e.get("kind") == "op"])
                    self.acted[a] += 1
                    self.busy[a] = (self.round + took, fut, obs)
            elif not (self.busy and not free and not self.pending):
                return
            self.round += 1
            if self.solved_at is None and self._env.solved:
                self.solved_at = self.round
            if self.on_round is not None:
                self.on_round(self)
            for a, (until, fut, obs) in list(self.busy.items()):
                if until <= self.round:
                    del self.busy[a]
                    if not fut.done():
                        fut.set_result(obs)

    def report(self) -> dict:
        return {"steps": self.round, "solved_step": self.solved_at, "acted": dict(self.acted)}
