"""
Автообновление исторических данных для всех лиг
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

LEAGUES_CONFIG = {
    'NHL': {
        'loader': 'nhl',
        'cache_dir': 'data/cache',
        'current_season': '20252026'
    },
    'KHL': {
        'loader': 'multi_league',
        'league_id': 35,
        'cache_dir': 'data/cache/leagues',
        'current_season': 2024
    },
    'SHL': {
        'loader': 'multi_league',
        'league_id': 16,
        'cache_dir': 'data/cache/leagues',
        'current_season': 2024
    },
    'Liiga': {
        'loader': 'multi_league',
        'league_id': 19,
        'cache_dir': 'data/cache/leagues',
        'current_season': 2024
    },
    'DEL': {
        'loader': 'multi_league',
        'league_id': 47,
        'cache_dir': 'data/cache/leagues',
        'current_season': 2024
    }
}

REFRESH_STATE_FILE = 'data/cache/refresh_state.json'


def get_refresh_state() -> Dict:
    """Получить состояние последнего обновления"""
    try:
        if os.path.exists(REFRESH_STATE_FILE):
            with open(REFRESH_STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Error reading refresh state: {e}")
    return {}


def save_refresh_state(state: Dict):
    """Сохранить состояние обновления"""
    try:
        os.makedirs(os.path.dirname(REFRESH_STATE_FILE), exist_ok=True)
        with open(REFRESH_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving refresh state: {e}")


def refresh_nhl_data() -> Dict:
    """Обновить данные NHL через nhle.com API"""
    from src.data_loader import NHLDataLoader
    from src.system_logger import log_data_update
    import pandas as pd
    
    result = {'league': 'NHL', 'success': False, 'matches': 0, 'error': None}
    
    try:
        loader = NHLDataLoader()
        loader.get_all_teams()
        
        current_season = LEAGUES_CONFIG['NHL']['current_season']
        games_df = loader.load_all_data(seasons=[current_season], use_cache=False)
        
        if isinstance(games_df, pd.DataFrame):
            result['matches'] = len(games_df)
        elif isinstance(games_df, list):
            result['matches'] = len(games_df)
        else:
            result['matches'] = 0
            
        result['success'] = True
        
        log_data_update('NHL', result['matches'], True, {'season': current_season})
        logger.info(f"NHL refresh: {result['matches']} matches")
        
    except Exception as e:
        result['error'] = str(e)
        log_data_update('NHL', 0, False, {'error': str(e)})
        logger.error(f"NHL refresh error: {e}")
    
    return result


def refresh_multi_league_data(league_name: str) -> Dict:
    """Обновить данные европейской лиги через API-Sports"""
    from src.system_logger import log_data_update
    
    config = LEAGUES_CONFIG.get(league_name)
    if not config or config['loader'] != 'multi_league':
        return {'league': league_name, 'success': False, 'error': 'Invalid config'}
    
    result = {'league': league_name, 'success': False, 'matches': 0, 'error': None}
    
    try:
        from src.multi_league_loader import MultiLeagueLoader
        
        loader = MultiLeagueLoader()
        games = loader.load_league_data(league_name, n_seasons=1)
        
        result['matches'] = len(games) if games else 0
        result['success'] = True
        
        log_data_update(league_name, result['matches'], True, {
            'n_seasons': 1
        })
        logger.info(f"{league_name} refresh: {result['matches']} matches")
        
    except ImportError:
        result['error'] = 'MultiLeagueLoader not available'
        logger.warning(f"{league_name} refresh skipped: loader not available")
    except Exception as e:
        result['error'] = str(e)
        log_data_update(league_name, 0, False, {'error': str(e)})
        logger.error(f"{league_name} refresh error: {e}")
    
    return result


def refresh_all_historical_data(force: bool = False) -> Dict:
    """
    Обновить исторические данные всех лиг
    
    Args:
        force: Принудительное обновление (игнорировать интервал)
        
    Returns:
        Результат обновления по лигам
    """
    from src.system_logger import log_system
    
    state = get_refresh_state()
    last_refresh = state.get('last_refresh')
    
    if last_refresh and not force:
        last_dt = datetime.fromisoformat(last_refresh)
        if datetime.utcnow() - last_dt < timedelta(hours=20):
            logger.info("Skipping refresh: last update was less than 20 hours ago")
            return {'skipped': True, 'last_refresh': last_refresh}
    
    log_system("Начало обновления исторических данных всех лиг", 'INFO')
    
    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'leagues': {}
    }
    
    results['leagues']['NHL'] = refresh_nhl_data()
    
    for league in ['KHL', 'SHL', 'Liiga', 'DEL']:
        results['leagues'][league] = refresh_multi_league_data(league)
    
    success_count = sum(1 for r in results['leagues'].values() if r.get('success'))
    total_matches = sum(r.get('matches', 0) for r in results['leagues'].values())
    
    state['last_refresh'] = results['timestamp']
    state['last_results'] = results['leagues']
    save_refresh_state(state)
    
    log_system(
        f"Обновление завершено: {success_count}/5 лиг, {total_matches} матчей",
        'INFO',
        {'results': results['leagues']}
    )
    
    return results


def should_refresh() -> bool:
    """Проверить нужно ли обновление"""
    state = get_refresh_state()
    last_refresh = state.get('last_refresh')
    
    if not last_refresh:
        return True
    
    try:
        last_dt = datetime.fromisoformat(last_refresh)
        return datetime.utcnow() - last_dt >= timedelta(hours=20)
    except:
        return True


def get_last_refresh_info() -> Optional[Dict]:
    """Получить информацию о последнем обновлении"""
    state = get_refresh_state()
    if state.get('last_refresh'):
        return {
            'last_refresh': state['last_refresh'],
            'results': state.get('last_results', {})
        }
    return None
