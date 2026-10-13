"""Agents for the agent network (worldseeds/net). Kept apart from the environment on purpose.

(Not called ``agents``: that is the import name of the OpenAI Agents SDK.)

Agents reach the environment only through its public interface: ``step``, ``ops``, ``observe`` and
``public`` (the problem, who is who, the network's rules). ``client.LocalEnv`` wraps an environment in
this process, ``client.RemoteEnv`` one served over HTTP (``worldseeds.net.server``); every agent here
works with either.

    client.py      LocalEnv / RemoteEnv
    tools.py       OpenAI tools, Agents SDK tools and a neutral briefing, generated from the op specs
    llm.py         model factory (any OpenAI-compatible server, e.g. vLLM with Qwen)
    team.py        an LLM team (every agent concurrently) and a random policy (fuzzing)
    scripted.py    reference teams written for the built-in task generators
    designs.py     published agent designs (ReAct, Reflexion, Kim et al.'s architectures, debate,
                   blackboard, Mixture-of-Agents, MetaGPT) with matched compute
    testset.py     the test suites; evaluate.py runs designs on them (docs/testset.md)
    run.py         command line: run a policy on a preset or provider
    baselines.py   the reference teams on every preset and variant
"""
