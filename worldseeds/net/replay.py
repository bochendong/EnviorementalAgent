"""Watch a network run in the town: turn a NetworkEnv's event log into a replay for web/codeworld.html.

The replay shows what the environment recorded, whoever the agents were (scripted, LLM, trained): every
operation of every agent becomes a scene in the town of the CodeWorld provider (``theme="town"``):

    study           walk to the machine's workshop, learn its rule
    run             walk to the first machine of the program and try it
    put / get       walk to the library, write a note down / read one ("law/<machine>" keys are rules)
    send            a letter through the post office
    post / board    pin a note on / read the notice board
    claim, submit   take an order, deliver it
    anything else   shown in the log as a tool call

The network charges no walking, so walks are only drawn: they show where an agent went, not what it cost.
The format is the one the page has always read: {"replays": [{"world", "devs", "sprints": [...]}]}; a run
is one sprint.
"""

from __future__ import annotations

import json

from .env import NetworkEnv

LOOKS = [("Rosa", "red"), ("Tomas", "blue"), ("Ivy", "green"), ("Bram", "orange"), ("Lena", "purple"),
         ("Otto", "yellow"), ("Mira", "blue"), ("Finn", "red"), ("Hana", "green"), ("Leo", "purple"),
         ("Clara", "orange"), ("Abe", "yellow")]


def _short(x, n: int = 160) -> str:
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return s if len(s) <= n else s[:n] + "…"


def town_replay(env: NetworkEnv, title: str = "", description: str = "") -> dict:
    """The replay of everything ``env`` has recorded since its reset (CodeWorld provider, town theme)."""
    p = env.provider
    u = getattr(p, "u", None)
    if p.name != "codeworld" or u is None or u.map is None:
        raise ValueError("town replays need the codeworld provider with theme='town'")
    names = list(env.agents)
    owns = {a: list(env.agents[a].role.scope.get("modules", [])) for a in names}
    devs = [{"name": a, "owns": owns[a], "home": owns[a][0] if owns[a] else None, "look": list(LOOKS[i % len(LOOKS)]),
             "role": env.agents[a].role.name} for i, a in enumerate(names)]
    loc = {d["name"]: d["home"] for d in devs}
    working: dict[str, str | None] = {a: None for a in names}
    started: set[str] = set()
    out: list[dict] = []

    def district(a: str) -> int:
        here = loc[a]
        if here and ":" in here:
            return int(here.split(":")[1])
        return u.district_of.get(here, 0) if here else 0

    def emit(a: str, kind: str, budget: int, **kw):
        out.append({"i": len(out), "kind": kind, "dev": a, "loc": loc[a], "budget": budget,
                    "project": working[a], **kw})

    def go(a: str, place: str | None, budget: int):
        if place == loc[a]:
            return
        path = u.route(loc[a], place)
        emit(a, "walk", budget, to=place, frm=loc[a], cost=0, legs=u.map.legs(path), steps=u.map.steps(path),
             remembered=False)
        loc[a] = place

    def start(a: str, task: str, budget: int):
        if task in p.projects and task not in started:
            started.add(task)
            working[a] = task
            emit(a, "start", budget, project=task, text=p.projects[task].text())
        working[a] = task if task in p.projects else working[a]

    world_events = []
    for e in env.events:
        if e["kind"] == "world":
            world_events.append({**e["event"], "sprint": 1})
            continue
        if e["kind"] != "op":
            continue
        a, op, args, obs = e["agent"], e["op"], e.get("args") or {}, e["obs"]
        b, ok = obs.get("budget", 0), obs.get("ok")
        if op == "study" and ok:
            go(a, obs["function"].split(".")[0], b)
            emit(a, "learn", b, fn=obs["function"], law=obs["law"], correct=True, forgot=[])
        elif op == "run" and ok and args.get("program"):
            go(a, args["program"][0].split(".")[0], b)
            emit(a, "tool", b, tool="run", args=args, out=str(obs.get("y")))
        elif op in ("put", "get") and ok:
            go(a, f"library:{district(a)}", b)
            key = args.get("key", "")
            fn = key[4:] if key.startswith("law/") else key
            if op == "put":
                emit(a, "deposit", b, fn=fn)
            else:
                emit(a, "read", b, fn=fn, also=[])
        elif op == "send" and ok:
            for to in obs.get("sent_to", []):
                fn = args.get("data") if isinstance(args.get("data"), str) else _short(args.get("text", ""), 40)
                emit(a, "ask", b, to=to, fn=fn, answered=True, law=_short(args.get("text", "")), also=[], by="post",
                     delay=env.cfg.latency)
        elif op == "post" and ok:
            go(a, f"board:{district(a)}", b)
            emit(a, "post", b, text=_short(args.get("text", ""), 200))
        elif op == "board" and ok:
            go(a, f"board:{district(a)}", b)
            emit(a, "board", b, entries=len(obs.get("posts", [])))
        elif op == "claim" and ok:
            start(a, args.get("task", ""), b)
        elif op == "submit" and args.get("task") in p.projects:
            task = args["task"]
            start(a, task, b)
            emit(a, "submit", b, project=task, program=list(args.get("artifact") or []), ok=bool(ok),
                 tried=env.state[task]["tries"])
            working[a] = None
        else:
            emit(a, "tool", b, tool=op, args=args, out=_short(obs.get("error") or {k: v for k, v in obs.items()
                                                                                     if k not in ("ok", "budget")}))
    for a in names:  # orders still in hand at the end
        if working[a] and env.state[working[a]]["status"] != "done":
            emit(a, "give_up", env.agents[a].budget, reason="the run ended", tried=env.state[working[a]]["tries"])
    projects = []
    for k, (pid, pr) in enumerate(p.projects.items()):
        s = env.state[pid]
        dev = s["by"] or (s["claims"][0] if s["claims"] else names[k % len(names)])
        projects.append({"id": pid, "text": pr.text(), "in": pr.in_type, "out": pr.out_type, "examples": pr.examples,
                         "target": list(pr.target), "dev": dev})
    m = env.metrics()
    budget = env.cfg.budget
    return {"kind": "codeworld", "title": title or f"{len(names)} agents", "description": description,
            "mode": "network", "team": len(names), "capacity": None, "walk": False, "batch": False,
            "board": env.cfg.board, "library": env.cfg.store, "post": env.cfg.messaging,
            "shortcuts": bool(u.map.shortcuts), "money": False, "policy": "network", "budget": budget,
            "world": u.layout(), "goals": [], "devs": devs,
            "sprints": [{"index": 1, "budget": budget, "projects": projects, "start_notebooks": {},
                         "events": out, "metrics": {**m, "projects": len(projects)},
                         "world_events": world_events, "broken": [], "storm": [], "demand": {},
                         "start_coins": {}, "start_rep": {}, "start_treasury": None, "goals": []}]}
