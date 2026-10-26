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


def test_a_team_of_one_is_not_shown_sharing_tools():
    from netagents.tools import briefing

    raw = build("compat/math-decomposable", "solo")
    raw.reset(0)
    names = {o["name"] for o in LocalEnv(raw).ops("a0")}
    assert not names & {"send", "inbox", "post", "board", "put", "get", "keys", "transfer"}
    assert {"tasks", "submit", "rsolve"} <= names and "alone" in briefing(LocalEnv(raw), "a0")
    assert not raw.step("a0", "put", {"key": "k", "value": "v"})["ok"]
    team = build("math/medium", "team")
    team.reset(0)
    assert {"send", "put", "board"} <= {o["name"] for o in LocalEnv(team).ops("a0")}


def test_calibration_verdicts():
    from netagents.evaluate import calibration
    from netagents.testset import SUITES

    assert {c.id for c in SUITES["calibration"]} >= {"math/easy", "math/medium", "compat/math-sequential"}
    rows = [{"case": c, "design": d, "completion": v} for c, v in (("a", .05), ("b", .5), ("c", .95))
            for d in ("sas", "centralized")]
    text = calibration(rows)
    assert "| a | 2 | 0.05" in text and "too hard" in text and "in range" in text and "too easy" in text


def test_designs_run_under_the_new_mechanisms(mock_llm, tmp_path):
    from netagents.designs import DESIGNS
    from netagents.evaluate import run_one
    from netagents.testset import SUITES

    model, settings = mock_llm
    cases = {c.id: c for s in ("org", "faults", "report", "memory") for c in SUITES[s]}
    for cid in ("math/medium/org2", "math/medium/silent", "math/medium/report-provenance", "math/medium/memory"):
        c = cases[cid]
        for name in ("sas", "centralized", "debate"):
            mem = str(tmp_path / f"{name}.json") if c.memory else ""
            r = run_one(DESIGNS[name], c, c.seeds[0], model, settings, 2 * c.team_size(), memory=mem)
            assert {"unsupported", "unseen", "used_faulty"} <= set(r), (cid, name)
            if "org" in cid and name != "sas":
                assert r["agents"] > c.team_size()  # the workers and their managers
            if "report" in cid:
                assert "report_score" in r


def test_a_step_whose_thinking_runs_out_is_redone_without_thinking():
    pytest.importorskip("agents")
    import asyncio
    from http.server import ThreadingHTTPServer

    from netagents.designs import Member
    from netagents.llm import LLMConfig, make_model, make_settings
    from netagents.mock_llm_server import Handler

    class Overthinker(Handler):  # thinking always uses up the output: no text, no tool call
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            raw = self.rfile.read(n)
            body = json.loads(raw)
            if (body.get("chat_template_kwargs") or {}).get("enable_thinking"):
                data = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": "m", "choices": [
                    {"index": 0, "finish_reason": "length", "message": {"role": "assistant", "content": None}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 8192, "total_tokens": 8202}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.rfile = __import__("io").BytesIO(raw)
            super().do_POST()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Overthinker)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = LLMConfig(base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1", model="qwen3-mock", timeout=30,
                        thinking=True)
        raw, env = local("math", budget=30)
        m = Member(env, "a0", make_model(cfg), make_settings(cfg), "")
        asyncio.run(m.turn("Begin.", 2))
        assert m.overflows >= 1 and not m.errors and m.calls >= 1
    finally:
        srv.shutdown()


def test_load_suite_grows_the_world_not_the_work():
    from netagents.testset import SUITES

    cases = {c.id: c for c in SUITES["load"]}
    seen = []
    for m in (4, 8, 12):
        raw = cases[f"load/codeworld-m{m}-split"].build("team")
        raw.reset(100)
        s = raw.provider.summary()
        assert len(raw.tasks) == 6 and all(len(p.target) == 3 for p in raw.provider.projects.values())
        assert len(raw.agents) == 4 and s["functions"] == 4 * m
        seen.append(s["candidates_per_project"])
        owned = [set(raw.agents[a].role.scope["modules"]) for a in raw.agents]
        assert set().union(*owned) == set(raw.provider.u.modules) and sum(map(len, owned)) == m
    assert seen == sorted(seen) and seen[0] < seen[-1]
    assert not cases["load/codeworld-m8-split"].solo_too and cases["load/codeworld-m8-shared"].solo_too


def test_scaling_reference_obeys_brent_and_solves():
    from netagents import scaling

    for n in (1, 2, 4, 8):
        for grain in (1, 3):
            r = scaling.run(4, 3, n, seed=0, grain=grain)
            assert r["solved"]
            # no team beats the lower bound by more than a round per layer (an agent sees what another did
            # earlier in the same round); sharing costs at most a read and a write per task
            assert r["lower_bound"] - r["depth"] - 1 <= r["rounds"] <= r["lower_bound"] + 2 * (r["depth"] + 1) + \
                (4 * 3 + 1) * 2 // n + 1
            if n == 1:
                assert r["rounds"] == r["work"] == r["lower_bound"]


def test_lockstep_rounds_wait_for_every_working_agent():
    import asyncio
    import random

    from netagents.lockstep import Lockstep

    raw = build("dag/fixed", opt={"agents": 3, "width": 2, "depth": 2})
    raw.reset(0)
    env = Lockstep(raw)
    rng = random.Random(0)

    async def agent(name, ops):
        env.join(name)
        try:
            for op, args in ops:
                await asyncio.sleep(rng.random() / 100)  # agents think at different speeds
                await env.astep(name, op, args)
        finally:
            env.leave(name)

    async def go():
        await asyncio.gather(agent("a0", [("wait", {})] * 5), agent("a1", [("wait", {})] * 2),
                             agent("a2", [("submit", {"task": "L0.0", "artifact": "1"})]))

    asyncio.run(go())
    rep = env.report()
    assert rep["steps"] == 5 and rep["acted"] == {"a0": 5, "a1": 2, "a2": 1}
    assert raw.round == (5 + 2 + raw.cfg.verify_cost) // 3  # the environment's own clock counts actions, not time


def test_peers_run_in_lockstep_against_the_reference(mock_llm):
    from netagents.designs import DESIGNS
    from netagents.evaluate import run_one
    from netagents.testset import Case, netscale_case

    model, settings = mock_llm
    case = Case("dag/fixed/tiny", "dag/fixed", [0], opt={"agents": 3, "width": 2, "depth": 2}, lockstep=True)
    r = run_one(DESIGNS["peers"], case, 0, model, settings, 12)
    assert r["agents"] == 3 and 0 < r["llm_tool_calls"] <= 12
    assert r["steps"] >= max(r["acted"].values()) and r["reference_steps"] >= r["lower_bound"] > 0
    assert r["work"] == (2 * 2 + 1) * 2
    c = netscale_case("scaled", 8, [0], grain=4)
    assert (c.opt["width"], c.opt["grain"], c.team_size()) == (8, 4, 8)


def test_netscale_table_and_usl_fit():
    from netagents.netscale import fit_usl, table, usl

    sigma, kappa, err = fit_usl([(n, usl(n, 0.1, 0.02)) for n in (1, 2, 4, 8, 16)])
    assert abs(sigma - 0.1) < 0.02 and abs(kappa - 0.02) < 0.005 and err < 0.05
    rows = [{"design": "peers", "case": f"dag/fixed/n{n}", "seed": s, "agents": n, "solved": True,
             "solved_step": 130 // n + 30, "steps": 130 // n + 30, "reference_steps": 129 if n == 1 else 300 // n + 35,
             "width": 16, "depth": 4, "ops": {"sequence": 64, "get": 30 if n > 1 else 0, "wait": n},
             "acted": {f"a{i}": 10 for i in range(n)}, "duplicate_work": 0, "wrong_submissions": 0}
            for n in (1, 2, 4, 8) for s in (0, 1)]
    text = table(rows)
    assert "peers, fixed family" in text and "Universal Scalability Law" in text


def test_batch_reference_and_sharing_labels():
    from netagents import scaling
    from netagents.netscale import sharing

    r = scaling.run(16, 4, 4, seed=100)
    assert r["rounds_batch"] < r["rounds_broadcast"] < r["rounds_store"] and r["sharing"] == "batch"
    assert r["lower_bound"] <= r["rounds"]
    base = {"agents": 4, "tasks": 65}
    assert sharing({**base, "ops": {"put": 60, "send": 20}}) == "store"
    assert sharing({**base, "ops": {"send": 26}}) == "batch"
    assert sharing({**base, "ops": {"send": 70}}) == "broadcast"
    assert sharing({**base, "agents": 1, "ops": {}}) == "none"


def test_superstep_overhead_and_prediction():
    from netagents.netscale import predict, superstep_overhead

    from netagents.scaling import layered_bound

    assert [layered_bound(16, 4, n, 4) for n in (1, 8, 16, 32)] == [325, 45, 25, 25]
    rows = [{"agents": n, "solved_step": layered_bound(16, 4, n, 4) + 5 * 3, "lower_bound": 0, "depth": 4,
             "width": 16, "grain": 4, "seed": 100} for n in (2, 4, 8)]
    b = superstep_overhead(rows)
    assert b["L"] == 3 and b["L_ref"] > 0
    assert predict(rows[0], 32, b) == 25 + 5 * 3  # one task per agent and layer: the span


def test_phases_of_a_scripted_run(tmp_path):
    import gzip

    from netagents import scaling
    from netagents.netscale import phases

    env = scaling.make_env(8, 3, 4, seed=0, grain=2)
    r = scaling.scripted_batch(env)
    path = tmp_path / "t.jsonl.gz"
    with gzip.open(path, "wt") as f:
        for e in env.events:
            f.write(json.dumps(e) + "\n")
    p = phases(str(path), 2, 8)
    assert p["agents"] == 4 and len(p["layer_excess"]) == 3 and min(p["layer_excess"]) >= 0
    assert p["join"] >= 3 and p["join_store_reads"] == 0
    # the layers and the join add up to the run's time
    assert sum(p["layer_excess"]) + 3 * 2 * 3 + p["join"] == r["rounds"]


def test_history_is_trimmed_before_every_model_call(mock_llm, monkeypatch):
    from netagents import designs
    from netagents.evaluate import run_one
    from netagents.testset import Case

    model, settings = mock_llm
    monkeypatch.setattr(designs, "CONTEXT_TOKENS", 3000)
    case = Case("dag/fixed/trim", "dag/fixed", [0], opt={"agents": 1, "width": 4, "depth": 2}, lockstep=True)
    r = run_one(designs.DESIGNS["peers"], case, 0, model, settings, 40)  # one turn of up to 40 calls
    m = r["members"][0]
    assert m["trims"] > 0 and m["peak_context"] <= 3000


def test_intervention_designs_add_one_rule(mock_llm):
    from netagents.designs import COLUMNS_RULE, DESIGNS, LEDGER_RULE, MESSAGE_JOIN_RULE, PEERS_PROTOCOL, Member
    from netagents.evaluate import run_one
    from netagents.testset import SUITES, Case

    model, settings = mock_llm
    seen = []
    orig = Member.__post_init__

    def spy(self):
        seen.append(self.protocol)
        orig(self)

    Member.__post_init__ = spy
    try:
        case = Case("dag/fixed/tiny", "dag/fixed", [0], opt={"agents": 3, "width": 2, "depth": 2}, lockstep=True)
        for name, rule in (("peers-columns", COLUMNS_RULE), ("peers-msgjoin", MESSAGE_JOIN_RULE),
                           ("peers-ledger", LEDGER_RULE)):
            seen.clear()
            r = run_one(DESIGNS[name], case, 0, model, settings, 9)
            assert r["design"] == name and seen == [PEERS_PROTOCOL.format(n=3) + " " + rule] * 3
            assert all(("ledger" in m) == (name == "peers-ledger") for m in r["members"])
        seen.clear()
        run_one(DESIGNS["peers"], case, 0, model, settings, 9)
        assert seen == [PEERS_PROTOCOL.format(n=3)] * 3
    finally:
        Member.__post_init__ = orig
    assert [c.id for c in SUITES["netscale-intervene"]] == ["dag/fixed-g4/n16", "dag/fixed-g4/n32"]


def test_lockstep_runs_save_their_progress(mock_llm, tmp_path):
    from netagents.designs import DESIGNS
    from netagents.evaluate import run_one
    from netagents.testset import Case

    model, settings = mock_llm
    case = Case("dag/fixed/tiny", "dag/fixed", [0], opt={"agents": 3, "width": 2, "depth": 2}, lockstep=True)
    path = str(tmp_path / "progress" / "peers__tiny__0")
    r = run_one(DESIGNS["peers"], case, 0, model, settings, 60, progress=path)
    state = json.load(open(path + ".json"))
    assert state["round"] == r["steps"] and state["tasks"] == r["tasks"] and state["done"] == r["done"]
    assert sum(state["ops"].values()) == sum(r["ops"].values())
    if r["steps"] >= 20:
        assert (tmp_path / "progress" / "peers__tiny__0.trace.jsonl.gz").exists()


def _walk(env, raw, rounds):
    """Members that work down the full task list in order, as the Qwen3-8B team of the 2026-10-25 smoke did
    (results/net/runs/20261023-netscale-smoke): apply a task from inputs they know (recomputing an input they
    lack), submit, go on to the next. With a ledger they move the first task it lists as open to the front and keep
    the answers it hands back. Returns the calls made until the episode was over."""
    import re

    names, order = list(raw.agents), list(raw.tasks)
    deps = {t: list(raw.tasks[t].deps) for t in order}
    known = {a: {} for a in names}
    queue = {a: list(order) for a in names}
    todo = {a: None for a in names}  # a value waiting to be submitted: (task, value)
    calls = 0
    for _ in range(rounds):
        for a in names:
            if raw.done:
                return calls
            calls += 1
            if todo[a]:
                task, v = todo[a]
                todo[a] = None
                obs = env.step(a, "submit", {"task": task, "artifact": str(v)})
            else:
                task = queue[a][0]
                while any(d not in known[a] for d in deps[task]):
                    task = next(d for d in deps[task] if d not in known[a])
                x = [known[a][d] for d in deps[task]] or int(re.search(r"x = (\d+)", raw.tasks[task].text).group(1))
                obs = env.step(a, "apply", {"task": task, "x": x})
                if "f(x)" in obs:
                    known[a][task] = obs["f(x)"]
                    todo[a] = (task, obs["f(x)"])
            if obs.get("answer") is not None:
                known[a][obs["task"]] = int(obs["answer"])
            for t in obs.get("open_now", []):
                known[a].update({d: int(v) for d, v in t.get("inputs", {}).items()})
            queue[a] = [t for t in queue[a] if t not in known[a]]
            if obs.get("open_now"):
                first = obs["open_now"][0]["id"]
                queue[a] = [first] + [t for t in queue[a] if t != first]
    return calls

def test_ledger_stops_a_team_redoing_done_tasks():
    from netagents.client import LocalEnv
    from netagents.designs import Guarded, Ledger
    from netagents.evaluate import failure_signals
    from worldseeds.net import presets

    def team(ledger):
        raw = presets.build("dag/fixed", opt={"agents": 8, "width": 16, "depth": 4, "grain": 1})
        raw.reset(100)
        env = LocalEnv(raw)
        led = Ledger(env, list(raw.agents)) if ledger else None
        calls = _walk(Guarded(env, led) if ledger else env, raw, 400)
        return raw, calls, led

    plain, plain_calls, _ = team(False)
    led_env, led_calls, led = team(True)
    assert plain.solved and led_env.solved
    sig = failure_signals(plain), failure_signals(led_env)
    # without the ledger every member redoes every task: most submissions are refused as already done
    assert sig[0]["wrong_submissions"] > 300 and sig[0]["duplicate_work"] > 300
    assert sig[1]["wrong_submissions"] == 0 and sig[1]["duplicate_work"] < sig[0]["duplicate_work"] // 4
    assert led_calls < plain_calls // 2 and led_env.actions < plain.actions // 3
    hits = {k: sum(c[k] for c in led.counts.values()) for k in ("done_calls", "done_submits", "taken", "cached")}
    assert hits["done_submits"] == 0 and sum(hits.values()) > 0


def test_ledger_answers_from_the_record_without_an_action():
    from netagents.client import LocalEnv
    from netagents.designs import Guarded, Ledger
    from worldseeds.net import presets

    raw = presets.build("dag/fixed", opt={"agents": 2, "width": 2, "depth": 1, "grain": 1})
    raw.reset(0)
    env = LocalEnv(raw)
    led = Ledger(env, ["a0", "a1"])
    g = Guarded(env, led)
    start = int(raw.tasks["L0.0"].text.split("x = ")[1].split(".")[0])
    v = g.step("a0", "apply", {"task": "L0.0", "x": start})["f(x)"]
    acts = raw.actions
    assert "working on L0.0" in g.step("a1", "apply", {"task": "L0.0", "x": start})["error"]  # a teammate is on it
    again = g.step("a0", "apply", {"task": "L0.0", "x": start})
    assert again["cached"] and again["f(x)"] == v and raw.actions == acts  # a repeat costs nothing
    ok = g.step("a0", "submit", {"task": "L0.0", "artifact": str(v)})
    assert ok["ok"] and [t["id"] for t in ok["open_now"]] == ["L0.1"]
    late = g.step("a1", "submit", {"task": "L0.0", "artifact": str(v)})
    assert not late["ok"] and late["answer"] == str(v) and late["ledger"]
    seen = g.step("a1", "apply", {"task": "L0.0", "x": start})
    assert seen["answer"] == str(v) and "already done by a0" in seen["note"]
    assert led.counts["a1"] == {"done_calls": 1, "done_submits": 1, "taken": 1, "cached": 0}
    assert raw.actions == acts + 1  # only a0's submission reached the environment
    fin = g.step("a1", "apply", {"task": "FINAL", "x": 0})  # the final task opens only when both are done
    assert "f(x)" in fin or "error" in fin
