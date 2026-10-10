import asyncio
import json
import re
from collections import Counter
from agents.testing import ScriptedModel

from worldseeds.codeworld.tutorial import MACHINES, TutorialConfig, make_sessions, prompt, run, tiny_world


def test_solo_requires_observations_notes_and_checks():
    org, (s,) = make_sessions(11, "solo", 32)
    assert org.u.n_functions == 2 and len(org.u.candidates("wheat", "dough")) == 1
    assert s.submit(list(MACHINES)).startswith("Rejected:")
    for fn in MACHINES:
        for x in (0, 1, 2):
            s.run(fn, x)
        s.remember(fn, org.u.functions[fn].law.describe())
    assert "first use compute" in s.submit(list(MACHINES))
    for x, _ in s.project.examples:
        s.compute(list(MACHINES), x)
    assert s.submit(list(MACHINES)).startswith("Accepted")


def test_pair_private_information_and_questions():
    org, sessions = make_sessions(22, "pair", 32)
    a, b = sessions
    assert set(a.dev.notebook.laws) == {MACHINES[0]}
    assert set(b.dev.notebook.laws) == {MACHINES[1]}
    assert "access only to your own" in a.run(MACHINES[1], 0)
    assert MACHINES[1] not in a.observations
    assert org.u.functions[MACHINES[1]].law.describe() not in prompt(a)
    for s, mate, fn in ((a, b, MACHINES[1]), (b, a, MACHINES[0])):
        assert " is " in s.ask(mate.dev.name, fn)
        for x, _ in s.project.examples:
            s.compute(list(MACHINES), x)
        assert s.submit(list(MACHINES)).startswith("Accepted")
    assert all(s.done == 1 for s in sessions)


class TutorialModel(ScriptedModel):
    """Use real SDK ScriptedModel responses to test the complete pipeline, without network access."""
    def __init__(self, fail=False):
        super().__init__([])
        self.steps = Counter()
        self.fail = fail

    async def get_response(self, *args, **kwargs):
        from agents.testing import ScriptedModel, function_call
        system = kwargs.get("system_instructions", args[0] if args else None)
        messages = kwargs.get("input", args[1] if len(args) > 1 else None)
        actor = int(re.search(r"You are dev(\d+)", system).group(1))
        seed = int(re.search(r"tutorial-(\d+)-", str(messages)).group(1))
        stage = "solo" if "notebook is initially empty" in system else "pair"
        key = (stage, seed, actor)
        n = self.steps[key]
        self.steps[key] += 1
        if self.fail:
            tool, arguments = "remember", {"function": MACHINES[0], "law": "a*x + b"}
        else:
            world = tiny_world(seed)
            calls = []
            if stage == "solo":
                for fn in MACHINES:
                    calls += [("study", {"function": fn}),
                              ("remember", {"function": fn, "law": world.functions[fn].law.describe()})]
            else:
                calls += [("ask", {"teammate": f"dev{1-actor}", "function": MACHINES[1-actor]})]
            calls += [("compute", {"program": list(MACHINES), "x": x}) for x in (2, 7)]
            calls += [("submit", {"program": list(MACHINES)})]
            tool, arguments = calls[n]
        scripted = ScriptedModel([[function_call(tool, arguments, call_id=f"call-{stage}-{seed}-{actor}-{n}")]])
        return await scripted.get_response(*args, **kwargs)


def test_full_tutorial_records_both_stages_and_replays(tmp_path):
    from agents import ModelSettings
    run(TutorialConfig(out_dir=str(tmp_path)), TutorialModel(), ModelSettings())
    rows = [json.loads(x) for x in (tmp_path / "codeworld.jsonl").read_text().splitlines()]
    assert len(rows) == 6 and all(r["passed"] for r in rows)
    assert all(r["asks"] == 2 for r in rows if r["variant"] == "pair")
    replays = json.loads((tmp_path / "replay.json").read_text())["replays"]
    assert len(replays) == 6 and all(r["world"]["theme"] == "town" for r in replays)
    events = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert any(r["kind"] == "llm_start" for r in events)


def test_pair_is_skipped_when_solo_gate_fails(tmp_path):
    from agents import ModelSettings
    run(TutorialConfig(out_dir=str(tmp_path)), TutorialModel(fail=True), ModelSettings())
    rows = [json.loads(x) for x in (tmp_path / "codeworld.jsonl").read_text().splitlines()]
    assert len(rows) == 3 and all(not r["passed"] for r in rows)
    events = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert any(r["kind"] == "stage_skipped" for r in events)
