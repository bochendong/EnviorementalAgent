"""Build browser replays from the actual experiment organisation, without rerunning agents."""
from .replay import LOOKS


def start_replay(org, tags, budget):
    return {"kind": "codeworld", "title": f"Qwen experiment: {tags['variant']} / universe {tags['universe']}",
            "description": "Recorded events from the experiment, including failed actions. See events.jsonl for model dialogue.",
            "mode": org.mode, "policy": "llm", "team": len(org.devs), "capacity": org.devs[0].notebook.capacity,
            "walk": org.walk, "batch": org.batch, "budget": budget, "money": org.econ is not None,
            "board": org.board, "library": org.library, "post": org.post,
            "world": org.u.layout(), "goals": [],
            "devs": [{"name": d.name, "owns": sorted(d.owns), "home": d.home,
                      "look": list(LOOKS[i % len(LOOKS)])} for i, d in enumerate(org.devs)],
            "sprints": []}


def sprint_snapshot(org, projects, goals):
    n = len(org.devs)
    return {"start_notebooks": {d.name: list(d.notebook.laws) for d in org.devs},
            "start_coins": {d.name: d.coins for d in org.devs},
            "start_rep": {d.name: d.rep for d in org.devs}, "start_treasury": org.treasury,
            "projects": [{"id": p.id, "text": p.text(), "in": p.in_type, "out": p.out_type,
                          "examples": p.examples, "target": list(p.target), "dev": org.devs[k % n].name}
                         for k, p in enumerate(projects)],
            "goals": [g.to_dict() for g in goals] if goals else []}
