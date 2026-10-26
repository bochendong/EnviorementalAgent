"""The network environment, its providers and adapters."""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from worldseeds.net import NetConfig, NetworkEnv, OpSpec, Role, Score, Task, TaskProvider, providers


class Toy(TaskProvider):
    """Two tasks: say "a", then (after it) say "b"."""

    name = "toy"

    def reset(self, seed=0):
        self.n = 0
        return {"world": "toy"}

    def roles(self):
        return [Role("worker", "works", ("poke",), 2), Role("watcher", "watches", (), 1)]

    def ops(self):
        return [OpSpec("poke", "count one", cost=2)]

    def apply(self, agent, role, op, args):
        self.n += 1
        return {"n": self.n}

    def tasks(self):
        return [Task("A", "say a"), Task("B", "say b", deps=("A",), final=True, reward=2)]

    def verify(self, task, artifact, agent):
        return Score(artifact == task.id.lower(), 1.0)


def env_(cfg=None, provider=None, seed=0):
    e = NetworkEnv(provider or Toy(), cfg or NetConfig(budget=20))
    e.reset(seed)
    return e


def test_roles_ops_and_costs():
    e = env_()
    assert {a.role.name for a in e.agents.values()} == {"worker", "watcher"} and len(e.agents) == 3
    assert "poke" in [o.name for o in e.ops("a0")] and "poke" not in [o.name for o in e.ops("a2")]
    assert e.step("a2", "poke")["ok"] is False
    obs = e.step("a0", "poke")
    assert obs["n"] == 1 and obs["budget"] == 18
    assert e.step("a0", "status")["budget"] == 18  # free


def test_dag_rewards_credits_and_reputation():
    e = env_(NetConfig(budget=20, team=0.5, bounty=10))
    assert "waits for" in e.step("a0", "submit", {"task": "B", "artifact": "b"})["error"]
    assert not e.step("a0", "submit", {"task": "A", "artifact": "x"})["ok"]
    assert e.step("a0", "submit", {"task": "A", "artifact": "a"})["ok"]
    assert e.step("a1", "submit", {"task": "B", "artifact": "b"})["ok"]
    assert e.solved and e.done
    m = e.metrics()
    assert m["credits"] == {"a0": 10, "a1": 20, "a2": 0}
    # half of each reward is shared by all three
    assert m["reward"]["a2"] == pytest.approx(0.5 * 3 / 3) and m["reward"]["a1"] == pytest.approx(1 + 0.5)
    assert e.agents["a0"].rep == pytest.approx(0.75)


def test_messages_topology_latency():
    e = env_(NetConfig(budget=50, topology="ring", latency=1))
    assert e.agents["a0"].neighbours == ("a1", "a2")
    e = env_(NetConfig(budget=50, topology="star", latency=1))
    assert not e.step("a1", "send", {"to": "a2", "text": "hi"})["ok"]
    assert e.step("a1", "send", {"to": "a0", "text": "hi", "data": [1]})["ok"]
    assert e.step("a0", "inbox")["messages"] == []  # not arrived yet
    for _ in range(3):
        e.step("a2", "wait")
    msgs = e.step("a0", "inbox")["messages"]
    assert msgs and msgs[0]["text"] == "hi" and msgs[0]["data"] == [1]


def test_store_board_market_transfer():
    e = env_(NetConfig(budget=50, market="claim", exclusive=True, store_price=2, credits=3))
    assert e.step("a0", "put", {"key": "k", "value": 1})["version"] == 0
    assert e.step("a0", "put", {"key": "k", "value": 2})["version"] == 1
    got = e.step("a1", "get", {"key": "k", "version": 0})
    assert got["value"] == 1 and got["paid"] == 2 and e.agents["a0"].credits == 5
    assert not e.step("a1", "get", {"key": "k"})["ok"]  # 1 credit left
    assert e.step("a1", "keys")["keys"]["k"]["versions"] == 2
    e.step("a1", "post", {"text": "hello", "tags": ["x"]})
    assert e.step("a2", "board", {"tag": "x"})["posts"][0]["by"] == "a1"
    assert "claim the task first" in e.step("a0", "submit", {"task": "A", "artifact": "a"})["error"]
    assert e.step("a1", "claim", {"task": "A"})["ok"] and not e.step("a0", "claim", {"task": "A"})["ok"]
    assert e.step("a1", "submit", {"task": "A", "key": "nope"})["ok"] is False
    e.step("a1", "put", {"key": "ans", "value": "a"})
    assert e.step("a1", "submit", {"task": "A", "key": "ans"})["ok"]
    assert e.step("a0", "transfer", {"to": "a2", "amount": 5})["ok"] and e.agents["a2"].credits == 8


def test_switches_outage_budget_and_log():
    e = env_(NetConfig(budget=4, messaging=False, board=False, store=False))
    names = {o.name for o in e.ops("a0")}
    assert not names & {"send", "inbox", "post", "board", "put", "get", "claim"}
    assert not e.step("a0", "send", {"to": "a1", "text": "x"})["ok"]
    e.step("a0", "poke")
    e.step("a0", "poke")
    assert e.step("a0", "poke")["error"] == "out of budget"
    e = env_(NetConfig(budget=200, outage=1.0, outage_rounds=1))
    for _ in range(6):
        e.step("a0", "wait")
    assert any(ev["kind"] == "outage" for ev in e.events)
    assert e.events[0]["kind"] == "reset" and all("t" in ev for ev in e.events)


def test_provider_op_clash_is_refused():
    class Bad(Toy):
        def ops(self):
            return [OpSpec("send", "clash")]

    with pytest.raises(ValueError):
        env_(provider=Bad())








def test_math_roles_safety_and_json(tmp_path):
    e = env_(NetConfig(budget=50), providers.make("math"))
    assert not e.step("a0", "simplify", {"expr": "x"})["ok"]  # explorers have no symbolic tools
    assert "not allowed" in e.step("a0", "evaluate", {"expr": "().__class__"})["error"]
    assert e.step("a0", "evaluate", {"expr": "Mod(3**100, 7)"})["value"] == str(pow(3, 100, 7))
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"title": "gauss", "tasks": [
        {"id": "L", "text": "sum 1..n", "answer": "n*(n+1)/2", "vars": ["n"]},
        {"id": "T", "text": "sum 1..100", "answer": "5050", "deps": ["L"]}]}))
    e = env_(NetConfig(budget=50), providers.make("math", problem_file=str(p)))
    assert e.tasks["T"].final
    assert e.step("a2", "submit", {"task": "L", "artifact": "(n**2 + n)/2"})["ok"]
    assert e.step("a2", "submit", {"task": "T", "artifact": "5050"})["ok"] and e.solved


def test_website_sandbox_client_and_task_dir(tmp_path):
    e = env_(NetConfig(budget=60), providers.make("website"))
    assert "called" in e.step("a0", "ask_client", {"question": "What is the shop's name?"})["answer"]
    assert not e.step("a1", "ask_client", {"question": "name?"})["ok"]  # only the PM talks to the client
    e.step("a1", "write", {"path": "tests/test_loop.py", "content": "def test_x():\n    while True: pass\n"})
    obs = e.step("a1", "run_tests", {"path": "tests/test_loop.py"})
    assert "timed out" in obs["failed"][0]["error"] or "CPU" in obs["failed"][0]["error"] or obs["failed"]
    d = tmp_path / "task"
    (d / "starter" / "tests").mkdir(parents=True)
    (d / "hidden").mkdir()
    (d / "starter" / "calc.py").write_text("def add(a, b):\n    return 0\n")
    (d / "hidden" / "test_add.py").write_text("from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n")
    (d / "task.json").write_text(json.dumps({
        "title": "calc", "roles": [{"name": "dev", "write": ["calc.py"], "count": 1}],
        "client": [{"keywords": ["add"], "answer": "add adds"}],
        "features": [{"id": "add", "text": "add works", "tests": "hidden/test_add.py"}]}))
    e = env_(NetConfig(budget=30), providers.make("website", task_dir=str(d)))
    assert not e.step("a0", "submit", {"task": "add"})["ok"]
    e.step("a0", "write", {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"})
    assert e.step("a0", "submit", {"task": "add"})["ok"] and e.step("a0", "submit", {"task": "release"})["ok"]


def test_molecule_needs_made_molecules_and_targets(tmp_path):
    e = env_(NetConfig(budget=60), providers.make("molecule"))
    start = e.info["start"][0]
    assert not e.step("a2", "assay", {"smiles": "CCO"})["ok"]  # never made
    assert not e.step("a0", "assay", {"smiles": start})["ok"]  # chemists do not assay
    prods = e.step("a0", "edit", {"smiles": start, "action": "add_fluoro"})["products"]
    assert prods and e.step("a2", "assay", {"smiles": prods[0]})["ok"]
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"start": ["c1ccccc1O"], "tasks": [{"id": "small", "text": "MW <= 200",
                                                                "need": {"mw": 200}}]}))
    e = env_(NetConfig(budget=20), providers.make("molecule", target_file=str(p)))
    assert e.step("a0", "submit", {"task": "small", "artifact": "Oc1ccccc1"})["ok"]


def test_http_api():
    e = env_(NetConfig(budget=30), providers.make("codeworld"))
    tools = [o.to_openai() for o in e.ops("a0")]
    assert {"submit", "run", "study"} <= {t["function"]["name"] for t in tools}

    from http.server import HTTPServer

    from worldseeds.net.server import make_handler

    srv = HTTPServer(("127.0.0.1", 0), make_handler(e))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req).read())

    try:
        info = json.loads(urllib.request.urlopen(base + "/info").read())
        assert info["provider"] == "codeworld" and info["config"]["budget"] == 30
        assert post("/step", {"agent": "a1", "op": "tasks"})["ok"]
        assert json.loads(urllib.request.urlopen(base + "/ops?agent=a1").read())["tools"]
        assert json.loads(urllib.request.urlopen(base + "/events?since=1").read())["events"]
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- presets, held-out tasks, time
def test_presets_and_variants_build():
    from worldseeds.net.presets import PRESETS, VARIANTS, build, resolve

    for name in PRESETS:
        for var in VARIANTS:
            prov, opt, net = resolve(name, var)
            if var == "solo" and name.endswith(("/medium", "/hard")):
                assert net["deadline"] == PRESETS[name]["net"]["budget"]
            if var == "nonet":
                assert not (net["messaging"] or net["store"] or net["board"])
    e = build("math/medium", "solo")
    e.reset(0)
    team = build("math/medium")
    team.reset(0)
    assert len(e.agents) == 1 and e.agents["a0"].budget == sum(a.budget for a in team.agents.values())
    assert {"simplify", "evaluate"} <= {o.name for o in e.ops("a0")}


def test_deadline_wait_and_outage_cost_time_not_budget():
    e = env_(NetConfig(budget=50, deadline=4))
    assert e.step("a0", "wait")["budget"] == 50
    for _ in range(3 * 4):
        e.step("a1", "wait")
    assert e.late and e.done and "deadline" in e.step("a0", "poke")["error"]
    e = env_(NetConfig(budget=50, outage=1.0, outage_rounds=3))
    for _ in range(3):
        e.step("a2", "wait")
    assert e.agents["a0"].offline and e.step("a0", "poke")["budget"] == 50


def test_heldout_tasks_are_solvable():
    import sys
    from pathlib import Path

    from worldseeds.net.presets import build, seeds

    sys.path.insert(0, str(Path(__file__).parent / "data"))
    from todo_reference import ROUTES, RULES

    e = build("website/heldout-todo")
    e.reset(0)
    assert not e.step("a0", "submit", {"task": "create"})["ok"]
    e.step("a1", "write", {"path": "routes.py", "content": ROUTES})
    e.step("a2", "write", {"path": "rules.py", "content": RULES})
    for t in ("create", "validate", "list", "done", "release"):
        assert e.step("a0", "submit", {"task": t})["ok"], t
    for name in ("math/heldout-number-theory", "math/heldout-combinatorics"):
        e = build(name)
        e.reset(0)
        for tid, t in e.provider.raw.items():
            assert e.step("a2", "submit", {"task": tid, "artifact": t["answer"]})["ok"], (name, tid)
        assert e.solved
    e = build("molecule/heldout-kinase")
    e.reset(seeds("molecule/heldout-kinase")[0])
    need = e.provider.raw[0]["need"]
    assert need["activity"] > e.provider.values(e.info["start"][0])["activity"]



def test_town_replay_shows_what_the_environment_recorded():
    from worldseeds.net.replay import town_replay

    e = NetworkEnv(providers.make("codeworld", theme="town", n_projects=3, drift=0.05),
                   NetConfig(budget=60, latency=1))
    e.reset(0)
    p = e.provider
    fn = sorted(p.u.functions)[0]
    e.step("a0", "study", {"function": fn})
    e.step("a0", "put", {"key": f"law/{fn}", "value": "x"})
    e.step("a1", "get", {"key": f"law/{fn}"})
    e.step("a1", "send", {"to": "a2", "text": "hello"})
    e.step("a2", "post", {"text": "who knows the oven?"})
    t = next(iter(p.projects))
    e.step("a2", "submit", {"task": t, "artifact": list(p.projects[t].target)})
    e.step("a0", "tasks")
    r = town_replay(e, "test")
    kinds = [x["kind"] for x in r["sprints"][0]["events"]]
    for k in ("walk", "learn", "deposit", "read", "ask", "post", "start", "submit", "tool"):
        assert k in kinds, k
    sub = next(x for x in r["sprints"][0]["events"] if x["kind"] == "submit")
    assert sub["ok"] and sub["project"] == t
    assert r["world"]["map"] and len(r["devs"]) == 3 and r["sprints"][0]["metrics"]["done"] == 1
    assert all(w["kind"] == "drift" and "fn" in w for w in r["sprints"][0]["world_events"])
    with pytest.raises(ValueError):
        town_replay(env_())


def test_dag_replay_plays_a_netscale_run_in_the_town():
    from netagents.replays import dag_shape, reference_run
    from worldseeds.net.replay import dag_replay

    ref, events = reference_run(width=4, depth=2, n=2, seed=3, grain=2)
    assert dag_shape(events) == {"width": 4, "depth": 2, "grain": 2}
    r = dag_replay(events, 4, 2, grain=2, reference=ref)
    d, ev = r["dag"], r["sprints"][0]["events"]
    assert d["solved"] and len(d["tasks"]) == 9 and d["rounds"] == ref["rounds"] and d["lower_bound"] == ref["lower_bound"]
    kinds = {x["kind"] for x in ev}
    assert {"walk", "start", "compute", "submit"} <= kinds
    assert all("round" in x for x in ev) and [x["round"] for x in ev] == sorted(x["round"] for x in ev)
    machines = {m["name"]: m for dd in r["world"]["districts"] for w in dd["workshops"] for m in w["machines"]}
    for t in d["tasks"]:  # every task is a machine in the district of its layer
        assert machines[t["fn"]]["task"] == t["id"]
        assert next(dd["index"] for dd in r["world"]["districts"] for w in dd["workshops"]
                    if any(m["name"] == t["fn"] for m in w["machines"])) == t["layer"]
    assert sum(1 for x in ev if x["kind"] == "submit" and x["ok"]) == 9


def test_math_linked_problems_form_one_chain():
    e = env_(NetConfig(budget=80), providers.make("math", problems=["recurrence"] * 3, linked=True, free_roles=True,
                                                  explorers=1, algebraists=0))
    raw = e.provider.raw
    assert raw["P2.L1"]["deps"] == ["P1.T"] and raw["P3.L1"]["deps"] == ["P2.T"] and "FINAL" not in raw
    assert e.tasks["P3.T"].final and not e.tasks["P1.T"].final
    assert "P1.T" in raw["P2.L1"]["text"]
    assert not e.step("a0", "submit", {"task": "P2.L1", "artifact": raw["P2.L1"]["answer"]})["ok"]  # not open
    for t in ("P1.L1", "P1.L2", "P1.T", "P2.L1"):
        assert e.step("a0", "submit", {"task": t, "artifact": raw[t]["answer"]})["ok"], t
    with pytest.raises(ValueError):
        providers.make("math", problems=["sum"], linked=True)


# ---------------------------------------------------------------- El Agente-style mechanisms
def _math(**cfg):
    e = NetworkEnv(providers.make("math", problems=["recurrence"], free_roles=True, explorers=4, algebraists=0),
                   NetConfig(budget=60, **cfg))
    e.reset(0)
    return e


def test_organisation_delegates_down_the_tree():
    e = _math(org=2, org_span=2)
    managers = [a for a in e.agents if a.startswith("m")]
    assert len(managers) == 3 and e.root == managers[-1] and len(e.children[e.root]) == 2
    mid, worker = e.children[e.root][0], e.children[e.children[e.root][0]][0]
    assert set(e.agents[worker].neighbours) == {mid} and e.parent[mid] == e.root
    assert not {o.name for o in e.ops(e.root)} & {"evaluate", "rsolve"}  # managers have no task tools
    assert e.step(worker, "tasks")["tasks"] == []  # a worker sees only what it is given
    assert not e.step(worker, "submit", {"task": "P1.L1", "artifact": "1"})["ok"]
    assert not e.step(mid, "assign", {"task": "P1.L1", "to": worker})["ok"]  # not its to hand out yet
    assert not e.step(e.root, "assign", {"task": "P1.L1", "to": worker})["ok"]  # one level at a time
    assert e.step(e.root, "assign", {"task": "P1.L1", "to": mid})["ok"]
    assert e.step(mid, "assign", {"task": "P1.L1", "to": worker})["ok"]
    assert [t["id"] for t in e.step(worker, "tasks")["tasks"]] == ["P1.L1"]
    ans = e.provider.raw["P1.L1"]["answer"]
    assert e.step(worker, "submit", {"task": "P1.L1", "artifact": ans})["ok"]
    assert not e.step(worker, "send", {"to": e.root, "text": "hi"})["ok"]  # only parent and children


def test_faults_are_silent_until_checked():
    e = _math(faults=1.0)
    r = e.step("a0", "evaluate", {"expr": "2+3"})
    assert r["ok"] and r["value"] != "5" and r["result_id"] == "r0"
    assert e.step("a1", "check", {"result": "r0"})["sound"] is False
    assert e.metrics()["faulty_results"] == 1
    loud = _math(loud_faults=1.0).step("a0", "evaluate", {"expr": "2+3"})
    assert not loud["ok"] and "try again" in loud["error"]
    assert "check" not in {o.name for o in _math().ops("a0")}


def test_provenance_is_recorded_and_can_be_required():
    e = _math()
    ans = e.provider.raw["P1.L1"]["answer"]
    e.step("a0", "submit", {"task": "P1.L1", "artifact": ans})
    assert e.events[-1]["provenance"]["source"] == "none"  # a guess (here: the test knows the answer)
    e = _math(provenance=True)
    assert not e.step("a0", "submit", {"task": "P1.L1", "artifact": ans})["ok"]
    seq = e.step("a1", "sequence", {"rec": e.provider.raw["P1.L1"]["text"].split("a(n+1) = ")[1].split(":")[0]
                                    .replace("a(n)", "a(n)"), "init": e.provider.raw["P1.L1"]["text"]
                                    .split("a(0) = ")[1].split(",")[0], "count": 7})
    assert seq["ok"] and seq["values"][6] == ans
    assert not e.step("a0", "submit", {"task": "P1.L1", "artifact": ans})["ok"]  # a1 computed it, a0 never saw it
    e.step("a1", "send", {"to": "a0", "text": f"a(6) = {ans}"})
    e.step("a0", "inbox")
    assert e.step("a0", "submit", {"task": "P1.L1", "artifact": ans})["ok"]
    assert e.events[-1]["provenance"]["source"] == "received"


def test_report_is_scored_field_by_field():
    e = _math(report=True)
    raw = e.provider.raw
    assert "REPORT" in e.tasks and e.tasks["REPORT"].final
    half = {k: raw[k]["answer"] for k in list(raw)[:2]}
    r = e.step("a0", "submit", {"task": "REPORT", "artifact": half})
    assert not r["ok"] and abs(r["value"] - 2 / 3) < 1e-9 and r["missing"] == [list(raw)[2]]
    assert abs(e.metrics()["report_score"] - 2 / 3) < 1e-9
    for t in raw:
        e.step("a0", "submit", {"task": t, "artifact": raw[t]["answer"]})
    assert not e.solved  # the work is done, the report is not
    assert e.step("a0", "submit", {"task": "REPORT", "artifact": {k: v["answer"] for k, v in raw.items()}})["ok"]
    assert e.solved


def test_hints_only_with_guidance():
    plain = _math().step("a0", "tasks")["tasks"]
    hinted = _math(guidance=1).step("a0", "tasks")["tasks"]
    assert all("hint" not in t["spec"] for t in plain) and all("hint" in t["spec"] for t in hinted)


def test_memory_carries_over_episodes(tmp_path):
    path = str(tmp_path / "m.json")
    e = NetworkEnv(providers.make("math", free_roles=True, explorers=1, algebraists=0),
                   NetConfig(budget=20, memory_file=path))
    e.reset(0)
    assert {"put", "get"} <= {o.name for o in e.ops("a0")}  # a team of one keeps its notebook
    e.step("a0", "put", {"key": "memory/how", "value": "rsolve first"})
    e.step("a0", "put", {"key": "scratch", "value": "gone next time"})
    e.reset(1)
    assert e.step("a0", "get", {"key": "memory/how"})["value"] == "rsolve first"
    assert not e.step("a0", "get", {"key": "scratch"})["ok"]


def test_submit_offers_a_store_key_only_where_there_is_a_store():
    from worldseeds.net.presets import build

    solo = build("compat/math-decomposable", "solo")
    solo.reset(0)
    sub = next(o for o in solo.ops("a0") if o.name == "submit")
    assert set(sub.params) == {"task", "artifact"}
    ans = solo.provider.raw["P1.L1"]["answer"]
    assert solo.step("a0", "submit", {"task": "P1.L1", "artifact": ans, "key": "Q"})["ok"]  # the value wins
    assert "artifact" in solo.step("a0", "submit", {"task": "P1.L2", "store_key": "answer"})["error"]
    team = build("math/medium", "team")
    team.reset(0)
    assert "store_key" in next(o for o in team.ops("a0") if o.name == "submit").params


def test_gen_dag_answers_follow_the_recurrences():
    import random
    import re

    from worldseeds.net.providers.math import gen_dag

    tasks = gen_dag(random.Random(3), width=5, depth=3)
    ans = {t["id"]: int(t["answer"]) for t in tasks}
    for t in tasks:
        if t["id"] == "FINAL":
            assert ans["FINAL"] == sum(ans[d] for d in t["deps"]) % 1009
            continue
        p, q, k, m = map(int, re.search(r"= (\d+)\*a\(n\) \+ (\d+): what is a\((\d+)\) mod (\d+)", t["text"]).groups())
        a = sum(ans[d] for d in t["deps"]) % 10 if t["deps"] else int(re.search(r"a\(0\) = (\d+)", t["text"]).group(1))
        for _ in range(k):
            a = p * a + q
        assert a % m == ans[t["id"]]
        assert all(d.startswith(f"L{t['layer'] - 1}.") for d in t["deps"])


def test_dag_tasks_need_their_hidden_functions():
    from worldseeds.net.presets import build
    from worldseeds.net.providers.dag import hidden

    raw = build("dag/fixed", opt={"agents": 2, "width": 3, "depth": 2, "grain": 3})
    raw.reset(5)
    t = raw.provider.raw["L1.0"]
    x = sum(int(raw.provider.raw[d]["answer"]) for d in t["deps"]) % 1000
    assert t["start"] == x
    xs = [x]
    for _ in range(3):
        xs.append(hidden(5, "L1.0", xs[-1], t["salt"]))
    assert str(xs[-1]) == t["answer"] and len(set(xs)) == 4  # no value repeats: every apply is needed
    o = raw.step("a0", "apply", {"task": "L1.0", "x": [int(raw.provider.raw[d]["answer"]) for d in t["deps"]]})
    assert o["ok"] and o["f(x)"] == hidden(5, "L1.0", t["start"], t["salt"])
    for d in [d for d in raw.provider.raw if d.startswith("L0.")]:
        assert raw.step("a0", "submit", {"task": d, "artifact": raw.provider.raw[d]["answer"]})["ok"]
    bad = raw.step("a1", "submit", {"task": "L1.0", "artifact": f"Mod({t['answer']}, 1000)"})
    assert not bad["ok"] and "whole number" in json.dumps(bad)
    assert raw.provider.raw["FINAL"]["deps"] == ["L1.0", "L1.1", "L1.2"]
