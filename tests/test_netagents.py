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


# ---------------------------------------------------------------- published agent designs
@pytest.fixture(scope="module")
def mock_llm():
    pytest.importorskip("agents")
    from http.server import ThreadingHTTPServer

    from netagents.mock_llm_server import Handler

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from netagents.llm import LLMConfig, make_model, make_settings

    cfg = LLMConfig(base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1", model="mock", timeout=30)
    yield make_model(cfg), make_settings(cfg)
    srv.shutdown()


def test_every_design_runs_within_the_same_call_budget(mock_llm):
    from netagents.designs import DESIGNS
    from netagents.evaluate import run_one
    from netagents.testset import Case

    model, settings = mock_llm
    case = Case("math/easy", "math/easy", [0])
    calls = 3 * case.team_size()
    for d in DESIGNS.values():
        r = run_one(d, case, 0, model, settings, calls)
        assert 0 < r["llm_tool_calls"] <= calls, (d.name, r["llm_tool_calls"])
        assert r["agents"] == (1 if d.variant == "solo" else 3)
        assert {"duplicate_work", "unread_messages", "wrong_submissions", "stopped_early"} <= set(r)


def test_designs_restrict_what_members_may_do(mock_llm):
    from netagents.designs import Member

    model, settings = mock_llm
    raw, env = local("math", budget=30)
    worker = Member(env, "a1", model, settings, "", keep=lambda op: op != "submit")
    board_only = Member(env, "a2", model, settings, "", keep=lambda op: op not in ("send", "inbox"))
    assert "submit" not in {t.name for t in worker.agent.tools}
    assert not {"send", "inbox"} & {t.name for t in board_only.agent.tools}
    assert "post" in {t.name for t in board_only.agent.tools}


def test_test_set_is_well_formed():
    from netagents.testset import DEV_SEEDS, SUITES, TEST_SEEDS

    assert not set(DEV_SEEDS) & set(TEST_SEEDS)
    for suite, cases in SUITES.items():
        for c in cases:
            raw = c.build("team")
            raw.reset(c.seeds[0])
            assert raw.tasks, (suite, c.id)
    sizes = [c.team_size() for c in SUITES["scaling"]]
    assert sizes == [2, 4, 8, 16]


@pytest.mark.skipif(not __import__("os").environ.get("NETAGENTS_PY_AUTOGEN"),
                    reason="set NETAGENTS_PY_AUTOGEN to a Python with autogen-agentchat 0.7.5")
def test_autogen_teams_run_through_the_http_api(mock_llm, monkeypatch):
    import asyncio

    from netagents.frameworks import FRAMEWORK_DESIGNS

    model, _ = mock_llm
    monkeypatch.setenv("WS_BASE_URL", str(model.__dict__.get("_client").base_url).rstrip("/"))
    monkeypatch.setenv("WS_MODEL", "mock")
    for name in ("autogen-roundrobin", "autogen-selector", "magentic-one"):
        raw = presets_build("math/easy")
        rep = asyncio.run(FRAMEWORK_DESIGNS[name].play(LocalEnv(raw), None, None, 9))
        ops = [e for e in raw.events if e.get("kind") == "op"]
        assert rep[0]["tool_calls"] == len(ops) and 0 < len(ops) <= 9, (name, rep)


def presets_build(name):
    raw = build(name)
    raw.reset(0)
    return raw
