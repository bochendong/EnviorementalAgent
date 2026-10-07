import json

from worldseeds.town import TownSeed, grow_town
from worldseeds.town.agents import TownOracle
from worldseeds.town.replay import record_policy, replay_trace


def test_record_and_resimulate_trace():
    seed = TownSeed(blocks=("farming", "gifting", "schedule"), surface_seed=4)
    rep = record_policy(seed, "oracle")
    assert rep["success"] and rep["frames"][-1]["state"]["done"]
    json.dumps(rep)  # must be JSON-able for the UI
    # an experiment trace (tool calls) re-simulates to the same end state
    w = grow_town(seed, max_actions=1000)
    TownOracle(w).solve()
    trace = [{"tool": "act", "args": {"verb": e.verb, "target": e.target, "instrument": e.instrument}, "out": e.message}
             for e in w.events if e.verb not in ("night", "see")]
    again = replay_trace(seed.to_dict(), trace)
    assert again["success"]
    assert again["frames"][-1]["state"]["inventory"] == rep["frames"][-1]["state"]["inventory"]
