"""
Автообновление исторических данных для всех лиг
"""
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
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
        'league_id': 47,
        'cache_dir': 'data/cache/leagues',
        'current_season': 2024
    },
    'Liiga': {
        'loader': 'multi_league',
        'league_id': 16,
        'cache_dir': 'data/cache/leagues',
        'current_season': 2024
    },
    'DEL': {
        'loader': 'multi_league',
        'league_id': 19,
        'cache_dir': 'data/cache/leagues',
        'current_season': 2024
    }
}

REFRESH_STATE_FILE = 'data/cache/refresh_state.json'
EURO_HOCKEY_LEAGUES = ('KHL', 'SHL', 'Liiga', 'DEL')


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


def _load_cached_count(cache_file: Path) -> int:
    try:
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
            if isinstance(payload, list):
                return len(payload)
    except Exception:
        return 0
    return 0


def plan_hockey_backfill(
    leagues: Optional[List[str]] = None,
    from_season: Optional[int] = None,
    to_season: Optional[int] = None,
    include_current: bool = True,
) -> Dict:
    """Построить план backfill для европейских хоккейных лиг."""
    from src.multi_league_loader import MultiLeagueLoader

    target_leagues = list(EURO_HOCKEY_LEAGUES if not leagues or 'all' in leagues else leagues)
    loader = MultiLeagueLoader()
    result = {
        'timestamp': datetime.utcnow().isoformat(),
        'mode': 'plan',
        'leagues': {},
        'planned_seasons': {},
    }

    for league in target_leagues:
        config = LEAGUES_CONFIG.get(league)
        if not config or config.get('loader') != 'multi_league':
            result['leagues'][league] = {
                'league_id': None,
                'available_seasons': [],
                'cached_seasons': [],
                'current_season': None,
                'planned_seasons': [],
                'error': 'Invalid config',
            }
            result['planned_seasons'][league] = []
            continue

        league_id = config['league_id']
        available_seasons = sorted({int(season) for season in loader.get_available_seasons(league_id)}, reverse=False)
        cached_seasons = sorted({int(season) for season in loader._get_cached_game_seasons(league_id)}, reverse=False)
        current_season = max(available_seasons) if available_seasons else None

        planned = []
        for season in available_seasons:
            if from_season is not None and season < int(from_season):
                continue
            if to_season is not None and season > int(to_season):
                continue
            if not include_current and current_season is not None and season == current_season:
                continue
            planned.append(season)

        result['leagues'][league] = {
            'league_id': league_id,
            'available_seasons': available_seasons,
            'cached_seasons': cached_seasons,
            'current_season': current_season,
            'planned_seasons': planned,
            'error': None,
        }
        result['planned_seasons'][league] = planned

    return result


def backfill_hockey_history(
    leagues: Optional[List[str]] = None,
    from_season: Optional[int] = None,
    to_season: Optional[int] = None,
    include_current: bool = True,
    refresh_existing_current: bool = False,
    dry_run: bool = False,
) -> Dict:
    """Глубокий backfill исторических сезонов европейского хоккея."""
    from src.cache_catalog import build_cache_manifest, save_manifest
    from src.multi_league_loader import MultiLeagueLoader

    plan = plan_hockey_backfill(
        leagues=leagues,
        from_season=from_season,
        to_season=to_season,
        include_current=include_current,
    )
    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'mode': 'dry-run' if dry_run else 'execute',
        'leagues': {},
        'planned_seasons': {},
        'downloaded_seasons': {},
        'updated_seasons': {},
        'skipped_seasons': {},
        'failed_seasons': {},
        'manifest_generated_at': None,
    }

    for league, info in plan['leagues'].items():
        results['planned_seasons'][league] = list(info.get('planned_seasons', []))
        results['downloaded_seasons'][league] = []
        results['updated_seasons'][league] = []
        results['skipped_seasons'][league] = []
        results['failed_seasons'][league] = []
        results['leagues'][league] = {
            'league_id': info.get('league_id'),
            'current_season': info.get('current_season'),
            'planned_seasons': list(info.get('planned_seasons', [])),
            'downloaded_seasons': results['downloaded_seasons'][league],
            'updated_seasons': results['updated_seasons'][league],
            'skipped_seasons': results['skipped_seasons'][league],
            'failed_seasons': results['failed_seasons'][league],
        }

    if dry_run:
        return results

    loader = MultiLeagueLoader()
    if not getattr(loader, 'api_key', '').strip():
        results['error'] = 'API_SPORTS_KEY not set'
        for league, seasons in results['planned_seasons'].items():
            if seasons:
                results['failed_seasons'][league].append({
                    'season': None,
                    'error': 'API_SPORTS_KEY not set',
                })
        return results

    refreshed_results = {}

    for league, info in plan['leagues'].items():
        if info.get('error'):
            results['failed_seasons'][league].append({'season': None, 'error': info['error']})
            refreshed_results[league] = {
                'league': league,
                'success': False,
                'matches': 0,
                'error': info['error'],
            }
            continue

        changed_matches = 0
        first_error = None
        for season in info.get('planned_seasons', []):
            cache_file = loader.get_games_cache_path(info['league_id'], season)
            cached_before = _load_cached_count(cache_file)
            cache_exists = cache_file.exists()
            is_current = season == info.get('current_season')
            should_refresh = bool(cache_exists and is_current and refresh_existing_current)

            if cache_exists and not should_refresh:
                results['skipped_seasons'][league].append(season)
                continue

            games = loader.get_games(info['league_id'], season, force_refresh=should_refresh)
            cached_after = _load_cached_count(cache_file)

            if cached_after <= 0:
                error = 'No completed games returned'
                if not loader.api_key:
                    error = 'API_SPORTS_KEY not set'
                entry = {'season': season, 'error': error}
                results['failed_seasons'][league].append(entry)
                if first_error is None:
                    first_error = error
                continue

            if cache_exists and should_refresh:
                delta = max(cached_after - cached_before, 0)
                changed_matches += delta
                results['updated_seasons'][league].append({
                    'season': season,
                    'matches': cached_after,
                    'delta': delta,
                })
            else:
                changed_matches += cached_after
                results['downloaded_seasons'][league].append({
                    'season': season,
                    'matches': cached_after,
                })

        refreshed_results[league] = {
            'league': league,
            'success': not results['failed_seasons'][league],
            'matches': changed_matches,
            'error': first_error,
        }

    manifest = build_cache_manifest()
    save_manifest(manifest)
    state = build_refresh_state_from_manifest(
        manifest,
        refreshed_results=refreshed_results,
        timestamp=results['timestamp'],
        source='backfill',
    )
    save_refresh_state(state)
    results['manifest_generated_at'] = manifest.get('generated_at')

    return results


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
        try:
            last_dt = datetime.fromisoformat(last_refresh)
            if datetime.utcnow() - last_dt < timedelta(hours=20):
                logger.info("Skipping refresh: last update was less than 20 hours ago")
                return {'skipped': True, 'last_refresh': last_refresh}
        except (TypeError, ValueError):
            logger.warning("Invalid last_refresh timestamp, forcing refresh")
    
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
    
    from src.cache_catalog import build_cache_manifest, save_manifest

    manifest = build_cache_manifest()
    save_manifest(manifest)
    state = build_refresh_state_from_manifest(
        manifest,
        refreshed_results=results['leagues'],
        timestamp=results['timestamp'],
        source='refresh',
    )
    save_refresh_state(state)
    results['cache_manifest_generated_at'] = manifest.get('generated_at')
    
    log_system(
        f"Обновление завершено: {success_count}/5 лиг, {total_matches} матчей",
        'INFO',
        {'results': results['leagues']}
    )
    
    return results


def build_refresh_state_from_manifest(
    manifest: Dict,
    refreshed_results: Optional[Dict] = None,
    timestamp: Optional[str] = None,
    source: str = 'cache_rebuild',
) -> Dict:
    """Собрать refresh-state из cache manifest и результатов последнего refresh."""
    from src.cache_catalog import get_cache_summary

    summary = get_cache_summary(manifest=manifest)
    refreshed_results = refreshed_results or {}
    state_results = {}

    for league_name in LEAGUES_CONFIG:
        league_summary = summary.get('hockey', {}).get(league_name)
        refresh_result = refreshed_results.get(league_name, {})
        issues = []
        if league_summary:
            issues = list(league_summary.get('issues', []))
        else:
            issues = ['missing from manifest']

        success = refresh_result.get('success')
        if success is None:
            success = bool(league_summary and league_summary.get('status') not in {'corrupt', 'empty'})

        error = refresh_result.get('error')
        if error is None and league_summary and league_summary.get('status') in {'partial', 'corrupt', 'empty'} and issues:
            error = issues[0]

        state_results[league_name] = {
            'league': league_name,
            'sport': 'hockey',
            'success': bool(success),
            'matches': int(league_summary.get('full_cache_matches', 0) if league_summary else 0),
            'refreshed_matches': int(refresh_result.get('matches', 0) or 0),
            'error': error,
            'date_min': league_summary.get('date_min') if league_summary else None,
            'date_max': league_summary.get('date_max') if league_summary else None,
            'source': league_summary.get('source') if league_summary else None,
            'kind': league_summary.get('kind') if league_summary else None,
            'issues_count': len(issues),
        }

    return {
        'last_refresh': timestamp or datetime.utcnow().isoformat(),
        'last_results': state_results,
        'source': source,
        'manifest_generated_at': manifest.get('generated_at'),
    }


def rebuild_refresh_state_from_cache() -> Dict:
    """Пересобрать refresh-state по cache manifest без сетевых запросов."""
    from src.cache_catalog import load_manifest
    from src.system_logger import log_system

    manifest = load_manifest()
    results = build_refresh_state_from_manifest(
        manifest,
        refreshed_results=None,
        timestamp=datetime.utcnow().isoformat(),
        source='cache_rebuild',
    )

    save_refresh_state(results)

    success_count = sum(1 for item in results['last_results'].values() if item.get('success'))
    total_matches = sum(item.get('matches', 0) for item in results['last_results'].values())
    log_system(
        f"Refresh-state rebuilt from cache: {success_count}/{len(results['last_results'])} лиг, {total_matches} матчей",
        'INFO',
        {'results': results['last_results']}
    )

    return {
        'timestamp': results['last_refresh'],
        'source': results['source'],
        'manifest_generated_at': results.get('manifest_generated_at'),
        'leagues': results['last_results'],
    }


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
    last_refresh = state.get('last_refresh')
    if last_refresh:
        info = {
            'last_refresh': last_refresh,
            'results': state.get('last_results', {})
        }
        try:
            last_dt = datetime.fromisoformat(last_refresh)
            hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600
            info['hours_since'] = round(hours_since, 2)
            info['needs_refresh'] = hours_since >= 20
        except (TypeError, ValueError):
            info['hours_since'] = None
            info['needs_refresh'] = True
            info['invalid_timestamp'] = True
        return info
    return None
