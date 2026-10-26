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
COLOR_CYCLE = ["red", "blue", "green", "orange", "purple", "yellow"]


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


def dag_replay(events: list[dict], width: int, depth: int, grain: int = 1, fanin: int = 2, title: str = "",
               description: str = "", reference: dict | None = None) -> dict:
    """The replay of a run on the DAG provider (worldseeds/net/providers/dag.py), told in the town: layer k of the
    DAG is district k (the final task has a district of its own), every task a machine there. ``events`` is a
    NetworkEnv's event log, or a saved trace (netagents/evaluate.py save_trace); every scene keeps its lockstep
    round, so the page can play a run round by round. ``reference`` ({"rounds", "lower_bound", ...}, from
    netagents/scaling.py run) is shown against the team's time.

        apply           walk to the task's machine and run it once
        submit          hand the task's answer in
        send            a message to one agent or to everyone ("*")
        inbox           read the messages that came
        put / get       the library (shared store)
        tasks / wait    look at the task list / let a round pass
    """
    import math

    from ..codeworld.world import town_world
    from .providers.dag import gen

    reset = next(e for e in events if e.get("kind") == "reset")
    seed, cfg = reset.get("seed", 0), reset.get("config", {})
    names = list(reset["agents"])
    raw = {t["id"]: t for t in gen(seed, width, depth, fanin, grain)}
    per = max(1, math.ceil(width / 8))
    u = town_world(1, depth + 1, per)
    mods = {d: [m for m in u.modules if u.district_of[m] == d] for d in range(depth + 1)}
    fns = {m: [f.name for f in u.functions.values() if f.module == m] for m in u.modules}
    fn_of, task_of = {}, {}
    for tid, t in raw.items():
        i = 0 if tid == "FINAL" else int(tid.split(".")[1])
        fn_of[tid] = fns[mods[t["layer"]][i // per]][i % per]
        task_of[fn_of[tid]] = tid
    world = u.layout()
    for d in world["districts"]:
        d["name"] = "final" if d["index"] == depth else f"layer {d['index'] + 1}"
        for w in d["workshops"]:
            for m in w["machines"]:
                m["task"] = task_of.get(m["name"])
                m["title"] = m["task"] or "idle"

    devs = [{"name": a, "nick": LOOKS[i % 12][0] + ("" if i < 12 else str(i // 12 + 1)), "owns": [], "home": None,
             "look": [LOOKS[i % 12][0], COLOR_CYCLE[(i % 12 + i // 12) % len(COLOR_CYCLE)]], "role": reset["agents"][a]}
            for i, a in enumerate(names)]
    loc: dict[str, str | None] = {a: None for a in names}
    working: dict[str, str | None] = {a: None for a in names}
    started: set[str] = set()
    done: dict[str, tuple[int, str]] = {}
    out: list[dict] = []

    def emit(a: str, kind: str, rnd: int, budget, **kw):
        out.append({"i": len(out), "kind": kind, "dev": a, "loc": loc[a], "round": rnd, "budget": budget,
                    "project": working[a], **kw})

    def go(a: str, place: str | None, rnd: int, budget):
        if place == loc[a]:
            return
        path = u.route(loc[a], place)
        emit(a, "walk", rnd, budget, to=place, frm=loc[a], cost=0, legs=u.map.legs(path), steps=u.map.steps(path),
             remembered=False)
        loc[a] = place

    def district(a: str) -> int:
        here = loc[a]
        if here and ":" in here:
            return int(here.split(":")[1])
        return u.district_of.get(here, 0) if here else 0

    for e in events:
        if e.get("kind") != "op":
            continue
        a, op, args, obs = e["agent"], e["op"], e.get("args") or {}, e.get("obs") or {}
        r, b, ok = e.get("round", 0), obs.get("budget"), obs.get("ok")
        if op == "apply" and ok and obs.get("task") in raw:
            tid = obs["task"]
            go(a, fn_of[tid].split(".")[0], r, b)
            if working[a] != tid:
                working[a] = tid
                if tid not in started:
                    started.add(tid)
                    emit(a, "start", r, b, project=tid, text=raw[tid]["text"])
            emit(a, "compute", r, b, fn=fn_of[tid], task=tid, x=obs.get("x"), y=obs.get("f(x)"))
        elif op == "submit" and args.get("task") in raw:
            tid = args["task"]
            if ok:
                done.setdefault(tid, (r + 1, a))
            emit(a, "submit", r, b, project=tid, program=[fn_of[tid]], ok=bool(ok), tried=1,
                 answer=_short(args.get("artifact", ""), 20))
            working[a] = None
        elif op == "send" and ok:
            emit(a, "message", r, b, to=list(obs.get("sent_to", [])), text=_short(args.get("text", ""), 400),
                 broadcast=args.get("to") == "*")
        elif op == "inbox" and ok:
            msgs = obs.get("messages", [])
            emit(a, "inbox", r, b, n=len(msgs), frm=sorted({m.get("from", "") for m in msgs}))
        elif op in ("put", "get") and ok:
            go(a, f"library:{district(a)}", r, b)
            emit(a, "deposit" if op == "put" else "read", r, b, fn=args.get("key", ""), also=[])
        elif op == "post" and ok:
            go(a, f"board:{district(a)}", r, b)
            emit(a, "post", r, b, text=_short(args.get("text", ""), 200))
        elif op == "board" and ok:
            go(a, f"board:{district(a)}", r, b)
            emit(a, "board", r, b, entries=len(obs.get("posts", [])))
        elif op == "wait":
            emit(a, "wait", r, b)
        else:
            emit(a, "tool", r, b, tool=op, args=args, out=_short(obs.get("error") or {k: v for k, v in obs.items()
                                                                                         if k not in ("ok", "budget")}))
    rounds = done["FINAL"][0] if "FINAL" in done else max([e["round"] for e in out] + [0]) + 1
    projects = [{"id": tid, "text": t["text"], "in": f"layer {t['layer'] + 1}", "out": "answer", "examples": [],
                 "target": [fn_of[tid]], "dev": done.get(tid, (0, names[0]))[1]} for tid, t in raw.items()]
    n = len(names)
    tasks = width * depth + 1
    dag = {"width": width, "depth": depth, "grain": grain, "fanin": fanin, "seed": seed, "agents": n,
           "tasks": [{"id": tid, "layer": t["layer"], "deps": list(t["deps"]), "fn": fn_of[tid],
                      "final": bool(t.get("final"))} for tid, t in raw.items()],
           "done": {tid: {"round": rr, "by": by} for tid, (rr, by) in done.items()},
           "rounds": rounds, "solved": "FINAL" in done,
           "lower_bound": max(math.ceil(tasks * (grain + 1) / n), (depth + 1) * (grain + 1)),
           "reference": reference}
    budget = cfg.get("budget", 0)
    return {"kind": "codeworld", "title": title or f"{n} agents on a DAG", "description": description,
            "mode": "network", "team": n, "capacity": None, "walk": False, "batch": False,
            "board": cfg.get("board", True), "library": cfg.get("store", True), "post": cfg.get("messaging", True),
            "shortcuts": False, "money": False, "policy": "network", "budget": budget,
            "world": world, "goals": [], "devs": devs, "dag": dag,
            "sprints": [{"index": 1, "budget": budget, "projects": projects, "start_notebooks": {}, "events": out,
                         "metrics": {"done": len(done), "projects": len(projects), "rounds": rounds},
                         "world_events": [], "broken": [], "storm": [], "demand": {}, "start_coins": {},
                         "start_rep": {}, "start_treasury": None, "goals": []}]}
