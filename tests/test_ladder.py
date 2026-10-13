"""The ladder from the tutorial to the full town: each level is buildable and solvable by a careful player."""
import json

from worldseeds.codeworld.ladder import LEVELS, LadderConfig, make_case, prompt, run


def _play(s, fns):
    """What a careful player does: learn the rules it may learn (study), ask for the rest, compare chains."""
    for fn in fns:
        if s._private(fn):
            continue
        s.study(fn)
        s.remember(fn, s.u.functions[fn].law.describe().replace(" (mod 101)", ""))


def test_levels_build_and_say_what_is_new():
    assert [lv.n for lv in LEVELS] == [1, 2, 3, 4, 5, 6]
    for lv in LEVELS:
        org, sessions, orders, _ = make_case(11, lv)
        assert len(sessions) == lv.players and len(orders) == lv.players * lv.orders
        assert all(org.u.type_checks(p.target, p.in_type, p.out_type) for p in orders)
        assert lv.hint and lv.hint[:20] in prompt(sessions[0])
    org, (s,), orders, _ = make_case(22, LEVELS[1])
    assert orders[0].n_candidates == 4  # level 2: four chains fit, the examples single one out
    assert sum(f.law.kind == "branch" for f in make_case(22, LEVELS[2])[0].u.functions.values()) == 4


def test_levels_two_to_four_are_solvable():
    for lv in LEVELS[1:4]:
        org, sessions, orders, _ = make_case(33, lv)
        for s in sessions:  # masters learn their own machines first
            _play(s, sorted(org.u.functions))
        for s in sessions:
            p = s.project
            for fn in sorted({fn for c in org.u.candidates(p.in_type, p.out_type) for fn in c}):
                if s._private(fn):
                    master = next(d for d in org.devs if org.u.functions[fn].module in d.owns)
                    assert " is " in s.ask(master.name, fn)
            fit = [c for c in org.u.candidates(p.in_type, p.out_type)
                   if all(org.u.run(c, x) == y for x, y in p.examples)]
            assert s.submit(list(fit[0])).startswith("Accepted"), lv.name
        if lv.private:
            assert "another master" in sessions[0].run(next(fn for fn in org.u.functions if sessions[0]._private(fn)), 1)


def test_ladder_records_and_stops_at_the_first_failing_level(tmp_path):
    from agents import ModelSettings
    from agents.testing import ScriptedModel, assistant_message

    idle = ScriptedModel([[assistant_message("I will think about it.")]] * 60)  # never acts: level 1 fails
    out = run(LadderConfig(seeds=(11, 22, 33), levels=(1, 2), out_dir=str(tmp_path / "l")), idle, ModelSettings())
    summary = json.loads((out / "summary.json").read_text())
    assert [x["level"] for x in summary] == [1] and not summary[0]["climbed"]
    rows = [json.loads(x) for x in (out / "codeworld.jsonl").read_text().splitlines()]
    assert len(rows) == 3 and all(not r["passed"] for r in rows)
    assert json.loads((out / "replay.json").read_text())["replays"]


def test_ladder_calculator_is_optional_and_records_actual_usage(tmp_path):
    from agents import ModelSettings
    from agents.testing import ScriptedModel, function_call
    _, _, orders, _ = make_case(11, LEVELS[0])
    model = ScriptedModel([
        [function_call('calculate', {'expression': '(53-69)%101'}, call_id='c1')],
        [function_call('submit', {'program': list(orders[0].target)}, call_id='c2')],
    ])
    out = run(LadderConfig(seeds=(11,), levels=(1,), out_dir=str(tmp_path), calculator=True),
              model, ModelSettings())
    row = json.loads((out / 'codeworld.jsonl').read_text())
    assert row['done'] == 1 and row['tool_calls']['calculate'] == 1
    events = [json.loads(line) for line in (out / 'events.jsonl').read_text().splitlines()]
    feedback = next(r for r in events if r['kind'] == 'tool_result' and r['tool'] == 'calculate')
    assert feedback['out'] == '(53-69)%101 = 85'
    assert feedback['budget_after'] == LEVELS[0].budget
    assert LadderConfig().calculator is False
