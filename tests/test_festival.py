"""The festival: a dish cooked from a fresh crop, a visit two farmers make together, private perception, drop."""
from worldseeds.town import TownLaws, TownSeed, grow_town
from worldseeds.world import Obj
from worldseeds.town.team import PERCEIVES, Team, Teammate, run_heuristic_team


def _town(**kw):
    s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming", "gifting"), board=3, days=7, surface_seed=4)
    return grow_town(s, max_actions=400, festival=True, **kw)


def _req(w, kind):
    return next(r for r in w.requests if r["kind"] == kind)


def test_festival_posts_a_dish_and_a_visit_for_two():
    w = _town()
    kinds = [r["kind"] for r in w.requests]
    assert "dish" in kinds and "together" in kinds and len(kinds) == 5
    assert "drop <item>" in w.verbs_text()
    plain = grow_town(TownSeed(laws=TownLaws.from_index(1), blocks=("farming", "gifting"), board=3, surface_seed=4))
    assert len(plain.requests) == 3
    assert "cooked by" in w.board_text()


def test_dish_chain_crop_to_cook_to_requester():
    w = _town()
    d = _req(w, "dish")
    cook, want = w.objs[d["holder"]], w.objs[d["villager"]]
    c = w._add(Obj("c99", "crop", w.town_crops[0], "red", fine={"category": "food"}, location="inv"))
    w.inventory.append(c.id)
    assert not w.request_met(d)[0] and "fresh crop" in w.request_met(d)[1]
    w.agent_room = cook.location
    msg, ok = w.act("give", cook.id, c.id)
    assert ok and "cooks" in msg and d["item"] in w.inventory
    w.agent_room = want.location
    w.act("give", want.id, d["item"])
    assert w.request_met(d)[0]
    msg, ok = w.act("talk", want.id)
    assert d["done"] and ok


def test_together_needs_two_farmers_in_the_room():
    w = _town()
    t = _req(w, "together")
    v = w.objs[t["villager"]]
    assert not w.request_met(t)[0]  # a lone farmer can never do it
    team = Team(w, 2)
    a, b = Teammate(team, 0), Teammate(team, 1)
    a.agent_room = v.location
    assert not w.request_met(t)[0]
    b.agent_room = v.location
    team.activate(0)
    assert w.present(v.location) == 2 and w.request_met(t)[0]


def test_drop_lends_a_tool_to_a_teammate():
    w = _town()
    team = Team(w, 2)
    a, b = Teammate(team, 0), Teammate(team, 1)
    can = next(o for o in w.objs.values() if o.kind == "tool")
    a.act("take", can.id)
    assert "not hold" in b.act("drop", can.id)[0] or not b.act("drop", can.id)[1]
    msg, ok = a.act("drop", can.id)
    assert ok and can.location == "farm"
    assert b.act("take", can.id)[1] and can.id in b.inventory
    assert team.metrics()["drops"] == 1


def test_roles_split_perception():
    w = _town()
    team = Team(w, 3, roles=True)
    farmer, social, merchant = (Teammate(team, i) for i in range(3))
    plot = next(o for o in w.objs.values() if o.kind == "plot")
    vill = next(o for o in w.objs.values() if o.kind == "villager")
    item = next(o for o in w.objs.values() if o.kind == "item")
    assert team.bodies[0].perceives == PERCEIVES["farmer"]
    farmer.focus = ["farm"]
    assert "soil: " + plot.fine["soil"] in farmer.zoom_in(plot.id)
    social.focus = ["farm"]
    assert "cannot tell soils" in social.zoom_in(plot.id)
    assert "soil" not in social.visible_attrs(plot.id) and "soil" in farmer.visible_attrs(plot.id)
    social.seen_fine.add(vill.id)
    merchant.seen_fine.add(vill.id)
    assert social.visible_attrs(vill.id).get("job") == vill.fine["job"]
    assert "job" not in merchant.visible_attrs(vill.id)
    assert "category" in merchant.visible_attrs(item.id) and "category" not in farmer.visible_attrs(item.id)
    assert "socialite" in social.prompt_spec()["notes"]
    # the morning report knows a plot's soil once anyone who can tell soils has looked at it
    assert team.anyone_sees(plot.id, "soil")
    assert not team.anyone_sees(next(o.id for o in w.objs.values() if o.kind == "plot" and o is not plot), "soil")


def test_heuristic_team_works_the_festival():
    w = _town()
    team = Team(w, 3, messages=True, roles=True)
    m = run_heuristic_team(team, [None, None, None], rng_seed=1, messages=True)
    assert m["board_together_done"] == 1
    assert m["board_done"] >= 3 and m["roles"] == ["farmer", "socialite", "merchant"]


def test_oracle_solves_festival_boards():
    from worldseeds.town.agents import TownOracle

    for surf in range(8):
        for team in (False, True):
            w = grow_town(TownSeed(laws=TownLaws.from_index(surf % 3), blocks=("farming", "gifting", "shop"), board=3,
                                   surface_seed=surf), festival=True, max_actions=10_000)
            if team:
                Team(w, 2)
            steps = TownOracle(w).solve()
            assert steps > 0
            together = _req(w, "together")
            assert w.done == team and together["done"] == team  # a lone farmer cannot visit as two
            assert all(r["done"] for r in w.requests if r["kind"] != "together")


def _scripted(testing, calls):
    return testing.ScriptedModel([[testing.function_call("act", c, call_id=f"c{k}")] for k, c in enumerate(calls)])


def test_replays_follow_the_run_exactly():
    import asyncio

    import pytest

    pytest.importorskip("agents")
    testing = pytest.importorskip("agents.testing")
    from agents import ModelSettings

    from worldseeds.agent import run_episode
    from worldseeds.town.replay import record_team, replay_team_trace, replay_trace

    # one agent, drug skin, rainy nights: the replay translates its words back and grows the same world
    seed = TownSeed(laws=TownLaws.from_index(1), blocks=("farming", "gifting"), board=3, surface_seed=4)
    w = grow_town(seed, max_actions=200, festival=True, confounder=True)
    s1 = next(o.id for o in w.objs.values() if o.kind == "seeds")
    p1 = next(o.id for o in w.objs.values() if o.kind == "plot")
    calls = [{"verb": "take", "target": s1}, {"verb": "dose", "target": p1, "instrument": s1},
             {"verb": "go", "target": "atrium"}, {"verb": "go", "target": "lab"}, {"verb": "rest", "target": "cot"},
             {"verb": "wait", "target": ""}]
    m, ctx = asyncio.run(run_episode(w, "none", _scripted(testing, calls), ModelSettings(), max_turns=len(calls),
                                     skin="drug"))
    rep = replay_trace(seed.to_dict(), ctx.trace, max_actions=200, world_opts={"festival": True, "confounder": True},
                       skin="drug")
    last = rep["frames"][-1]["state"]
    assert last["actions"] == m["actions"] == 6 and last["day"] == w.day and rep["skin"]["name"] == "drug"
    assert "weather" in last and last["festival"]

    # a team of two: calls replayed in the order they reached the world, through each teammate's body
    w = grow_town(seed, max_actions=200, festival=True)
    team = Team(w, 2, messages=True, roles=True)
    plan = [[{"verb": "go", "target": "plaza"}, {"verb": "wait", "target": ""}, {"verb": "go", "target": "farm"}],
            [{"verb": "take", "target": s1}, {"verb": "plant", "target": p1, "instrument": s1},
             {"verb": "go", "target": "shop"}]]
    outs = asyncio.run(_team_run(team, plan, testing, ModelSettings(), run_episode))
    traces = [{"agent": team.bodies[i].name, "trace": ctx.trace} for i, (_, ctx) in enumerate(outs)]
    rep = replay_team_trace(seed.to_dict(), traces, max_actions=200, world_opts={"festival": True}, roles=True,
                            messages=True)
    team.save()
    roster = rep["frames"][-1]["state"]["team"]
    assert [b["actions"] for b in roster] == [b.actions for b in team.bodies]
    assert [b["room"] for b in roster] == [b.agent_room for b in team.bodies]
    assert {f["who"] for f in rep["frames"][1:]} == {"Ana", "Bo"}

    demo = record_team(seed, 3, roles=True, festival=True)
    assert demo["frames"] and all("who" in f for f in demo["frames"][1:])


async def _team_run(team, plan, testing, settings, run_episode):
    import asyncio

    return await asyncio.gather(*[run_episode(Teammate(team, i), "none", _scripted(testing, plan[i]), settings,
                                              max_turns=len(plan[i])) for i in range(len(plan))])
