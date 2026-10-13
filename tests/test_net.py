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
            if var == "solo" and not name.endswith("/easy") and "heldout" not in name:
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

