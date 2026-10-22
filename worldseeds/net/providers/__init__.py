"""Task providers: what the network works on. ``make(name, **options)`` builds one by name."""

from __future__ import annotations

PROVIDERS = {
    "codeworld": ("worldseeds.net.providers.codeworld", "CodeWorldProvider"),
    "math": ("worldseeds.net.providers.math", "MathProvider"),
    "website": ("worldseeds.net.providers.website", "WebsiteProvider"),
    "molecule": ("worldseeds.net.providers.molecule", "MoleculeProvider"),
    "dag": ("worldseeds.net.providers.dag", "DagProvider"),
}


def make(name: str, **options):
    import importlib

    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; known: {sorted(PROVIDERS)}")
    mod, cls = PROVIDERS[name]
    return getattr(importlib.import_module(mod), cls)(**options)
