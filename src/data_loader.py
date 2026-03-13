"""
DEPRECATED -- this module now re-exports from ``src.loaders.nhl``.

All classes and functions are preserved for backwards compatibility.
New code should import directly from ``src.loaders`` or ``src.loaders.nhl``.
"""
# Re-export everything from the new location
from src.loaders.nhl import NHLDataLoader, DataLoader  # noqa: F401

# Keep module-level references so that monkeypatch / tests that do
# ``monkeypatch.setattr("src.data_loader.requests.get", ...)`` still work.
import requests  # noqa: F401
import time  # noqa: F401
from datetime import datetime  # noqa: F401

import src.loaders.nhl as _nhl_module  # noqa: F401

__all__ = ["NHLDataLoader", "DataLoader"]


def __getattr__(name: str):
    """Proxy attribute lookups to ``src.loaders.nhl`` for backwards compat."""
    import src.loaders.nhl as _mod
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __setattr__(name: str, value) -> None:  # type: ignore[override]
    """Forward attribute patches (e.g. monkeypatch) to the canonical module."""
    import sys
    import src.loaders.nhl as _mod
    # Set on both this wrapper AND the real module so monkeypatches
    # like ``monkeypatch.setattr(data_loader_module, "datetime", ...)``
    # propagate to the code that actually uses the attribute.
    sys.modules[__name__].__dict__[name] = value
    if hasattr(_mod, name):
        setattr(_mod, name, value)
