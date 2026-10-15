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


@pytest.mark.parametrize("variant", ["team", "solo", "nonet"])
@pytest.mark.parametrize("seed", [0, 1, 100])
def test_reference_math_team_handles_linked_recurrences(variant, seed):
    raw = build("compat/math-sequential", variant)
    raw.reset(seed)
    SOLVERS["math"](LocalEnv(raw))
    assert raw.solved == (variant != "nonet")
    assert raw.metrics()["done"] > 0
    if variant == "team":
        assert any(e.get("op") in ("send", "put", "post") for e in raw.events)


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


@pytest.mark.skipif(not __import__("os").environ.get("NETAGENTS_PY_CAMEL"),
                    reason="set NETAGENTS_PY_CAMEL to a Python with camel-ai 0.2.90")
def test_camel_role_play_runs_through_the_http_api(mock_llm, monkeypatch):
    import asyncio

    from netagents.frameworks import FRAMEWORK_DESIGNS

    model, _ = mock_llm
    monkeypatch.setenv("WS_BASE_URL", str(model.__dict__.get("_client").base_url).rstrip("/"))
    monkeypatch.setenv("WS_MODEL", "mock")
    d = FRAMEWORK_DESIGNS["camel-roleplay"]
    raw = build("math/easy", d.variant)
    raw.reset(0)
    rep = asyncio.run(d.play(LocalEnv(raw), None, None, 9))
    ops = [e for e in raw.events if e.get("kind") == "op"]
    assert rep[0]["tool_calls"] == len(ops) and 0 < len(ops) <= 9 and len(raw.agents) == 1


def presets_build(name):
    raw = build(name)
    raw.reset(0)
    return raw


def test_fidelity_scoring_is_strict():
    from netagents.fidelity import bootstrap, correct, parse, vote

    assert parse("so the answer is \\boxed{1,234}") == "1234" and parse("it is 18 eggs") == "18"
    assert parse("no idea") is None and not correct(None, "3")  # unparseable is wrong (unlike eval_gsm.py)
    assert vote(["3", "4", "3", None]) == "3" and correct("3.0", "3")
    lo, hi = bootstrap([True, True, False, True], [False, True, False, False])
    assert lo <= .5 <= hi


def test_channel_routes_messages_through_the_framework_or_the_network():
    from netagents.designs import Channel

    raw = build("math/easy", net_change={"topology": "chain"})
    raw.reset(0)
    env = LocalEnv(raw)
    a, b, c = list(raw.agents)
    free = Channel(env, "framework")
    assert free.send(a, c, "x = 3", "solution") == "x = 3"
    free.post(a, "note")
    assert free.read(b) == ["note"] and not [e for e in raw.events if e.get("kind") == "op"]
    net = Channel(env, "network")
    before = raw.agents[a].budget
    assert net.send(a, b, "x = 3", "solution") == "x = 3"
    assert raw.agents[a].budget < before  # the send is charged to the sender
    assert {"send", "inbox"} <= {e["op"] for e in raw.events if e.get("kind") == "op"}
    assert net.send(a, c, "x = 3", "solution") is None  # not a neighbour on a chain: lost
    assert net.report() == {"route": "network", "delivered": 1, "lost": 1}
    assert net.send("orchestrator", a, "hi", "guidance") == "hi"  # a non-agent speaks from the first seat
    net.post(b, "on the board")
    assert "on the board" in net.read(c)
    net.remove({"on the board"})
    assert "on the board" not in net.read(c)


def test_compat_track_and_published_findings():
    from netagents.designs import DESIGNS
    from netagents.evaluate import check_hypotheses
    from netagents.testset import HYPOTHESES, SUITES

    compat = {c.id: c for c in SUITES["compat"]}
    assert all(c.route == "framework" for c in compat.values())
    assert all(c.route == "network" for c in SUITES["test"])
    for h in HYPOTHESES:
        assert h.case in compat and h.design in DESIGNS and h.baseline in DESIGNS
    for name in ("compat/math-decomposable", "compat/math-sequential"):
        raw = compat[name].build("team")
        raw.reset(100)
        assert set(raw.public()["agents"].values()) == {"mathematician"} and raw.cfg.deadline == 0
    rows = [{"design": d, "case": "compat/math-decomposable", "seed": s, "completion": v}
            for s in range(8) for d, v in (("sas", .4), ("centralized", .7 + .01 * s))]
    rows += [{"design": d, "case": "compat/math-sequential", "seed": s, "completion": v}
             for s in range(8) for d, v in (("sas", .4), ("centralized", .7))]
    got = {(c["case"], c["design"]): c["verdict"] for c in check_hypotheses(rows)}
    assert got == {("compat/math-decomposable", "centralized"): "reproduced",
                   ("compat/math-sequential", "centralized"): "contradicted"}


def test_designs_run_on_both_tracks(mock_llm):
    from netagents.designs import DESIGNS
    from netagents.evaluate import run_one
    from netagents.testset import Case

    model, settings = mock_llm
    case = Case("compat/math-sequential", "compat/math-sequential", [0], track="compat")
    calls = 3 * case.team_size()
    for name in ("debate", "centralized", "decentralized", "blackboard"):
        free = run_one(DESIGNS[name], case, 0, model, settings, calls)
        assert free["route"] == "framework" and free["messages"] == 0 and free["posts"] == 0, name
        net = run_one(DESIGNS[name], case, 0, model, settings, calls, route="network")
        assert net["route"] == "network" and net["channel"]["delivered"] + net["channel"]["lost"] > 0, name
        assert net["messages"] + net["posts"] > 0, name
    assert DESIGNS["debate"].route == "framework"  # the registry's designs are not changed


@pytest.mark.parametrize("design", ["centralized", "hybrid"])
@pytest.mark.parametrize("network", [{"topology": "chain"}, {"outage": 1.0}])
def test_orchestrators_handle_missing_network_findings(mock_llm, design, network):
    from netagents.designs import DESIGNS
    from netagents.evaluate import run_one
    from netagents.testset import Case

    model, settings = mock_llm
    case = Case("missing-findings", "math/medium", [0], net=network)
    calls = 2 * case.team_size()
    result = run_one(DESIGNS[design], case, 0, model, settings, calls)
    assert result["channel"]["lost"] > 0
    assert result["llm_tool_calls"] <= calls


def test_runs_resume_and_summaries_merge(tmp_path):
    from netagents.evaluate import load_runs, write_summary

    for design, v in (("sas", .2), ("centralized", .6)):
        (tmp_path / design).mkdir()
        with open(tmp_path / design / "runs.jsonl", "w") as f:
            for s in range(6):
                f.write(json.dumps({"design": design, "case": "compat/math-decomposable", "seed": s, "solved": False,
                                    "completion": v + .01 * s, "input_tokens": 1, "output_tokens": 1,
                                    "wrong_submissions": 0, "duplicate_work": 0, "route": "framework"}) + "\n")
    rows = load_runs(str(tmp_path))
    assert len(rows) == 12 and len(load_runs(str(tmp_path / "sas" / "runs.jsonl"))) == 6
    text = write_summary(str(tmp_path), rows, "compat")
    assert "reproduced" in text and (tmp_path / "hypotheses.json").exists()


def test_history_is_trimmed_without_orphan_tool_results():
    from netagents.designs import _tokens, trim

    h = [{"role": "user", "content": "the task"}]
    for i in range(40):
        h += [{"type": "function_call", "call_id": f"c{i}", "name": "tasks", "arguments": "{}"},
              {"type": "function_call_output", "call_id": f"c{i}", "output": "x" * 400}]
    out, cut = trim(h, 2000)
    assert cut and out[0] == h[0] and _tokens(out) <= 2000
    assert out[2].get("type") != "function_call_output"  # after the note, never a result without its call
    assert trim(h[:3], 2000) == (h[:3], False)


def test_llm_settings_are_shared():
    from netagents.llm import LLMConfig

    cfg = LLMConfig(model="qwen3-8b", thinking=True, temperature=0.6, top_p=0.95, top_k=20, max_tokens=4096)
    s = cfg.sampling()
    assert s["extra_body"] == {"top_k": 20, "chat_template_kwargs": {"enable_thinking": True}}
    assert s["temperature"] == 0.6 and s["max_tokens"] == 4096
