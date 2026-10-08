"""Zoom with a cost: a daily perception budget."""
from worldseeds.town import TownLaws, TownSeed, grow_town
from worldseeds.town.team import Team, Teammate


def _town(**kw):
    s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming", "gifting"), surface_seed=2)
    return grow_town(s, max_actions=200, **kw)


def test_free_by_default():
    w = _town()
    assert w.zoom_budget is None
    plots = [o.id for o in w.objs.values() if o.kind == "plot"]
    for p in plots:
        w.focus = ["farm"]
        assert "soil:" in w.zoom_in(p)
    assert w.perception_spent == 0


def test_budget_spent_and_refilled():
    w = _town(zoom_budget=2)
    plots = [o.id for o in w.objs.values() if o.kind == "plot"]
    seen = []
    for p in plots[:3]:
        w.focus = ["farm"]
        seen.append("soil:" in w.zoom_in(p))
    assert seen == [True, True, False] and w.perception_spent == 2
    w.focus = ["farm"]
    assert "soil:" in w.zoom_in(plots[0])  # looking again at what you already saw is free
    w.act("sleep")
    assert w.zoom_left == 2
    assert "attention left today 2/2" in w.observe()


def test_item_category_is_a_fine_detail_with_a_budget():
    w = _town(zoom_budget=5)
    item = next(o for o in w.objs.values() if o.kind == "item" and o.location in w.rooms)
    assert "category" not in w.visible_attrs(item.id)
    assert f"({item.fine['category']})" not in w._label(item)
    assert "category" in _town().visible_attrs(item.id)


def test_team_bodies_have_their_own_attention():
    w = _town(zoom_budget=1)
    team = Team(w, 2)
    a, b = Teammate(team, 0), Teammate(team, 1)
    plots = [o.id for o in w.objs.values() if o.kind == "plot"]
    a.focus = ["farm"]
    assert "soil:" in a.zoom_in(plots[0])
    a.focus = ["farm"]
    assert "too tired" in a.zoom_in(plots[1])
    b.focus = ["farm"]
    assert "soil:" in b.zoom_in(plots[1])
