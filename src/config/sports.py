"""
Sport & league configuration registry.

Provides typed dataclasses for sport/league metadata and ONE canonical
function for league resolution (``resolve_league``).

DI NOTES (for other agents):
--------------------------------------------------------------
- ``match_league`` in src/sports_config.py, ``_resolve_sport_type_from_league``
  in src/routes.py, ``infer_sport_type_from_league`` in both app.py and
  src/prediction_service.py all duplicate the same league-lookup logic.
  They should all delegate to ``resolve_league()`` from this module.
- ``_resolve_sport_type`` in src/odds_monitor.AutoMonitor re-invents the
  same mapping; replace with ``infer_sport_type()``.
--------------------------------------------------------------
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.config.constants import SportType, ALL_SPORT_TYPES


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LeagueConfig:
    """Immutable description of a single league."""
    name: str
    keywords: tuple[str, ...]
    country: str
    priority: int
    exclude_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class SportConfig:
    """Immutable description of a sport type and its leagues."""
    sport_type: SportType
    name: str
    name_ru: str
    icon: str
    sport_id: int
    bet_type: str
    leagues: dict[str, LeagueConfig]


# ---------------------------------------------------------------------------
# Registry (single source of truth for league definitions)
# ---------------------------------------------------------------------------
def _build_registry() -> dict[SportType, SportConfig]:
    """Build the sport registry.  Called once at module load time."""
    return {
        SportType.HOCKEY: SportConfig(
            sport_type=SportType.HOCKEY,
            name='Hockey',
            name_ru='\u0425\u043e\u043a\u043a\u0435\u0439',
            icon='\U0001f3d2',
            sport_id=4,
            bet_type='winner',
            leagues={
                'NHL': LeagueConfig(
                    name='NHL',
                    keywords=('usa: nhl', 'usa. nhl', 'usa-nhl', 'national hockey league', 'nhl '),
                    country='USA',
                    priority=1,
                ),
                'KHL': LeagueConfig(
                    name='KHL',
                    keywords=('russia: khl', 'russia. khl', 'russia-khl', 'kontinental hockey league', 'khl '),
                    country='Russia',
                    priority=2,
                ),
                'SHL': LeagueConfig(
                    name='SHL',
                    keywords=('sweden: shl', 'sweden. shl', 'sweden-shl', 'swedish hockey league', ' shl'),
                    country='Sweden',
                    priority=3,
                ),
                'Liiga': LeagueConfig(
                    name='Liiga',
                    keywords=('finland: liiga', 'finland. liiga', 'finland-liiga', 'finnish liiga', 'liiga'),
                    country='Finland',
                    priority=4,
                ),
                'DEL': LeagueConfig(
                    name='DEL',
                    keywords=('germany: del', 'germany. del', 'germany-del', 'deutsche eishockey liga', ' del'),
                    country='Germany',
                    priority=5,
                ),
            },
        ),
        SportType.FOOTBALL: SportConfig(
            sport_type=SportType.FOOTBALL,
            name='Football',
            name_ru='\u0424\u0443\u0442\u0431\u043e\u043b',
            icon='\u26bd',
            sport_id=1,
            bet_type='half_totals',
            leagues={
                'EPL': LeagueConfig(
                    name='EPL',
                    keywords=('england: premier league', 'england. premier', 'premier league', 'epl'),
                    country='England',
                    priority=1,
                    exclude_keywords=('premier league 2', 'u21', 'u23', 'reserve'),
                ),
                'La Liga': LeagueConfig(
                    name='La Liga',
                    keywords=('spain: la liga', 'spain. laliga', 'laliga', 'la liga'),
                    country='Spain',
                    priority=2,
                ),
                'Bundesliga': LeagueConfig(
                    name='Bundesliga',
                    keywords=('germany: bundesliga', 'germany. bundesliga', '1. bundesliga', 'bundesliga'),
                    country='Germany',
                    priority=3,
                ),
                'Serie A': LeagueConfig(
                    name='Serie A',
                    keywords=('italy: serie a', 'italy. serie a', 'serie a'),
                    country='Italy',
                    priority=4,
                ),
                'Ligue 1': LeagueConfig(
                    name='Ligue 1',
                    keywords=('france: ligue 1', 'france. ligue 1', 'ligue 1'),
                    country='France',
                    priority=5,
                ),
            },
        ),
        SportType.BASKETBALL: SportConfig(
            sport_type=SportType.BASKETBALL,
            name='Basketball',
            name_ru='\u0411\u0430\u0441\u043a\u0435\u0442\u0431\u043e\u043b',
            icon='\U0001f3c0',
            sport_id=3,
            bet_type='winner',
            leagues={
                'NBA': LeagueConfig(
                    name='NBA',
                    keywords=('usa: nba', 'usa. nba', 'nba', 'national basketball association'),
                    country='USA',
                    priority=1,
                ),
                'EuroLeague': LeagueConfig(
                    name='EuroLeague',
                    keywords=('europe: euroleague', 'euroleague', 'euro league'),
                    country='Europe',
                    priority=2,
                ),
                'VTB League': LeagueConfig(
                    name='VTB League',
                    keywords=('russia: vtb', 'vtb united', 'vtb league'),
                    country='Russia',
                    priority=3,
                ),
                'ACB': LeagueConfig(
                    name='ACB',
                    keywords=('spain: acb', 'liga acb', 'acb '),
                    country='Spain',
                    priority=4,
                ),
                'BBL': LeagueConfig(
                    name='BBL',
                    keywords=('germany: bbl', 'basketball bundesliga', 'bbl '),
                    country='Germany',
                    priority=5,
                ),
            },
        ),
        SportType.VOLLEYBALL: SportConfig(
            sport_type=SportType.VOLLEYBALL,
            name='Volleyball',
            name_ru='\u0412\u043e\u043b\u0435\u0439\u0431\u043e\u043b',
            icon='\U0001f3d0',
            sport_id=12,
            bet_type='winner',
            leagues={
                'Superliga Russia': LeagueConfig(
                    name='Superliga Russia',
                    keywords=('russia: superliga', 'russia. superliga', 'superliga'),
                    country='Russia',
                    priority=1,
                ),
                'Serie A Italy': LeagueConfig(
                    name='Serie A Italy',
                    keywords=('italy: serie a1', 'italy. superlega', 'superlega'),
                    country='Italy',
                    priority=2,
                ),
                'PlusLiga': LeagueConfig(
                    name='PlusLiga',
                    keywords=('poland: plusliga', 'poland. plusliga', 'plusliga'),
                    country='Poland',
                    priority=3,
                ),
                'Bundesliga': LeagueConfig(
                    name='Bundesliga',
                    keywords=('germany: volleyball', 'germany. bundesliga', 'vbl'),
                    country='Germany',
                    priority=4,
                ),
                'CEV Champions': LeagueConfig(
                    name='CEV Champions',
                    keywords=('europe: cev', 'cev champions', 'champions league volleyball'),
                    country='Europe',
                    priority=5,
                ),
            },
        ),
    }


SPORTS_REGISTRY: dict[SportType, SportConfig] = _build_registry()


# ---------------------------------------------------------------------------
# Public helpers  (canonical, ONE implementation each)
# ---------------------------------------------------------------------------

def get_sport_config(sport_type: SportType) -> SportConfig:
    """Return config for a sport type.  Raises KeyError if unknown."""
    return SPORTS_REGISTRY[sport_type]


def get_sport_by_id(sport_id: int) -> SportType:
    """Return ``SportType`` matching *sport_id* (FlashLive / API-Sports ID)."""
    for st in SportType:
        if st.value == sport_id:
            return st
    return SportType.HOCKEY


def get_leagues_for_sport(sport_type: SportType) -> list[str]:
    """Return league names registered for *sport_type*."""
    cfg = SPORTS_REGISTRY.get(sport_type)
    return list(cfg.leagues.keys()) if cfg else []


def get_all_sports() -> list[dict]:
    """Return a summary list (for UI/API) of all registered sports."""
    return [
        {
            'type': sc.sport_type,
            'id': sc.sport_id,
            'name': sc.name,
            'name_ru': sc.name_ru,
            'icon': sc.icon,
            'leagues': list(sc.leagues.keys()),
        }
        for sc in SPORTS_REGISTRY.values()
    ]


def get_all_league_names() -> set[str]:
    """Return a flat set of every registered league name."""
    return {
        league_name
        for sc in SPORTS_REGISTRY.values()
        for league_name in sc.leagues
    }


# ---------------------------------------------------------------------------
# League matching - THE canonical implementation
# ---------------------------------------------------------------------------

def resolve_league(league_name: str, sport_type: SportType) -> str:
    """Determine the canonical league key from a raw *league_name* string.

    This replaces ALL duplicate implementations across the codebase:
    - ``src/sports_config.match_league``
    - ``src/routes._resolve_sport_type_from_league``  (partially)
    - ``app.infer_sport_type_from_league``  (partially)
    - ``src/prediction_service.infer_sport_type_from_league``  (partially)

    Returns:
        Canonical league key (e.g. ``'NHL'``) or ``'Unknown'``.
    """
    cfg = SPORTS_REGISTRY.get(sport_type)
    if cfg is None:
        return 'Unknown'

    league_lower = league_name.lower()

    for league_key, lc in cfg.leagues.items():
        # Check excludes first
        if any(ex in league_lower for ex in lc.exclude_keywords):
            continue

        for keyword in lc.keywords:
            kw_lower = keyword.lower()
            if kw_lower not in league_lower:
                continue

            # Generic keywords (without : . -) need country match
            is_generic = not any(sep in kw_lower for sep in (':', '.', '-'))
            if is_generic and lc.country and lc.country.lower() not in league_lower:
                continue

            return league_key

    return 'Unknown'


def infer_sport_type(league: Optional[str], default: SportType = SportType.HOCKEY) -> SportType:
    """Determine ``SportType`` from a canonical league key.

    This replaces ALL duplicate implementations:
    - ``src/routes._resolve_sport_type_from_league``
    - ``app.infer_sport_type_from_league``
    - ``src/prediction_service.infer_sport_type_from_league``
    - ``src/odds_monitor.AutoMonitor._resolve_sport_type``  (partially)

    Returns:
        Matching ``SportType`` or *default*.
    """
    if not league:
        return default
    for sport_type in ALL_SPORT_TYPES:
        if league in SPORTS_REGISTRY.get(sport_type, SportConfig(
            sport_type=sport_type, name='', name_ru='', icon='',
            sport_id=0, bet_type='', leagues={},
        )).leagues:
            return sport_type
    return default


def resolve_sport_type(sport, default: Optional[SportType] = SportType.HOCKEY) -> SportType:
    """Convert a string slug, SportType, or None to SportType.

    Replaces ``app.resolve_sport_type``.
    """
    from src.config.constants import SPORT_SLUG_MAP
    if isinstance(sport, SportType):
        return sport
    if sport is None:
        return default  # type: ignore[return-value]
    return SPORT_SLUG_MAP.get(str(sport).strip().lower(), default)  # type: ignore[return-value]


def get_sport_slug(sport_type: SportType) -> str:
    """Return the URL slug for a SportType.  Replaces ``app.get_sport_slug``."""
    from src.config.constants import SPORT_TYPE_TO_SLUG
    return SPORT_TYPE_TO_SLUG.get(sport_type, 'hockey')


# ---------------------------------------------------------------------------
# Legacy-compatible dict export
# (for code that still reads SPORTS_CONFIG[SportType.HOCKEY]['leagues'] etc.)
# ---------------------------------------------------------------------------

def _as_legacy_dict() -> dict:
    """Convert registry to the old SPORTS_CONFIG dict format for backwards compat."""
    result = {}
    for sport_type, sc in SPORTS_REGISTRY.items():
        leagues_dict = {}
        for league_key, lc in sc.leagues.items():
            leagues_dict[league_key] = {
                'keywords': list(lc.keywords),
                'country': lc.country,
                'priority': lc.priority,
            }
            if lc.exclude_keywords:
                leagues_dict[league_key]['exclude_keywords'] = list(lc.exclude_keywords)
        result[sport_type] = {
            'name': sc.name,
            'name_ru': sc.name_ru,
            'icon': sc.icon,
            'sport_id': sc.sport_id,
            'bet_type': sc.bet_type,
            'leagues': leagues_dict,
        }
    return result


SPORTS_CONFIG = _as_legacy_dict()
