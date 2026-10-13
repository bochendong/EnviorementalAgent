"""Agents (netagents/) driving the network environment through its public interface only."""

from __future__ import annotations

import json
import threading
from http.server import HTTPServer

import pytest

from netagents.client import LocalEnv, RemoteEnv
from netagents.scripted import SOLVERS, solve_codeworld
from netagents.team import random_policy
from netagents.tools import briefing, call
from worldseeds.net import NetConfig, NetworkEnv, providers
from worldseeds.net.presets import build
from worldseeds.net.server import make_handler


def local(name, seed=0, **cfg):
    raw = NetworkEnv(providers.make(name), NetConfig(**cfg))
    raw.reset(seed)
    return raw, LocalEnv(raw)


@pytest.mark.parametrize("name,budget", [("codeworld", 400), ("math", 200), ("website", 100), ("molecule", 600)])
def test_reference_teams_solve_every_provider(name, budget):
    raw, env = local(name, budget=budget)
    SOLVERS[name](env)
    assert raw.solved, raw.metrics()


def test_sharing_laws_saves_work_in_codeworld():
    spent = []
    for share in (True, False):
        raw, env = local("codeworld", 1, budget=400)
        solve_codeworld(env, share)
        assert raw.solved
        spent.append(raw.actions)
    assert spent[0] < spent[1]


@pytest.mark.parametrize("name", ["codeworld/easy", "math/easy", "website/easy", "molecule/easy"])
def test_reference_teams_need_the_network(name):
    raw = build(name)
    raw.reset(0)
    SOLVERS[raw.provider.name](LocalEnv(raw))
    assert raw.solved
    if name != "codeworld/easy":  # without the network, information between roles does not travel
        raw = build(name, "nonet")
        raw.reset(0)
        SOLVERS[raw.provider.name](LocalEnv(raw))
        assert not raw.solved


@pytest.mark.parametrize("name", sorted(providers.PROVIDERS))
def test_random_calls_never_break_a_provider(name):
    raw, env = local(name, 2, budget=60, market="claim", topology="random", latency=1, outage=.1, store_price=1,
                     credits=2)
    random_policy(env, 120, 2)
    assert not [ev for ev in raw.events if ev["kind"] == "provider_error"]


def test_tools_and_briefing():
    raw, env = local("math", budget=30)
    assert {t["function"]["name"] for t in env.tools("a0")} >= {"evaluate", "submit"}
    assert json.loads(call(env, "a0", "evaluate", '{"expr": "2+2"}'))["value"] == "4"
    assert "not JSON" in call(env, "a0", "evaluate", "{oops")
    text = briefing(env, "a0")
    assert "explorer" in text and "evaluate" in text and "submit" in text
    pytest.importorskip("agents")
    from netagents.tools import function_tools

    assert len(function_tools(env, "a0")) == len(env.ops("a0"))


def test_the_same_team_over_http():
    """A reference team gets the same result in this process and over the HTTP API."""
    raw, env = local("website", 3, budget=100)
    SOLVERS["website"](env)
    here = raw.metrics()
    served = NetworkEnv(providers.make("website"), NetConfig(budget=100))
    served.reset(3)
    srv = HTTPServer(("127.0.0.1", 0), make_handler(served))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        remote = RemoteEnv(f"http://127.0.0.1:{srv.server_address[1]}")
        SOLVERS["website"](remote)
        there = remote.metrics()
    finally:
        srv.shutdown()
    assert there["solved"] and there["actions"] == here["actions"]
