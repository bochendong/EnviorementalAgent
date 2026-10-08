"""All memories one chain carries across episodes."""

from __future__ import annotations

from ..envs import EnvSpec
from ..memory import OracleSeed, RetrievalMemory, TrajectoryMemory

LIBRARY_CONDITIONS = ("library", "library_flat")
SOURCE_CONDITIONS = (*LIBRARY_CONDITIONS, "testimony")


class Memories:
    """All memories a chain carries across episodes."""

    def __init__(self, condition: str, laws, env: EnvSpec, decay: float = 1.0,
                 source_error: float | None = None, trust: str | None = None):
        self.condition = condition
        self.source_error, self.trust = source_error, trust
        if condition == "testimony" and env.name not in ("town", "board"):
            raise ValueError("condition 'testimony' needs env 'town' or 'board'")
        self.seed = env.seed_cls(decay=decay) if condition in ("seed", "seed_llm") else None
        self.retrieval = RetrievalMemory() if condition == "retrieval" else None
        self.traj = TrajectoryMemory() if condition == "trajectory" else None
        self.oracle = OracleSeed(laws) if condition == "oracle" else None
        # library conditions (town only): memory lives in the world, on shelves the agent must go and read.
        # ``lib_seed`` is the librarian: it consolidates each town's events and rewrites the shelves.
        self.library = self.lib_seed = None
        if condition in LIBRARY_CONDITIONS:
            if env.name not in ("town", "board"):
                raise ValueError(f"condition {condition!r} needs env 'town' or 'board'")
            from ..town.library import LibraryArchive

            self.library = LibraryArchive(mode="flat" if condition == "library_flat" else "categorized")
            self.lib_seed = env.seed_cls(decay=decay)
        self.laws = laws
        self.strategy: str | None = None  # evolve protocol, llm policy: the inherited playbook

    def set_laws(self, laws) -> None:
        self.laws = laws
        if self.oracle is not None:
            self.oracle = OracleSeed(laws)
