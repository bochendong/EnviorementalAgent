"""Experiment configuration: option groups, flat names, the generated command line."""
import argparse

import pytest

from worldseeds.experiment import ExpConfig, add_arguments, from_args
from worldseeds.experiment.config import HiveOptions, flat_names


def _parse(argv):
    p = argparse.ArgumentParser()
    add_arguments(p)
    return from_args(p.parse_args(argv))


def test_flat_names_fill_the_groups():
    c = ExpConfig(env="board", noise=0.2, hive_modes=["sync"], team_modes=["solo"], n_agents=3,
                  evolve_generations=2, transfer_universes=[5], context="canvas", decay=0.7)
    assert c.world.noise == 0.2 and c.hive.modes == ["sync"] and c.team.modes == ["solo"] and c.team.n_agents == 3
    assert c.evolve.generations == 2 and c.evolve.transfer_universes == [5]
    assert c.llm.context == "canvas" and c.learner.decay == 0.7 and c.env == "board"
    assert ExpConfig(hive=HiveOptions(waves=3)).hive.waves == 3
    with pytest.raises(TypeError):
        ExpConfig(no_such_option=1)
    assert ExpConfig().hive.modes is not ExpConfig().hive.modes  # no shared mutable defaults


def test_command_line_matches_the_config():
    c = _parse(["--env", "board", "--protocol", "hive", "--hive-modes", "sync", "hive_provenance",
                "--hive-faulty", "0.5", "--hive-faulty-mode", "groups", "--noise", "0.1", "--festival", "--roles",
                "--no-evolve-benchmark", "--transfer-universes", "5", "6", "--out", "x", "--zoom-budget", "4"])
    assert c.protocol == "hive" and c.hive.modes == ["sync", "hive_provenance"] and c.hive.faulty == [0.5]
    assert c.world.noise == 0.1 and c.world.festival and c.team.roles and c.world.zoom_budget == 4
    assert not c.evolve.benchmark and c.evolve.transfer_universes == [5, 6] and c.out_dir == "x"
    d = _parse([])
    assert d.to_dict() == ExpConfig().to_dict()  # the command line's defaults are the config's defaults
    assert set(flat_names()) >= {"hive_modes", "team_modes", "n_agents", "roles", "transfer_curve", "noise"}
