"""Where results go: episodes.jsonl, traces.jsonl, hive.jsonl, evolve.jsonl, seeds/."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from ..memory import LawSeed
from .config import ExpConfig


class Recorder:
    def __init__(self, cfg: ExpConfig):
        self.dir = Path(cfg.out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
        self._f = open(self.dir / "episodes.jsonl", "a")
        self._t = open(self.dir / "traces.jsonl", "a") if cfg.save_traces else None
        self._h = open(self.dir / "hive.jsonl", "a") if cfg.protocol == "hive" else None
        self._e = open(self.dir / "evolve.jsonl", "a") if cfg.protocol == "evolve" else None
        self._lock = asyncio.Lock()

    async def write(self, row: dict, trace: list | None = None) -> None:
        async with self._lock:
            if row.get("phase") == "wave":  # hive summaries go to their own file
                self._h.write(json.dumps(row) + "\n")
                self._h.flush()
                return
            if row.get("phase") in ("life", "generation", "transfer"):  # evolve summaries too
                self._e.write(json.dumps(row) + "\n")
                self._e.flush()
                return
            self._f.write(json.dumps(row) + "\n")
            self._f.flush()
            if self._t is not None and trace is not None:
                self._t.write(json.dumps({"key": row["chain"], "episode": row["episode"],
                                          "variant": row.get("variant", ""), "trace": trace}) + "\n")
                self._t.flush()

    def save_seed(self, chain: str, seed: LawSeed) -> None:
        d = self.dir / "seeds"
        d.mkdir(exist_ok=True)
        (d / f"{chain}.json").write_text(json.dumps(seed.to_dict(), indent=1))
