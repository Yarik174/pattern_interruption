"""
Sport type resolution and NHL team mapping constants.

Extracted from app.py to reduce monolith size.
"""
import os
from typing import Optional

from src.sports_config import SportType, get_leagues_for_sport


SPORT_NAME_MAP = {
    'hockey': SportType.HOCKEY,
    'nhl': SportType.HOCKEY,
    'football': SportType.FOOTBALL,
    'soccer': SportType.FOOTBALL,
    'basketball': SportType.BASKETBALL,
    'volleyball': SportType.VOLLEYBALL,
}

NHL_TEAM_MAPPING = {
    'ANA': ['Anaheim Ducks', 'Ducks'],
    'ARI': ['Arizona Coyotes', 'Coyotes'],
    'BOS': ['Boston Bruins', 'Bruins'],
    'BUF': ['Buffalo Sabres', 'Sabres'],
    'CGY': ['Calgary Flames', 'Flames'],
    'CAR': ['Carolina Hurricanes', 'Hurricanes'],
    'CHI': ['Chicago Blackhawks', 'Blackhawks'],
    'COL': ['Colorado Avalanche', 'Avalanche'],
    'CBJ': ['Columbus Blue Jackets', 'Blue Jackets'],
    'DAL': ['Dallas Stars', 'Stars'],
    'DET': ['Detroit Red Wings', 'Red Wings'],
    'EDM': ['Edmonton Oilers', 'Oilers'],
    'FLA': ['Florida Panthers', 'Panthers'],
    'LAK': ['Los Angeles Kings', 'Kings'],
    'MIN': ['Minnesota Wild', 'Wild'],
    'MTL': ['Montreal Canadiens', 'Canadiens'],
    'NSH': ['Nashville Predators', 'Predators'],
    'NJD': ['New Jersey Devils', 'Devils'],
    'NYI': ['New York Islanders', 'Islanders'],
    'NYR': ['New York Rangers', 'Rangers'],
    'OTT': ['Ottawa Senators', 'Senators'],
    'PHI': ['Philadelphia Flyers', 'Flyers'],
    'PIT': ['Pittsburgh Penguins', 'Penguins'],
    'SJS': ['San Jose Sharks', 'Sharks'],
    'SEA': ['Seattle Kraken', 'Kraken'],
    'STL': ['St Louis Blues', 'St. Louis Blues', 'Blues'],
    'TBL': ['Tampa Bay Lightning', 'Lightning'],
    'TOR': ['Toronto Maple Leafs', 'Maple Leafs'],
    'UTA': ['Utah Hockey Club', 'Utah Mammoth', 'Utah HC'],
    'VAN': ['Vancouver Canucks', 'Canucks'],
    'VGK': ['Vegas Golden Knights', 'Golden Knights'],
    'WSH': ['Washington Capitals', 'Capitals'],
    'WPG': ['Winnipeg Jets', 'Jets'],
}


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def resolve_sport_type(sport, default: Optional[SportType] = SportType.HOCKEY):
    """Преобразовать строку/query param в SportType."""
    if isinstance(sport, SportType):
        return sport
    if sport is None:
        return default
    return SPORT_NAME_MAP.get(str(sport).strip().lower(), default)


def get_sport_slug(sport_type: SportType) -> str:
    """Получить slug вида спорта для API/UI."""
    for slug in ('hockey', 'football', 'basketball', 'volleyball'):
        if SPORT_NAME_MAP[slug] == sport_type:
            return slug
    return 'hockey'


def infer_sport_type_from_league(league: Optional[str]) -> SportType:
    """Определить вид спорта по коду лиги."""
    if not league:
        return SportType.HOCKEY
    for sport_type in (SportType.HOCKEY, SportType.FOOTBALL, SportType.BASKETBALL, SportType.VOLLEYBALL):
        if league in get_leagues_for_sport(sport_type):
            return sport_type
    return SportType.HOCKEY


def get_abbrev_from_full_name(full_name):
    """Конвертировать полное название команды в аббревиатуру."""
    full_name_lower = full_name.lower()
    for abbrev, names in NHL_TEAM_MAPPING.items():
        for name in names:
            if name.lower() in full_name_lower or full_name_lower in name.lower():
                return abbrev
    return None


def build_odds_key(home_team: str, away_team: str, league: Optional[str], sport_type: SportType) -> str:
    """Стабильный ключ матча для odds-ответов."""
    if sport_type == SportType.HOCKEY and league == 'NHL':
        home_abbrev = get_abbrev_from_full_name(home_team)
        away_abbrev = get_abbrev_from_full_name(away_team)
        if home_abbrev and away_abbrev:
            return f"{home_abbrev}_{away_abbrev}"
    return f"{home_team}__{away_team}"


def normalize_flash_match(match: dict, sport_type: SportType) -> dict:
    """Нормализовать live-матч для ответа API."""
    normalized = dict(match)
    normalized['sport'] = get_sport_slug(sport_type)
    normalized['sport_type'] = get_sport_slug(sport_type)
    return normalized
