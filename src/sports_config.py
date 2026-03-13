"""
Legacy sports config module -- backwards-compatibility shim.

All sport/league configuration now lives in ``src.config.sports``.
This file re-exports every public name so that existing code like
``from src.sports_config import SportType, match_league`` continues to work.
"""
from typing import Dict, List

# Re-export everything from the canonical locations
from src.config.constants import SportType  # noqa: F401
from src.config.sports import (  # noqa: F401
    SPORTS_CONFIG,
    get_sport_config as _get_sport_config,
    get_sport_by_id,
    get_leagues_for_sport,
    get_all_sports,
    resolve_league,
)


def get_sport_config(sport_type: SportType) -> Dict:
    """Получить конфигурацию для вида спорта (legacy dict format)."""
    return SPORTS_CONFIG.get(sport_type, {})


def match_league(league_name: str, sport_type: SportType) -> str:
    """Определить лигу по названию.

    Delegates to ``src.config.sports.resolve_league`` which is the
    single canonical implementation.
    """
    return resolve_league(league_name, sport_type)
