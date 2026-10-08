"""Experiment protocols. Each *chain* (universe x condition x variant x repeat) is a sequential stream
of episodes that share one memory; chains run concurrently (vLLM batches the requests).

    config.py     ExpConfig and its option groups (the command line is generated from them)
    runner.py     plays episodes, consolidates memories, records rows
    classic.py    compgen, persistence, law_shift, multiagent, curriculum
    team.py       several agents on one town board (festival, roles)
    hive.py       many agents in parallel worlds sharing one memory
    evolve.py     generations of learners that inherit how to learn
    memories.py   what a chain carries between episodes
    recorder.py   where results go
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .classic import ClassicProtocols
from .config import ExpConfig, add_arguments, from_args
from .evolve import EvolveProtocol
from .hive import HiveProtocol
from .memories import LIBRARY_CONDITIONS, SOURCE_CONDITIONS, Memories
from .recorder import Recorder
from .runner import PROTOCOLS, CoreRunner, _seed
from .team import TeamProtocol

__all__ = ["ExpConfig", "PROTOCOLS", "Runner", "run_experiment", "add_arguments", "from_args", "Memories",
           "Recorder", "LIBRARY_CONDITIONS", "SOURCE_CONDITIONS", "_seed"]


class Runner(CoreRunner, ClassicProtocols, TeamProtocol, HiveProtocol, EvolveProtocol):
    """Runs one experiment configuration."""


def run_experiment(cfg: ExpConfig) -> Path:
    os.makedirs(cfg.out_dir, exist_ok=True)
    return asyncio.run(Runner(cfg).run())
