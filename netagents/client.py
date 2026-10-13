"""The only way agents touch the environment: its public interface, in this process or over HTTP."""

from __future__ import annotations

import json
import urllib.request


class LocalEnv:
    """A NetworkEnv in this process, seen through its public interface only."""

    def __init__(self, env):
        self._env = env

    def reset(self, seed: int | None = None) -> dict:
        return self._env.reset(seed)

    def public(self) -> dict:
        return self._env.public()

    def ops(self, agent: str) -> list[dict]:
        return [s.to_dict() for s in self._env.ops(agent)]

    def tools(self, agent: str) -> list[dict]:
        return [s.to_openai() for s in self._env.ops(agent)]

    def observe(self, agent: str) -> dict:
        return self._env.observe(agent)

    def step(self, agent: str, op: str, args: dict | None = None) -> dict:
        return self._env.step(agent, op, args or {})

    def metrics(self) -> dict:  # for the experimenter, not for agents
        return self._env.metrics()

    def events(self, since: int = 0) -> list[dict]:
        return self._env.events[since:]


class RemoteEnv:
    """The same interface over the HTTP API of ``worldseeds.net.server``."""

    def __init__(self, base_url: str = "http://127.0.0.1:8090", timeout: float = 120.0):
        self.base, self.timeout = base_url.rstrip("/"), timeout

    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
            return json.loads(r.read())

    def _post(self, path: str, body: dict):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def reset(self, seed: int | None = None) -> dict:
        return self._post("/reset", {"seed": seed})

    def public(self) -> dict:
        return self._get("/info")

    def ops(self, agent: str) -> list[dict]:
        return self._get(f"/ops?agent={agent}")["ops"]

    def tools(self, agent: str) -> list[dict]:
        return self._get(f"/ops?agent={agent}")["tools"]

    def observe(self, agent: str) -> dict:
        return self._get(f"/observe?agent={agent}")

    def step(self, agent: str, op: str, args: dict | None = None) -> dict:
        return self._post("/step", {"agent": agent, "op": op, "args": args or {}})

    def metrics(self) -> dict:
        return self._get("/metrics")

    def events(self, since: int = 0) -> list[dict]:
        return self._get(f"/events?since={since}")["events"]
