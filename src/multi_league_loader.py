"""
DEPRECATED -- this module now re-exports from ``src.loaders.apisports``.

All classes, constants and functions are preserved for backwards compatibility.
New code should import directly from ``src.loaders`` or ``src.loaders.apisports``.
"""
# Re-export everything from the new location
from src.loaders.apisports import (  # noqa: F401
    MultiLeagueLoader,
    LEAGUES,
    CACHE_DIR,
    API_SPORTS_KEY,
    ODDS_API_KEY,
    BASE_URL,
)

import src.loaders.apisports as _apisports_module  # noqa: F401


def test_loader():
    """Test loader (preserved for backwards compatibility)."""
    loader = MultiLeagueLoader()

    print("\n" + "=" * 60)
    print("TEST: EUROPEAN LEAGUES LOADER")
    print("=" * 60)

    for league_name in ["KHL", "SHL", "Liiga"]:
        games = loader.load_league_data(league_name, n_seasons=1)
        if games:
            print(f"\n{league_name}: {len(games)} games")
            print(f"   Example: {games[0]['away_team']} @ {games[0]['home_team']}")

    print("\nUpcoming games:")
    upcoming = loader.get_all_upcoming(["KHL", "SHL", "Liiga"])
    for game in upcoming[:5]:
        print(f"  {game['league']}: {game['away_team']} @ {game['home_team']}")


def __getattr__(name: str):
    """Proxy attribute lookups to ``src.loaders.apisports`` for backwards compat."""
    import src.loaders.apisports as _mod
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __setattr__(name: str, value) -> None:  # type: ignore[override]
    """Forward attribute patches (e.g. monkeypatch) to the canonical module."""
    import sys
    import src.loaders.apisports as _mod
    sys.modules[__name__].__dict__[name] = value
    if hasattr(_mod, name):
        setattr(_mod, name, value)


if __name__ == "__main__":
    test_loader()
