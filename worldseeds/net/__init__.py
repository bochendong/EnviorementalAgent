"""A network of agents working on pluggable tasks: the environment, the provider interface, adapters.

    from worldseeds.net import NetworkEnv, NetConfig, providers
    env = NetworkEnv(providers.make("math"), NetConfig(budget=200, latency=1))
    env.reset(seed=0)
    env.step("a0", "tasks", {})

See docs/network.md.
"""

from . import providers
from .core import OpSpec, Role, Score, Task, TaskProvider
from .env import NetConfig, NetworkEnv

__all__ = ["NetworkEnv", "NetConfig", "TaskProvider", "OpSpec", "Role", "Task", "Score", "providers"]
