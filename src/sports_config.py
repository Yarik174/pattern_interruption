"""
Конфигурация видов спорта и лиг для мульти-спортивной системы
"""
from enum import Enum
from typing import Dict, List

class SportType(Enum):
    HOCKEY = 4
    FOOTBALL = 1
    BASKETBALL = 3
    VOLLEYBALL = 12
    TENNIS = 2

SPORTS_CONFIG = {
    SportType.HOCKEY: {
        'name': 'Hockey',
        'name_ru': 'Хоккей',
        'icon': '🏒',
        'sport_id': 4,
        'bet_type': 'winner',
        'leagues': {
            'NHL': {
                'keywords': ['usa: nhl', 'usa. nhl', 'usa-nhl', 'national hockey league', 'nhl '],
                'country': 'USA',
                'priority': 1
            },
            'KHL': {
                'keywords': ['russia: khl', 'russia. khl', 'russia-khl', 'kontinental hockey league', 'khl '],
                'country': 'Russia',
                'priority': 2
            },
            'SHL': {
                'keywords': ['sweden: shl', 'sweden. shl', 'sweden-shl', 'swedish hockey league', ' shl'],
                'country': 'Sweden',
                'priority': 3
            },
            'Liiga': {
                'keywords': ['finland: liiga', 'finland. liiga', 'finland-liiga', 'finnish liiga', 'liiga'],
                'country': 'Finland',
                'priority': 4
            },
            'DEL': {
                'keywords': ['germany: del', 'germany. del', 'germany-del', 'deutsche eishockey liga', ' del'],
                'country': 'Germany',
                'priority': 5
            }
        }
    },
    
    SportType.FOOTBALL: {
        'name': 'Football',
        'name_ru': 'Футбол',
        'icon': '⚽',
        'sport_id': 1,
        'bet_type': 'half_totals',
        'leagues': {
            'EPL': {
                'keywords': ['england: premier league', 'england. premier', 'premier league', 'epl'],
                'exclude_keywords': ['premier league 2', 'u21', 'u23', 'reserve'],
                'country': 'England',
                'priority': 1
            },
            'La Liga': {
                'keywords': ['spain: la liga', 'spain. laliga', 'laliga', 'la liga'],
                'country': 'Spain',
                'priority': 2
            },
            'Bundesliga': {
                'keywords': ['germany: bundesliga', 'germany. bundesliga', '1. bundesliga', 'bundesliga'],
                'country': 'Germany',
                'priority': 3
            },
            'Serie A': {
                'keywords': ['italy: serie a', 'italy. serie a', 'serie a'],
                'country': 'Italy',
                'priority': 4
            },
            'Ligue 1': {
                'keywords': ['france: ligue 1', 'france. ligue 1', 'ligue 1'],
                'country': 'France',
                'priority': 5
            }
        }
    },
    
    SportType.BASKETBALL: {
        'name': 'Basketball',
        'name_ru': 'Баскетбол',
        'icon': '🏀',
        'sport_id': 3,
        'bet_type': 'winner',
        'leagues': {
            'NBA': {
                'keywords': ['usa: nba', 'usa. nba', 'nba', 'national basketball association'],
                'country': 'USA',
                'priority': 1
            },
            'EuroLeague': {
                'keywords': ['europe: euroleague', 'euroleague', 'euro league'],
                'country': 'Europe',
                'priority': 2
            },
            'VTB League': {
                'keywords': ['russia: vtb', 'vtb united', 'vtb league'],
                'country': 'Russia',
                'priority': 3
            },
            'ACB': {
                'keywords': ['spain: acb', 'liga acb', 'acb '],
                'country': 'Spain',
                'priority': 4
            },
            'BBL': {
                'keywords': ['germany: bbl', 'basketball bundesliga', 'bbl '],
                'country': 'Germany',
                'priority': 5
            }
        }
    },
    
    SportType.VOLLEYBALL: {
        'name': 'Volleyball',
        'name_ru': 'Волейбол',
        'icon': '🏐',
        'sport_id': 12,
        'bet_type': 'winner',
        'leagues': {
            'Superliga Russia': {
                'keywords': ['russia: superliga', 'russia. superliga', 'superliga'],
                'country': 'Russia',
                'priority': 1
            },
            'Serie A Italy': {
                'keywords': ['italy: serie a1', 'italy. superlega', 'superlega'],
                'country': 'Italy',
                'priority': 2
            },
            'PlusLiga': {
                'keywords': ['poland: plusliga', 'poland. plusliga', 'plusliga'],
                'country': 'Poland',
                'priority': 3
            },
            'Bundesliga': {
                'keywords': ['germany: volleyball', 'germany. bundesliga', 'vbl'],
                'country': 'Germany',
                'priority': 4
            },
            'CEV Champions': {
                'keywords': ['europe: cev', 'cev champions', 'champions league volleyball'],
                'country': 'Europe',
                'priority': 5
            }
        }
    }
}

def get_sport_config(sport_type: SportType) -> Dict:
    """Получить конфигурацию для вида спорта"""
    return SPORTS_CONFIG.get(sport_type, {})

def get_sport_by_id(sport_id: int) -> SportType:
    """Получить SportType по sport_id"""
    for sport_type in SportType:
        if sport_type.value == sport_id:
            return sport_type
    return SportType.HOCKEY

def get_leagues_for_sport(sport_type: SportType) -> List[str]:
    """Получить список лиг для вида спорта"""
    config = SPORTS_CONFIG.get(sport_type, {})
    return list(config.get('leagues', {}).keys())

def get_all_sports() -> List[Dict]:
    """Получить список всех видов спорта"""
    return [
        {
            'type': sport_type,
            'id': sport_type.value,
            'name': config['name'],
            'name_ru': config['name_ru'],
            'icon': config['icon'],
            'leagues': list(config['leagues'].keys())
        }
        for sport_type, config in SPORTS_CONFIG.items()
    ]

def match_league(league_name: str, sport_type: SportType) -> str:
    """Определить лигу по названию"""
    config = SPORTS_CONFIG.get(sport_type, {})
    league_name_lower = league_name.lower()
    
    for league, league_config in config.get('leagues', {}).items():
        country = league_config.get('country', '').lower()
        excluded = [value.lower() for value in league_config.get('exclude_keywords', [])]
        if any(value in league_name_lower for value in excluded):
            continue
        for keyword in league_config['keywords']:
            keyword_lower = keyword.lower()
            if keyword_lower not in league_name_lower:
                continue

            # Для общих названий вроде "Premier League" или "Bundesliga"
            # требуем совпадение страны, иначе ловим ложные срабатывания
            keyword_is_generic = not any(separator in keyword_lower for separator in (':', '.', '-'))
            if keyword_is_generic and country and country not in league_name_lower:
                continue

            if keyword_lower in league_name_lower:
                return league
    
    return 'Unknown'
