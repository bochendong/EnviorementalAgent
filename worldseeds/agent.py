"""The acting agent, built with the OpenAI Agents SDK.

Each episode = one ``Runner.run`` of an ``Agent`` whose tools operate on a ``World``.
Conditions (what memory the agent carries across worlds) map to the baselines of
section 23 of the program seed:

    none        stateless agent                              pi(o_t)
    trajectory  last K episode logs in context               pi(o_t, tau_{1:t})
    retrieval   episodic store + recall() tool               pi(o_t, Retrieve(M, q))
    seed        learned world seed (symbolic) + predict()    Seed + Grow + Zoom + Consolidate
    seed_llm    seed + free-text rules from an LLM consolidator
    oracle      the true laws are given                      upper bound
    library     (town) memory lives on topic shelves in the town library; the agent must walk
                there and read(); it may also leave notes with write_note()
    library_flat  same archive as one unsorted pile, read page by page
    testimony   (town) no memory, but villagers answer act('ask', <villager>) from what their trade
                taught them; with --source-errors some villagers (and library notes) are wrong

View modes: ``zoom`` (hierarchical, lazily grown) vs ``flat`` (everything at full
detail, no zoom tools) for the adaptive-resolution hypothesis H3.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agents import (
    Agent,
    MaxTurnsExceeded,
    RunConfig,
    RunContextWrapper,
    RunHooks,
    Runner,
    ToolsToFinalOutputResult,
    function_tool,
    set_tracing_disabled,
)
from pydantic import BaseModel, Field

from .memory import OracleSeed, RetrievalMemory, SeedMemory, TrajectoryMemory
from .world import World

set_tracing_disabled(True)  # no OpenAI key on Nibi; traces would try to upload

CONDITIONS = ["none", "trajectory", "retrieval", "seed", "seed_llm", "oracle", "library", "library_flat",
              "testimony"]
LIBRARY_CONDITIONS = ("library", "library_flat")
CANVAS_RECENT = 6  # tool-call items kept next to the canvas


@dataclass
class EpisodeCtx:
    world: World
    condition: str
    seed: SeedMemory | None = None
    retrieval: RetrievalMemory | None = None
    tool_calls: int = 0
    observed_chars: int = 0  # text the environment returned to the agent (a proxy for observation tokens)
    predict_calls: int = 0
    recall_calls: int = 0
    trace: list[dict] = field(default_factory=list)
    llm_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _run_usage: tuple[int, int, int] = (0, 0, 0)
    canvas: Any = None  # worldseeds.canvas.Canvas when the context is a canvas instead of a transcript
    strategy: str | None = None  # an inherited playbook (evolve protocol)
    skin: Any = None  # worldseeds.skin.Skin: the same world told as another story (e.g. drug discovery)

    def out(self, text: str) -> str:
        return self.skin.out(text) if self.skin is not None else text

    def back(self, text: str | None) -> str | None:
        return self.skin.back(text) if self.skin is not None else text

    def commit_usage(self) -> None:
        r, i, o = self._run_usage
        self.llm_requests += r
        self.input_tokens += i
        self.output_tokens += o
        self._run_usage = (0, 0, 0)


class _UsageHooks(RunHooks):
    async def on_llm_end(self, context: RunContextWrapper[EpisodeCtx], agent, response) -> None:
        u = context.usage  # cumulative for the current Runner.run call
        context.context._run_usage = (u.requests, u.input_tokens, u.output_tokens)


def _log(ctx: EpisodeCtx, tool: str, args: dict, out: str) -> str:
    out = ctx.out(out)
    ctx.tool_calls += 1
    ctx.observed_chars += len(out)
    ctx.trace.append({"tool": tool, "args": args, "out": out[:2000]})
    return out


# ------------------------------------------------------------------ tools
@function_tool
def observe(ctx: RunContextWrapper[EpisodeCtx]) -> str:
    """Describe what is visible at the current zoom focus (world map, a room, an object or a component)."""
    return _log(ctx.context, "observe", {}, ctx.context.world.observe())


@function_tool
def zoom_in(ctx: RunContextWrapper[EpisodeCtx], target: str) -> str:
    """Zoom one level deeper: map -> location id -> object id -> component id.
    Deeper levels reveal fine details that the coarse view hides. Costs no action.

    Args:
        target: id of a location, object or component visible at the current focus.
    """
    return _log(ctx.context, "zoom_in", {"target": target}, ctx.context.world.zoom_in(ctx.context.back(target)))


@function_tool
def zoom_out(ctx: RunContextWrapper[EpisodeCtx]) -> str:
    """Zoom one level out (component -> object -> location -> map). Costs no action."""
    return _log(ctx.context, "zoom_out", {}, ctx.context.world.zoom_out())


@function_tool
async def act(ctx: RunContextWrapper[EpisodeCtx], verb: str, target: str, instrument: str | None = None) -> str:
    """Perform a physical action where you are standing. Each call uses one action from the budget.

    Args:
        verb: one of the verbs listed in your instructions (e.g. go, take, open, unlock, plant, give).
        target: location id for 'go', otherwise an object or person id shown in your view.
        instrument: id of a held item used as instrument (a key, a tool, seeds, a gift); omit otherwise.
    """
    c = ctx.context
    w = c.world
    msg, _ = w.act(c.back(verb), c.back(target), c.back(instrument))
    if getattr(w, "team", None) is not None and w.asleep:  # in a team: wait in bed for the next morning
        await w.team.wait_morning(w.i)
        msg += "\n" + ("A new day begins.\n" + w.observe() if not w.done else "")
    return _log(ctx.context, "act", {"verb": verb, "target": target, "instrument": instrument}, msg)


@function_tool
def tell(ctx: RunContextWrapper[EpisodeCtx], teammate: str, message: str) -> str:
    """Send a short message to a teammate; they read it with their next observation. Uses one action.

    Args:
        teammate: the teammate's name.
        message: what you want them to know or do (e.g. a law you learned, which request you take on).
    """
    msg, _ = ctx.context.world.tell(teammate, message)
    return _log(ctx.context, "tell", {"teammate": teammate, "message": message}, msg)


@function_tool
def predict(ctx: RunContextWrapper[EpisodeCtx], verb: str, target: str, instrument: str | None = None) -> str:
    """Ask your learned world model what an action would do BEFORE spending an action on it.
    Returns PREDICT SUCCESS/FAIL, or UNCERTAIN plus which object to zoom into. Costs no action.

    Args:
        verb: the action you are considering (e.g. unlock, smash, repair, plant, give, find).
        target: object or person id.
        instrument: key/tool/seeds/gift id, if any.
    """
    c = ctx.context
    c.predict_calls += 1
    out = c.seed.predict(c.world, c.back(verb), c.back(target), c.back(instrument)) if c.seed else \
        "No world model available."
    return _log(c, "predict", {"verb": verb, "target": target, "instrument": instrument}, out)


@function_tool
def recall(ctx: RunContextWrapper[EpisodeCtx], query: str) -> str:
    """Search your memory of past episodes (other worlds) for relevant events. Costs no action.

    Args:
        query: keywords, e.g. 'unlock key lock shape', 'smash jar' or 'give rosa liked'.
    """
    c = ctx.context
    c.recall_calls += 1
    hits = c.retrieval.recall(c.back(query)) if c.retrieval else []
    return _log(c, "recall", {"query": query}, "\n".join(hits) if hits else "(nothing relevant remembered)")


@function_tool
def write_note(ctx: RunContextWrapper[EpisodeCtx], shelf: str, text: str) -> str:
    """Leave a note on a library shelf for whoever comes to this universe's library later
    (including you, in later towns). You must be in the library. Uses one action.

    Args:
        shelf: shelf id shown in the library, e.g. shelf_farming, shelf_gifting, shelf_schedule.
        text: one short, general lesson about the laws (not about this town's ids).
    """
    w = ctx.context.world
    msg, _ = w.act("write", ctx.context.back(shelf), text)
    return _log(ctx.context, "write_note", {"shelf": shelf, "text": text}, msg)


@function_tool
def rewrite_notes(ctx: RunContextWrapper[EpisodeCtx], text: str) -> str:
    """Rewrite your NOTES on the canvas (they replace the old notes; at most 800 characters). Use them for
    plans, open questions and lessons you want to keep in view. Costs no action.

    Args:
        text: the complete new notes.
    """
    c = ctx.context
    out = c.canvas.rewrite_notes(text) if c.canvas is not None else "No canvas in this run."
    return _log(c, "rewrite_notes", {"text": text}, out)


def _stop_when_done(ctx: RunContextWrapper[EpisodeCtx], results) -> ToolsToFinalOutputResult:
    w = ctx.context.world
    if w.done:
        return ToolsToFinalOutputResult(is_final_output=True, final_output="DONE")
    if w.out_of_budget:
        return ToolsToFinalOutputResult(is_final_output=True, final_output="OUT_OF_BUDGET")
    return ToolsToFinalOutputResult(is_final_output=False)


# ------------------------------------------------------------------ prompt
BASE_INSTRUCTIONS = """{intro}
GOAL: {goal}

How the world works:
- The world is hierarchical: {levels}. {view_help}
- Use act(verb, target, instrument) to change the world. Verbs: {verbs}.
  You have {budget} actions; zooming/observing is free but keep it purposeful.
- {notes}
- {laws_hint}

Strategy: think about what stands between you and the goal, gather what you need, and avoid
wasting actions on guesses when you can inspect details first. Before an action whose outcome
you cannot predict, zoom into the objects involved: what you perceive is what you can learn from.
Call one tool at a time. {done_text}
{memory}"""

ZOOM_HELP = ("You start zoomed into your current location. Use zoom_in(id) to inspect details {details} "
             "and zoom_out() to go back up to the map.")
FLAT_HELP = "observe() always shows the map and your location with every detail already expanded."


def build_instructions(ctx: EpisodeCtx, traj: TrajectoryMemory | None, oracle: OracleSeed | None,
                       flat: bool) -> str:
    w = ctx.world
    mem = ""
    c = ctx.condition
    if c in ("seed", "seed_llm") and ctx.seed is not None:
        mem = ("\nWORLD SEED - causal knowledge consolidated from your previous worlds "
               f"({ctx.seed.worlds_seen} worlds). Trust it, but it may be incomplete:\n" + ctx.seed.render() +
               "\nUse predict(verb, target, instrument) to check an action before taking it; if it says "
               "UNCERTAIN, zoom into the object it names.")
    elif c == "oracle" and oracle is not None:
        mem = "\nTRUE LAWS OF THIS UNIVERSE:\n" + oracle.render()
    elif c == "trajectory" and traj is not None:
        mem = "\nLOGS OF YOUR PREVIOUS EPISODES (other worlds, same universe):\n" + traj.render()
    elif c == "retrieval":
        mem = "\nYou have an episodic memory of previous worlds in this universe; query it with recall(query)."
    if getattr(w, "library", None) is not None and getattr(w, "team", None) is not None:
        mem += ("\nTHE LIBRARY (location 'library'): your teammates wrote down what they learned in their earlier "
                "towns, on shelves by topic (farming, gifting, schedule, shop, general). Reading costs an action and "
                "a tick: act('read', <shelf id>).")
    elif getattr(w, "library", None) is not None and c in LIBRARY_CONDITIONS:
        sorted_ = c == "library"
        mem = ("\nTHE LIBRARY: you carry no memory between towns, but this universe has a library (location "
               "'library') holding what was learned in earlier towns"
               + (", sorted onto shelves by topic (farming, gifting, schedule, shop, general). "
                  if sorted_ else ", as one unsorted pile of notes read a page at a time. ")
               + "Reading costs an action and a tick, so read only what your task needs: act('read', <shelf id>). "
               "Notes may be incomplete, and notes by different people may disagree or be wrong. Before you "
               "finish, you may leave a short general lesson with write_note(shelf, text).")
    if getattr(w, "team", None) is not None and w.team.messages:
        mem += ("\nTEAM: work out with your teammates who does which request. You can message a teammate "
                "with tell(teammate, message); it costs an action.")
    if getattr(w, "testimony", None) is not None:
        mem += ("\nVILLAGERS: you carry no memory between towns, but you can ask any villager you meet what "
                "their trade has taught them: act('ask', <villager id>). It costs an action. Not everyone is "
                "right: some villagers are consistently mistaken, so weigh what you hear against what you "
                "see happen.")
    if ctx.canvas is not None:
        mem += ("\nCANVAS MEMORY: you do not see the whole history of this episode. Every step you get a CANVAS "
                "drawn from what you have perceived: where you are in full detail, places you saw recently by name, "
                "older places only in outline, the recent events, and your NOTES. Older detail is still in the "
                "world: go back and look again when you need it. Keep plans, open questions and lessons in your "
                "notes with rewrite_notes(text); it replaces them, so write the full notes each time.")
    if ctx.strategy:
        mem += ("\nPLAYBOOK (how agents before you learned to work in a new town; advice, not law):\n"
                + ctx.strategy)
    p = w.prompt_spec()
    view_help = FLAT_HELP if flat else ZOOM_HELP.format(details=p["details"])
    return ctx.out(BASE_INSTRUCTIONS.format(view_help=view_help, budget=w.max_actions, memory=mem,
                                            **{k: v for k, v in p.items() if k != "details"}))


def build_agent(ctx: EpisodeCtx, model, settings, traj=None, oracle=None, flat: bool = False) -> Agent:
    tools = [observe, act]
    if not flat:
        tools += [zoom_in, zoom_out]
    if ctx.condition in ("seed", "seed_llm"):
        tools.append(predict)
    if ctx.condition == "retrieval":
        tools.append(recall)
    if getattr(ctx.world, "library", None) is not None:
        tools.append(write_note)
    if getattr(ctx.world, "team", None) is not None and ctx.world.team.messages:
        tools.append(tell)
    if ctx.canvas is not None:
        tools.append(rewrite_notes)
    return Agent[EpisodeCtx](
        name="explorer",
        instructions=build_instructions(ctx, traj, oracle, flat),
        tools=tools,
        model=model,
        model_settings=settings,
        tool_use_behavior=_stop_when_done,
        reset_tool_choice=False,  # keep tool_choice="required" for the whole episode
    )


def _trim_history(max_items: int):
    """call_model_input_filter keeping the first message + the last ``max_items`` items.

    Old tool round-trips can be dropped because the *world* keeps the state they
    produced (open doors, held items) and every observation ends with a status line:
    the environment is the agent's memory (H1). The cut never starts on an orphaned
    function_call_output."""

    def f(data):
        items = list(data.model_data.input)
        if max_items <= 0 or len(items) <= max_items + 1:
            return data.model_data
        tail = items[-max_items:]
        while tail and isinstance(tail[0], dict) and tail[0].get("type") == "function_call_output":
            tail = tail[1:]
        note = {"role": "user", "content": "(Older steps were trimmed. The world keeps its state; "
                                           "use observe() or zoom_out() if you need to re-orient.)"}
        data.model_data.input = [items[0], note] + tail
        return data.model_data

    return f


def _canvas_input(recent: int, image: bool = False):
    """call_model_input_filter for canvas memory: the first message, the canvas (redrawn now from what
    the agent has perceived) and only the last ``recent`` items, instead of the long transcript.
    With ``image`` the canvas is rendered into pictures (context as image, worldseeds.render)."""

    def f(data):
        items = list(data.model_data.input)
        tail = items[1:][-recent:] if recent > 0 else []
        while tail and isinstance(tail[0], dict) and tail[0].get("type") == "function_call_output":
            tail = tail[1:]
        canvas = data.context.canvas if data.context is not None else None
        if canvas is None:
            return data.model_data
        text = data.context.out(canvas.render())
        if image:
            from .render import canvas_content

            msg = {"role": "user", "content": canvas_content(data.context.world, text, skin=data.context.skin)}
        else:
            msg = {"role": "user", "content": text}
        data.model_data.input = [items[0], msg] + tail
        return data.model_data

    return f


def _run_config(history_items: int, context: str = "transcript") -> RunConfig:
    flt = _trim_history(history_items) if context == "transcript" else \
        _canvas_input(CANVAS_RECENT, image=(context == "image"))
    wanted = {
        "tracing_disabled": True,
        "call_model_input_filter": flt,
        "tool_not_found_behavior": "return_error_to_model",
    }
    fields = getattr(RunConfig, "__dataclass_fields__", {})
    return RunConfig(**{k: v for k, v in wanted.items() if k in fields})


async def run_episode(
    world: World,
    condition: str,
    model,
    settings,
    *,
    seed: SeedMemory | None = None,
    retrieval: RetrievalMemory | None = None,
    traj: TrajectoryMemory | None = None,
    oracle: OracleSeed | None = None,
    library=None,
    max_turns: int = 80,
    history_items: int = 40,
    max_nudges: int = 3,
    context: str = "transcript",
    canvas_chars: int = 3000,
    skin: str | None = None,
    strategy: str | None = None,
) -> tuple[dict[str, Any], EpisodeCtx]:
    flat = world.eager
    if library is not None and getattr(world, "library", None) is None:
        raise ValueError("library condition: grow the world with library=<LibraryArchive>")
    team = getattr(world, "team", None)
    from .skin import make_skin

    ctx = EpisodeCtx(world=world, condition=condition, seed=seed, retrieval=retrieval, skin=make_skin(skin),
                     strategy=strategy)
    if context in ("canvas", "image"):
        from .canvas import Canvas

        ctx.canvas = Canvas(world, chars=canvas_chars)
    agent = build_agent(ctx, model, settings, traj=traj, oracle=oracle, flat=flat)
    run_input: Any = "Begin. Current view:\n" + ctx.out(world.observe())
    t0 = time.time()
    status, error, nudges, turns_left = "finished", None, 0, max_turns
    hooks, rc = _UsageHooks(), _run_config(history_items, context)
    while True:
        result = None
        try:
            result = await Runner.run(agent, run_input, context=ctx, max_turns=turns_left, hooks=hooks,
                                      run_config=rc)
        except MaxTurnsExceeded:
            status = "max_turns"
        except Exception as e:  # model/server errors should not kill a whole sweep
            status, error = "error", f"{type(e).__name__}: {e}"[:500]
        finally:
            ctx.commit_usage()
        if result is None or world.done or world.out_of_budget or nudges >= max_nudges or (
                team is not None and team.done):
            if result is not None and not world.done and not world.out_of_budget:
                status = "gave_up"
            break
        # The model answered in plain text without finishing: nudge it to keep acting.
        nudges += 1
        turns_left = max(1, turns_left - len([i for i in result.new_items if i.type == "tool_call_item"]) - 1)
        run_input = result.to_input_list() + [{
            "role": "user",
            "content": "The goal is not complete yet. Keep going: call a tool (observe, zoom_in, act ...).",
        }]
    if team is not None:
        team.finish(world.i)
    metrics = {
        "success": world.done,
        "status": status,
        "error": error,
        "nudges": nudges,
        "actions": world.actions,
        "invalid_actions": world.invalid_actions,
        "zoom_ops": world.zoom_ops,
        "nodes_grown": world.nodes_grown,
        "tool_calls": ctx.tool_calls,
        "predict_calls": ctx.predict_calls,
        "recall_calls": ctx.recall_calls,
        "notes_written": sum(1 for t in ctx.trace if t["tool"] == "write_note"),
        "observed_tokens": ctx.observed_chars // 4,
        "context": context,
        "skin": skin or "none",
        **({"canvas_mean_chars": ctx.canvas.rendered_chars // max(1, ctx.canvas.renders),
            "notes_chars": len(ctx.canvas.notes)} if ctx.canvas is not None else {}),
        "llm_requests": ctx.llm_requests,
        "input_tokens": ctx.input_tokens,
        "output_tokens": ctx.output_tokens,
        "wall_s": round(time.time() - t0, 2),
        **(world.board_metrics() if hasattr(world, "board_metrics") else {}),
    }
    return metrics, ctx


# ------------------------------------------------------------------ LLM consolidator
class LawClaim(BaseModel):
    law: str = Field(description="a law id from the list of laws")
    value: str = Field(description="the value you believe this law has (one of the allowed values)")


class RuleBook(BaseModel):
    rules: list[str] = Field(description="At most 12 short, general, causal rules about how this universe works.")
    claims: list[LawClaim] = Field(default_factory=list,
                                   description="For each law you are fairly sure about, its value.")


CONSOLIDATOR_INSTRUCTIONS = """You maintain a compact 'world seed': general causal rules about a universe,
learned across many different worlds. You receive the current rules and the event log of one more
episode. Update the rules: keep rules that are confirmed, revise or delete rules contradicted by the
log, add new general rules supported by the log. Rules must be about laws (e.g. which attribute makes a
key fit a lock), never about specific object ids or rooms of one world. At most 12 rules.
Also list, as claims, the value of each law (from the given list) that the evidence so far supports."""


async def llm_consolidate(seed: SeedMemory, events_text: str, model, settings, skin=None) -> list[str]:
    """Free-text consolidation C(S_t, trajectory) -> S_{t+1} with an LLM (Agents SDK structured output).
    With a ``skin`` the consolidator reads the same story as the agent (law ids and values included) and
    its claims are translated back before they are scored."""
    agent = Agent(name="consolidator", instructions=CONSOLIDATOR_INSTRUCTIONS, model=model,
                  model_settings=settings, output_type=RuleBook)
    laws = "\n".join(f"- {sp}: one of {', '.join(vals)}" for sp, vals in seed.SPACES.items())
    prompt = "CURRENT RULES:\n" + ("\n".join(f"- {r}" for r in seed.rules) or "(none)") + \
             "\n\nLAWS YOU CAN STATE (id: allowed values):\n" + laws + \
             "\n\nEPISODE LOG:\n" + events_text
    if skin is not None:
        prompt = skin.out(prompt)
    back = skin.back if skin is not None else (lambda x: x)
    try:
        res = await Runner.run(agent, prompt, max_turns=2)
        seed.rules = [r.strip() for r in res.final_output.rules][:12]
        # self-written lessons, kept apart from the evidence and scored against the true laws
        seed.reflected = [(back(c.law.strip()), back(c.value.strip())) for c in res.final_output.claims][:64]
    except Exception:
        pass  # keep previous rules on failure
    return seed.rules
