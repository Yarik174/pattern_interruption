"""
Фоновый мониторинг коэффициентов и генерация прогнозов
С автозапуском и логированием в БД
"""
from collections import Counter
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Callable
import os
import atexit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_global_monitor = None
_monitor_thread_started = False
_guard = None


class OddsMonitor:
    """Фоновый мониторинг коэффициентов
    
    ОПТИМИЗАЦИЯ для 100 запросов/день:
    - Интервал 2 часа вместо 5 минут
    - Кэширование в odds_loader
    - Не запускается автоматически
    """
    
    def __init__(self, 
                 odds_loader,
                 prediction_callback: Callable,
                 notification_callback: Optional[Callable] = None,
                 check_interval: int = 7200):  # 2 часа вместо 5 минут
        """
        Args:
            odds_loader: Загрузчик коэффициентов (APISportsOddsLoader)
            prediction_callback: Функция генерации прогноза (match_data) -> prediction
            notification_callback: Функция отправки уведомления (prediction) -> bool
            check_interval: Интервал проверки в секундах (default: 5 минут)
        """
        self.odds_loader = odds_loader
        self.prediction_callback = prediction_callback
        self.notification_callback = notification_callback
        self.check_interval = check_interval
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_events = set()
        self._last_check = None
        self._stats = {
            'total_checks': 0,
            'matches_found': 0,
            'predictions_created': 0,
            'notifications_sent': 0,
            'errors': 0
        }
    
    def start(self):
        """Запустить мониторинг"""
        if self._running:
            logger.warning("Monitor already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"Odds monitor started (interval: {self.check_interval}s)")
    
    def stop(self):
        """Остановить мониторинг"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Odds monitor stopped")
    
    def is_running(self) -> bool:
        """Статус мониторинга"""
        return self._running
    
    def get_stats(self) -> dict:
        """Получить статистику"""
        return {
            **self._stats,
            'is_running': self._running,
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'processed_events': len(self._processed_events)
        }
    
    def check_now(self) -> dict:
        """Выполнить проверку сейчас"""
        return self._check_odds()
    
    def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                self._check_odds()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                self._stats['errors'] += 1
            
            time.sleep(self.check_interval)
    
    def _check_odds(self) -> dict:
        """Проверить коэффициенты и создать прогнозы"""
        self._last_check = datetime.utcnow()
        self._stats['total_checks'] += 1
        
        result = {
            'timestamp': self._last_check.isoformat(),
            'matches_found': 0,
            'new_predictions': 0,
            'notifications_sent': 0
        }
        
        try:
            if hasattr(self.odds_loader, 'get_matches_with_odds'):
                matches = self.odds_loader.get_matches_with_odds(days_ahead=2)
            else:
                matches = self.odds_loader.get_upcoming_games(days_ahead=2)
            result['matches_found'] = len(matches)
            self._stats['matches_found'] += len(matches)
            
            for match in matches:
                event_id = match.get('event_id')
                
                if event_id and event_id in self._processed_events:
                    continue
                
                try:
                    prediction = self.prediction_callback(match)
                    
                    if prediction:
                        result['new_predictions'] += 1
                        self._stats['predictions_created'] += 1
                        
                        if event_id:
                            self._processed_events.add(event_id)
                        
                        if self.notification_callback:
                            if self.notification_callback(prediction):
                                result['notifications_sent'] += 1
                                self._stats['notifications_sent'] += 1
                                
                except Exception as e:
                    logger.error(f"Error processing match {match.get('home_team')} vs {match.get('away_team')}: {e}")
            
            logger.info(f"Check complete: {result['matches_found']} matches, {result['new_predictions']} new predictions")
            
        except Exception as e:
            logger.error(f"Error checking odds: {e}")
            result['error'] = str(e)
            self._stats['errors'] += 1
        
        return result
    
    def clear_processed(self, older_than_hours: int = 48):
        """Очистить старые обработанные события"""
        old_count = len(self._processed_events)
        self._processed_events.clear()
        logger.info(f"Cleared {old_count} processed events")


class AutoMonitor:
    """
    Автоматический мониторинг с:
    - Проверкой матчей каждые 4 часа
    - Обновлением исторических данных раз в день
    - Логированием в БД
    """
    
    def __init__(self, check_interval: int = 43200, dry_run: bool = False):  # 12 часов вместо 4
        self.check_interval = check_interval
        self.dry_run = dry_run
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_check = None
        self._last_data_refresh = None
        self._history_context: Dict[tuple[str, str], Dict[str, Any]] = {}
        self._stats = {
            'total_checks': 0,
            'matches_found': 0,
            'predictions_created': 0,
            'notifications_sent': 0,
            'data_refreshes': 0,
            'errors': 0,
            'dry_run_candidates': 0,
            'shadow_logged': 0,
            'shadow_only': 0,
            'rejected_matches': 0,
        }
    
    def start(self):
        """Запустить автомониторинг"""
        if self._running:
            logger.warning("AutoMonitor already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()
        logger.info(f"AutoMonitor started (interval: {self.check_interval}s = {self.check_interval // 3600}h)")
    
    def stop(self):
        """Остановить мониторинг"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("AutoMonitor stopped")
    
    def is_running(self) -> bool:
        return self._running
    
    def get_stats(self) -> dict:
        return {
            **self._stats,
            'is_running': self._running,
            'dry_run': self.dry_run,
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'last_data_refresh': self._last_data_refresh.isoformat() if self._last_data_refresh else None,
            'check_interval_hours': self.check_interval // 3600
        }
    
    def _main_loop(self):
        """Основной цикл"""
        time.sleep(10)
        
        while self._running:
            try:
                self._maybe_refresh_data()
                self._check_matches()
            except Exception as e:
                logger.error(f"AutoMonitor error: {e}")
                self._stats['errors'] += 1
                self._log_error(str(e))
            
            time.sleep(self.check_interval)
    
    def _maybe_refresh_data(self):
        """Обновить исторические данные если нужно"""
        if self.dry_run:
            return
        try:
            from src.data_refresh import should_refresh, refresh_all_historical_data
            
            if should_refresh():
                logger.info("AutoMonitor: refreshing historical data...")
                result = refresh_all_historical_data()
                if not result.get('skipped'):
                    self._last_data_refresh = datetime.utcnow()
                    self._stats['data_refreshes'] += 1
        except ImportError as e:
            logger.warning(f"Data refresh module not available: {e}")
        except Exception as e:
            logger.error(f"Data refresh error: {e}")
    
    def _check_matches(self):
        """Проверить матчи и создать прогнозы"""
        from src.system_logger import log_monitoring
        
        self._last_check = datetime.utcnow()
        self._stats['total_checks'] += 1
        
        result = {
            'matches_found': 0,
            'predictions_created': 0,
            'notifications_sent': 0,
            'decision_breakdown': {
                'candidate': 0,
                'shadow_only': 0,
                'rejected': 0,
            },
        }
        if self.dry_run:
            result['dry_run'] = True
            result['decisions'] = []
        
        try:
            loader = self._get_live_loader()
            if not loader.is_configured():
                logger.warning("FlashLive not configured, skipping check")
                return result
            
            matches = loader.get_matches_with_odds(days_ahead=2)
            result['matches_found'] = len(matches)
            self._stats['matches_found'] += len(matches)
            
            for match in matches:
                try:
                    decision = self.evaluate_match(match)
                    self._log_match_decision(decision)
                    result['decision_breakdown'][decision['status']] += 1

                    if decision['status'] == 'shadow_only':
                        self._stats['shadow_only'] += 1
                    elif decision['status'] == 'rejected':
                        self._stats['rejected_matches'] += 1

                    if self.dry_run:
                        result['decisions'].append(decision)
                        if decision['status'] == 'candidate':
                            result['predictions_created'] += 1
                            self._stats['predictions_created'] += 1
                            self._stats['dry_run_candidates'] += 1
                        continue

                    prediction = self._process_match(match, decision=decision)
                    if prediction:
                        result['predictions_created'] += 1
                        self._stats['predictions_created'] += 1
                        
                        if self._send_notification(prediction):
                            result['notifications_sent'] += 1
                            self._stats['notifications_sent'] += 1
                except Exception as e:
                    logger.error(f"Error processing match: {e}")
            
            log_monitoring(
                result['matches_found'],
                result['predictions_created'],
                result['notifications_sent'],
                details={'decision_breakdown': result['decision_breakdown'], 'dry_run': self.dry_run}
            )
            
            logger.info(f"AutoMonitor check: {result['matches_found']} matches, "
                       f"{result['predictions_created']} predictions")
            
            # Также проверяем результаты прошедших матчей
            if not self.dry_run:
                try:
                    self.check_results()
                except Exception as e:
                    logger.error(f"Results check error in _check_matches: {e}")
            
        except Exception as e:
            logger.error(f"AutoMonitor check error: {e}")
            self._log_error(f"Check error: {e}")
        
        return result

    def _get_live_loader(self):
        """Получить live loader для всех поддерживаемых видов спорта."""
        from src.flashlive_loader import MultiSportFlashLiveLoader
        return MultiSportFlashLiveLoader()
    
    def _process_match(self, match: dict, decision: Optional[dict] = None) -> Optional[dict]:
        """Обработать матч и создать прогноз если нужно"""
        decision = decision or self.evaluate_match(match)
        if decision['status'] != 'candidate':
            return None

        if self.dry_run:
            return {
                **decision,
                'dry_run': True,
                'created': False,
            }

        target_odds = decision['target_odds']
        bet_on = decision['bet_on']
        
        try:
            from src.prediction_service import create_prediction_from_match
            return create_prediction_from_match(match, bet_on, target_odds, decision=decision)
        except ImportError:
            return None
        except Exception as e:
            logger.error(f"Prediction creation error: {e}")
            return None

    def evaluate_match(self, match: dict) -> dict:
        """Оценить матч без побочных эффектов и объяснить решение."""
        sport_type = self._resolve_sport_type(match)
        decision = self._build_decision_shell(match, sport_type)

        technical_verdict = self._evaluate_technical_verdict(match, sport_type)
        decision['technical_verdict'] = technical_verdict
        if technical_verdict['status'] != 'pass':
            decision['reason'] = technical_verdict['reason']
            return decision

        odds_verdict = self._evaluate_odds_verdict(match)
        decision['odds_verdict'] = odds_verdict
        if odds_verdict['status'] != 'pass':
            decision['reason'] = odds_verdict['reason']
            return decision

        decision['bet_on'] = odds_verdict.get('bet_on')
        decision['target_odds'] = odds_verdict.get('target_odds')

        history_verdict = self._evaluate_history_verdict(match, sport_type)
        decision['history_verdict'] = history_verdict
        if history_verdict['status'] != 'pass':
            decision['reason'] = history_verdict['reason']
            return decision

        pattern_verdict, model_verdict = self._evaluate_pattern_and_model(match, sport_type, history_verdict)
        decision['pattern_verdict'] = pattern_verdict
        decision['model_verdict'] = model_verdict

        agreement_verdict = self._evaluate_agreement_verdict(
            decision['bet_on'],
            pattern_verdict,
            model_verdict,
        )
        decision['agreement_verdict'] = agreement_verdict

        final_status, final_reason = self._finalize_decision(
            pattern_verdict=pattern_verdict,
            model_verdict=model_verdict,
            agreement_verdict=agreement_verdict,
        )
        decision['status'] = final_status
        decision['reason'] = final_reason
        return decision

    def _build_decision_shell(self, match: dict, sport_type: str) -> dict:
        return {
            'event_id': match.get('event_id'),
            'sport_type': sport_type,
            'league': match.get('league'),
            'home_team': match.get('home_team'),
            'away_team': match.get('away_team'),
            'home_odds': match.get('home_odds'),
            'away_odds': match.get('away_odds'),
            'status': 'rejected',
            'reason': None,
            'bet_on': None,
            'target_odds': None,
            'technical_verdict': {'status': 'pending', 'reason': None},
            'odds_verdict': {'status': 'pending', 'reason': None},
            'history_verdict': {'status': 'pending', 'reason': None},
            'pattern_verdict': {'status': 'pending', 'reason': None},
            'model_verdict': {'status': 'pending', 'reason': None},
            'agreement_verdict': {'status': 'pending', 'reason': None},
        }

    def _resolve_sport_type(self, match: dict) -> str:
        sport_type = str(match.get('sport_type') or '').strip().lower()
        if sport_type:
            return sport_type
        try:
            from src.prediction_service import infer_sport_type_from_league, SPORT_SLUGS

            inferred = infer_sport_type_from_league(match.get('league'))
            return SPORT_SLUGS.get(inferred, 'hockey')
        except Exception:
            return 'hockey'

    def _evaluate_technical_verdict(self, match: dict, sport_type: str) -> dict:
        league = match.get('league')
        if not league:
            return {'status': 'fail', 'reason': 'missing_league'}
        if not match.get('home_team') or not match.get('away_team'):
            return {'status': 'fail', 'reason': 'missing_teams'}
        if not match.get('event_id'):
            return {'status': 'fail', 'reason': 'missing_event_id'}
        if sport_type == 'unknown':
            return {'status': 'fail', 'reason': 'unknown_sport'}
        return {'status': 'pass', 'reason': 'match_metadata_ready'}

    def _evaluate_odds_verdict(self, match: dict) -> dict:
        home_odds = match.get('home_odds')
        away_odds = match.get('away_odds')
        if not home_odds and not away_odds:
            return {'status': 'fail', 'reason': 'missing_odds'}

        min_odds, max_odds = 2.0, 3.5
        if home_odds and min_odds <= home_odds <= max_odds:
            return {
                'status': 'pass',
                'reason': 'odds_in_target_range',
                'bet_on': 'home',
                'target_odds': home_odds,
            }
        if away_odds and min_odds <= away_odds <= max_odds:
            return {
                'status': 'pass',
                'reason': 'odds_in_target_range',
                'bet_on': 'away',
                'target_odds': away_odds,
            }
        return {'status': 'fail', 'reason': 'odds_out_of_range'}

    def _evaluate_history_verdict(self, match: dict, sport_type: str) -> dict:
        league = match.get('league')
        context = self._get_history_context(sport_type, league)
        normalized_home = self._normalize_team_for_history(sport_type, league, match.get('home_team'))
        normalized_away = self._normalize_team_for_history(sport_type, league, match.get('away_team'))
        team_counts = context['team_counts']
        pair_counts = context['pair_counts']
        min_team_matches = self._get_min_team_history(sport_type)
        h2h_key = tuple(sorted((normalized_home, normalized_away)))
        home_matches = team_counts.get(normalized_home, 0)
        away_matches = team_counts.get(normalized_away, 0)
        h2h_matches = pair_counts.get(h2h_key, 0)

        verdict = {
            'status': 'pass',
            'reason': 'history_ready',
            'records_total': context['records'],
            'min_team_matches': min_team_matches,
            'home_matches': home_matches,
            'away_matches': away_matches,
            'h2h_matches': h2h_matches,
            'normalized_home_team': normalized_home,
            'normalized_away_team': normalized_away,
        }

        if context['records'] == 0:
            verdict['status'] = 'fail'
            verdict['reason'] = 'no_history'
        elif home_matches < min_team_matches or away_matches < min_team_matches:
            verdict['status'] = 'fail'
            verdict['reason'] = 'insufficient_team_history'

        return verdict

    def _evaluate_pattern_and_model(self, match: dict, sport_type: str, history_verdict: dict) -> tuple[dict, dict]:
        league = match.get('league')
        home_team = history_verdict.get('normalized_home_team') or match.get('home_team')
        away_team = history_verdict.get('normalized_away_team') or match.get('away_team')

        if sport_type == 'hockey':
            return self._evaluate_hockey_signals(league, home_team, away_team)
        if sport_type == 'basketball':
            return self._evaluate_basketball_signals(league, home_team, away_team)
        if sport_type == 'volleyball':
            return self._evaluate_volleyball_signals(league, home_team, away_team)
        if sport_type == 'football':
            return self._evaluate_football_signals(league, home_team, away_team)
        return (
            {'status': 'fail', 'reason': 'unsupported_sport', 'signal_side': None, 'confidence': None},
            {'status': 'unsupported', 'reason': 'unsupported_sport', 'signal_side': None, 'confidence': None},
        )

    def _evaluate_hockey_signals(self, league: str, home_team: str, away_team: str) -> tuple[dict, dict]:
        if league == 'NHL':
            try:
                from app import analyze_game
                analysis = analyze_game(home_team, away_team)
            except Exception as e:
                logger.warning(f"NHL analysis unavailable: {e}")
                return (
                    {'status': 'fail', 'reason': 'analysis_unavailable', 'signal_side': None, 'confidence': None},
                    {'status': 'unavailable', 'reason': 'analysis_unavailable', 'signal_side': None, 'confidence': None},
                )

            if not analysis:
                return (
                    {'status': 'fail', 'reason': 'analysis_unavailable', 'signal_side': None, 'confidence': None},
                    {'status': 'unavailable', 'reason': 'analysis_unavailable', 'signal_side': None, 'confidence': None},
                )

            cpp = analysis.get('cpp_prediction', {})
            synergy = cpp.get('synergy', 0)
            pattern_side = cpp.get('team') if cpp.get('bet_recommendation') else None
            pattern_confidence = min(0.9, 0.55 + max(0, synergy - 2) * 0.05) if pattern_side else None
            pattern_verdict = {
                'status': 'pass' if pattern_side else 'fail',
                'reason': 'pattern_signal_ready' if pattern_side else 'no_pattern_signal',
                'signal_side': pattern_side,
                'confidence': pattern_confidence,
                'details': {
                    'synergy': synergy,
                    'patterns': cpp.get('patterns', []),
                    'strong_signal_max': analysis.get('strong_signal', {}).get('max', 0),
                },
            }

            prediction = analysis.get('prediction') or {}
            model_side = prediction.get('predicted_winner')
            if model_side == 'home':
                model_confidence = (prediction.get('home_probability') or 0) / 100
            elif model_side == 'away':
                model_confidence = (prediction.get('away_probability') or 0) / 100
            else:
                model_confidence = None

            threshold = 0.58
            if model_side and model_confidence is not None and model_confidence >= threshold:
                model_verdict = {
                    'status': 'pass',
                    'reason': 'model_signal_ready',
                    'signal_side': model_side,
                    'confidence': model_confidence,
                    'details': {
                        'break_probability': prediction.get('break_probability'),
                        'continue_probability': prediction.get('continue_probability'),
                    },
                }
            elif model_side and model_confidence is not None:
                model_verdict = {
                    'status': 'fail',
                    'reason': 'model_below_threshold',
                    'signal_side': model_side,
                    'confidence': model_confidence,
                }
            else:
                model_verdict = {
                    'status': 'unavailable',
                    'reason': 'model_unavailable',
                    'signal_side': None,
                    'confidence': None,
                }

            return pattern_verdict, model_verdict

        try:
            from app import init_multi_league
            engine = init_multi_league()
            analysis = engine.analyze_match(league, home_team, away_team)
        except Exception as e:
            logger.warning(f"Euro hockey analysis unavailable: {e}")
            return (
                {'status': 'fail', 'reason': 'analysis_unavailable', 'signal_side': None, 'confidence': None},
                {'status': 'unsupported', 'reason': 'model_not_calibrated_for_league', 'signal_side': None, 'confidence': None},
            )

        cpp = analysis.get('cpp_prediction', {})
        pattern_side = analysis.get('bet_recommendation')
        synergy = cpp.get('synergy', 0)
        pattern_verdict = {
            'status': 'pass' if pattern_side else 'fail',
            'reason': 'pattern_signal_ready' if pattern_side else 'no_pattern_signal',
            'signal_side': pattern_side,
            'confidence': min(0.85, 0.55 + max(0, synergy - 2) * 0.05) if pattern_side else None,
            'details': {
                'synergy': synergy,
                'patterns': cpp.get('patterns', []),
                'max_score': analysis.get('max_score'),
            },
        }
        model_verdict = {
            'status': 'unsupported',
            'reason': 'model_not_calibrated_for_league',
            'signal_side': None,
            'confidence': None,
        }
        return pattern_verdict, model_verdict

    def _evaluate_basketball_signals(self, league: str, home_team: str, away_team: str) -> tuple[dict, dict]:
        context = self._get_history_context('basketball', league)
        analyzer = context.get('analyzer')
        if analyzer is None:
            return (
                {'status': 'fail', 'reason': 'analysis_unavailable', 'signal_side': None, 'confidence': None},
                {'status': 'unsupported', 'reason': 'model_not_implemented_for_sport', 'signal_side': None, 'confidence': None},
            )

        analysis = analyzer.analyze_match(home_team, away_team)
        confidence = analysis.get('confidence')
        signal_side = analysis.get('bet_on')
        pattern_verdict = {
            'status': 'pass' if signal_side and confidence is not None and confidence >= 0.62 else 'fail',
            'reason': 'pattern_signal_ready' if signal_side and confidence is not None and confidence >= 0.62 else 'no_pattern_signal',
            'signal_side': signal_side,
            'confidence': confidence,
            'details': {
                'patterns': analysis.get('patterns', []),
                'home_win_pct': analysis.get('home_win_pct'),
                'away_win_pct': analysis.get('away_win_pct'),
            },
        }
        model_verdict = self._build_basketball_model_verdict(analysis)
        return pattern_verdict, model_verdict

    def _evaluate_volleyball_signals(self, league: str, home_team: str, away_team: str) -> tuple[dict, dict]:
        context = self._get_history_context('volleyball', league)
        analyzer = context.get('analyzer')
        if analyzer is None:
            return (
                {'status': 'fail', 'reason': 'analysis_unavailable', 'signal_side': None, 'confidence': None},
                {'status': 'unsupported', 'reason': 'model_not_implemented_for_sport', 'signal_side': None, 'confidence': None},
            )

        analysis = analyzer.analyze_match(home_team, away_team)
        confidence = analysis.get('confidence')
        signal_side = analysis.get('bet_on')
        pattern_verdict = {
            'status': 'pass' if signal_side and confidence is not None and confidence >= 0.60 else 'fail',
            'reason': 'pattern_signal_ready' if signal_side and confidence is not None and confidence >= 0.60 else 'no_pattern_signal',
            'signal_side': signal_side,
            'confidence': confidence,
            'details': {
                'patterns': analysis.get('patterns', []),
                'home_win_pct': analysis.get('home_win_pct'),
                'away_win_pct': analysis.get('away_win_pct'),
            },
        }
        model_verdict = self._build_volleyball_model_verdict(analysis)
        return pattern_verdict, model_verdict

    def _evaluate_football_signals(self, league: str, home_team: str, away_team: str) -> tuple[dict, dict]:
        context = self._get_history_context('football', league)
        analyzer = context.get('analyzer')
        if analyzer is None:
            return (
                {'status': 'fail', 'reason': 'analysis_unavailable', 'signal_side': None, 'confidence': None},
                {'status': 'unsupported', 'reason': 'model_not_implemented_for_sport', 'signal_side': None, 'confidence': None},
            )

        analysis = analyzer.analyze_match(home_team, away_team)
        pattern_verdict = {
            'status': 'fail',
            'reason': 'market_mismatch',
            'signal_side': None,
            'confidence': analysis.get('best_confidence'),
            'details': {
                'best_bet': analysis.get('best_bet'),
                'bet_type': 'half_totals',
                'patterns': analysis.get('patterns', []),
            },
        }
        model_verdict = {
            'status': 'unsupported',
            'reason': 'model_not_implemented_for_sport',
            'signal_side': None,
            'confidence': None,
        }
        return pattern_verdict, model_verdict

    def _build_basketball_model_verdict(self, analysis: dict) -> dict:
        signal_side = analysis.get('bet_on')
        confidence = analysis.get('confidence')
        if not signal_side or confidence is None:
            return {
                'status': 'unavailable',
                'reason': 'model_unavailable',
                'signal_side': None,
                'confidence': None,
            }

        home_win_pct = float(analysis.get('home_win_pct') or 0.5)
        away_win_pct = float(analysis.get('away_win_pct') or 0.5)
        home_streak = int(analysis.get('home_streak') or 0)
        away_streak = int(analysis.get('away_streak') or 0)
        h2h_matches = int(analysis.get('h2h_matches') or 0)

        if signal_side == 'home':
            edge = home_win_pct - away_win_pct
            streak = max(0, home_streak)
        else:
            edge = away_win_pct - home_win_pct
            streak = max(0, away_streak)

        calibrated_confidence = min(
            0.9,
            confidence
            + max(0.0, edge) * 0.30
            + min(streak, 5) * 0.015
            + (0.02 if h2h_matches >= 3 else 0.0),
        )
        threshold = 0.68
        if calibrated_confidence >= threshold and edge >= 0.05:
            return {
                'status': 'pass',
                'reason': 'model_signal_ready',
                'signal_side': signal_side,
                'confidence': calibrated_confidence,
                'details': {
                    'edge': round(edge, 4),
                    'h2h_matches': h2h_matches,
                    'streak': streak,
                },
            }
        return {
            'status': 'fail',
            'reason': 'model_below_threshold',
            'signal_side': signal_side,
            'confidence': calibrated_confidence,
            'details': {
                'edge': round(edge, 4),
                'h2h_matches': h2h_matches,
                'streak': streak,
            },
        }

    def _build_volleyball_model_verdict(self, analysis: dict) -> dict:
        signal_side = analysis.get('bet_on')
        confidence = analysis.get('confidence')
        if not signal_side or confidence is None:
            return {
                'status': 'unavailable',
                'reason': 'model_unavailable',
                'signal_side': None,
                'confidence': None,
            }

        home_win_pct = float(analysis.get('home_win_pct') or 0.5)
        away_win_pct = float(analysis.get('away_win_pct') or 0.5)
        home_form_pct = float(analysis.get('home_form_pct') or 0.5)
        away_form_pct = float(analysis.get('away_form_pct') or 0.5)
        patterns = analysis.get('patterns') or []

        home_strength = home_win_pct * 0.6 + home_form_pct * 0.4
        away_strength = away_win_pct * 0.6 + away_form_pct * 0.4

        if signal_side == 'home':
            edge = home_strength - away_strength
            target_strength = home_strength
        else:
            edge = away_strength - home_strength
            target_strength = away_strength

        calibrated_confidence = min(
            0.88,
            confidence
            + max(0.0, edge) * 0.35
            + min(len(patterns), 2) * 0.02,
        )
        threshold = 0.66
        if calibrated_confidence >= threshold and edge >= 0.04 and target_strength >= 0.58:
            return {
                'status': 'pass',
                'reason': 'model_signal_ready',
                'signal_side': signal_side,
                'confidence': calibrated_confidence,
                'details': {
                    'edge': round(edge, 4),
                    'target_strength': round(target_strength, 4),
                    'pattern_count': len(patterns),
                },
            }
        return {
            'status': 'fail',
            'reason': 'model_below_threshold',
            'signal_side': signal_side,
            'confidence': calibrated_confidence,
            'details': {
                'edge': round(edge, 4),
                'target_strength': round(target_strength, 4),
                'pattern_count': len(patterns),
            },
        }

    def _evaluate_agreement_verdict(self, target_side: Optional[str], pattern_verdict: dict, model_verdict: dict) -> dict:
        if not target_side:
            return {'status': 'fail', 'reason': 'missing_target_side'}

        pattern_side = pattern_verdict.get('signal_side')
        model_side = model_verdict.get('signal_side')

        if pattern_verdict.get('status') == 'pass' and pattern_side and pattern_side != target_side:
            return {'status': 'fail', 'reason': 'pattern_odds_conflict'}
        if model_verdict.get('status') == 'pass' and model_side and model_side != target_side:
            return {'status': 'fail', 'reason': 'model_odds_conflict'}
        if pattern_verdict.get('status') == 'pass' and model_verdict.get('status') == 'pass' and pattern_side != model_side:
            return {'status': 'fail', 'reason': 'pattern_model_conflict'}
        return {'status': 'pass', 'reason': 'signals_aligned'}

    def _finalize_decision(self, *, pattern_verdict: dict, model_verdict: dict, agreement_verdict: dict) -> tuple[str, str]:
        pattern_pass = pattern_verdict.get('status') == 'pass'
        model_pass = model_verdict.get('status') == 'pass'
        model_status = model_verdict.get('status')
        pattern_reason = pattern_verdict.get('reason')
        model_reason = model_verdict.get('reason')

        if pattern_pass and model_pass and agreement_verdict.get('status') == 'pass':
            return 'candidate', 'quality_gate_passed'

        if pattern_pass and model_status in {'unsupported', 'unavailable'}:
            return 'shadow_only', model_reason or 'model_unavailable'
        if pattern_pass and model_status == 'fail':
            return 'shadow_only', model_reason or 'model_rejected_signal'
        if pattern_reason == 'market_mismatch':
            return 'shadow_only', 'market_mismatch'
        if model_pass and not pattern_pass:
            return 'shadow_only', pattern_reason or 'pattern_rejected_signal'
        if agreement_verdict.get('status') == 'fail' and (pattern_pass or model_pass):
            return 'shadow_only', agreement_verdict.get('reason') or 'signal_conflict'
        return 'rejected', pattern_reason or model_reason or agreement_verdict.get('reason') or 'no_actionable_signal'

    def _get_history_context(self, sport_type: str, league: str) -> Dict[str, Any]:
        cache_key = (sport_type, league)
        if cache_key in self._history_context:
            return self._history_context[cache_key]

        from src.cache_catalog import load_history

        history = load_history(sport_type, league, prefer_odds=False)
        team_counts = Counter()
        pair_counts = Counter()
        for item in history:
            home_team = item.get('home_team')
            away_team = item.get('away_team')
            if home_team:
                team_counts[home_team] += 1
            if away_team:
                team_counts[away_team] += 1
            if home_team and away_team:
                pair_counts[tuple(sorted((home_team, away_team)))] += 1

        analyzer = None
        try:
            if sport_type == 'football':
                from src.football_pattern_engine import FootballPatternEngine
                analyzer = FootballPatternEngine()
                analyzer.load_matches(history)
            elif sport_type == 'basketball':
                from src.football_pattern_engine import BasketballPatternEngine
                analyzer = BasketballPatternEngine()
                analyzer.load_matches(history)
            elif sport_type == 'volleyball':
                from src.football_pattern_engine import VolleyballPatternEngine
                analyzer = VolleyballPatternEngine()
                analyzer.load_matches(history)
        except Exception as e:
            logger.warning(f"Analyzer build error for {sport_type}/{league}: {e}")

        context = {
            'records': len(history),
            'team_counts': team_counts,
            'pair_counts': pair_counts,
            'analyzer': analyzer,
        }
        self._history_context[cache_key] = context
        return context

    def _normalize_team_for_history(self, sport_type: str, league: str, team_name: Optional[str]) -> Optional[str]:
        if not team_name:
            return team_name
        if sport_type == 'hockey' and league == 'NHL':
            normalized = team_name.strip().upper()
            try:
                from app import get_abbrev_from_full_name
                resolved = get_abbrev_from_full_name(team_name)
                if resolved:
                    return resolved
            except Exception:
                pass
            return normalized
        return team_name.strip()

    def _get_min_team_history(self, sport_type: str) -> int:
        return {
            'hockey': 20,
            'football': 8,
            'basketball': 8,
            'volleyball': 8,
        }.get(sport_type, 8)

    def _log_match_decision(self, decision: dict):
        try:
            from src.system_logger import LOG_TYPES, log_to_db

            level = 'INFO' if decision.get('status') in {'candidate', 'shadow_only'} else 'WARNING'
            message = (
                f"Match gate: {decision.get('league')} | "
                f"{decision.get('home_team')} vs {decision.get('away_team')} -> "
                f"{decision.get('status')} ({decision.get('reason')})"
            )
            log_to_db(
                log_type=LOG_TYPES['MONITORING'],
                message=message,
                level=level,
                details={
                    'source': 'AutoMonitor',
                    'decision': decision,
                },
            )
            self._stats['shadow_logged'] += 1
        except Exception as e:
            logger.error(f"Decision log error: {e}")
    
    def _send_notification(self, prediction: dict) -> bool:
        """Отправить уведомление в Telegram"""
        try:
            from src.telegram_bot import send_prediction_notification
            return send_prediction_notification(prediction)
        except ImportError:
            return False
        except Exception as e:
            logger.error(f"Notification error: {e}")
            return False
    
    def _log_error(self, message: str):
        """Записать ошибку в лог"""
        try:
            from src.system_logger import log_error
            log_error(message, {'source': 'AutoMonitor'})
        except:
            pass
    
    def check_now(self) -> dict:
        """Выполнить проверку сейчас"""
        return self._check_matches()
    
    def check_results(self) -> dict:
        """Проверить результаты завершённых матчей и обновить is_win"""
        result = {
            'checked': 0,
            'updated': 0,
            'wins': 0,
            'losses': 0,
            'errors': 0
        }
        
        try:
            from app import app, db
            from models import Prediction
            
            loader = self._get_live_loader()
            if not loader.is_configured():
                logger.warning("FlashLive not configured for result checking")
                return result
            
            with app.app_context():
                # Найти все прогнозы без результата, у которых матч уже должен был закончиться
                pending = Prediction.query.filter(
                    Prediction.is_win == None,
                    Prediction.match_date < datetime.utcnow(),
                    Prediction.flashlive_event_id != None
                ).all()
                
                result['checked'] = len(pending)
                logger.info(f"Checking results for {len(pending)} predictions")
                
                for pred in pending:
                    try:
                        event_id = pred.flashlive_event_id
                        if not event_id:
                            continue
                        
                        match_result = loader.get_match_result(
                            event_id,
                            sport=getattr(pred, 'sport_type', None),
                            league=pred.league
                        )
                        
                        if not match_result:
                            continue
                        
                        if match_result['status'] != 'FINISHED':
                            continue
                        
                        # Определить победителя
                        winner = match_result.get('winner')
                        if not winner:
                            continue
                        
                        # Сохранить результат
                        home_score = match_result.get('home_score', 0)
                        away_score = match_result.get('away_score', 0)
                        pred.actual_result = f"{home_score}:{away_score}"
                        pred.result_updated_at = datetime.utcnow()
                        
                        # Определить выиграл ли прогноз
                        # predicted_outcome содержит название команды
                        predicted_team = pred.predicted_outcome
                        
                        if winner == 'home' and predicted_team == pred.home_team:
                            pred.is_win = True
                            result['wins'] += 1
                        elif winner == 'away' and predicted_team == pred.away_team:
                            pred.is_win = True
                            result['wins'] += 1
                        else:
                            pred.is_win = False
                            result['losses'] += 1
                        
                        result['updated'] += 1
                        
                    except Exception as e:
                        logger.error(f"Error checking result for prediction {pred.id}: {e}")
                        result['errors'] += 1
                
                db.session.commit()
            
            self._stats['results_checked'] = self._stats.get('results_checked', 0) + result['checked']
            self._stats['results_updated'] = self._stats.get('results_updated', 0) + result['updated']
            
            logger.info(f"Results check: {result['updated']} updated ({result['wins']} wins, {result['losses']} losses)")
            
        except Exception as e:
            logger.error(f"Results check error: {e}")
            result['errors'] += 1
        
        return result


class MonitorGuard:
    def __init__(self, lock_path: Optional[str] = None):
        self.lock_path = lock_path or os.environ.get('MONITOR_LOCK_PATH') or '/tmp/arena_monitor.lock'
        self.pid = os.getpid()
        self.fd = None
        self.mode = None
    def acquire(self) -> bool:
        try:
            import fcntl
            self.fd = open(self.lock_path, 'w')
            fcntl.lockf(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.mode = 'fcntl'
            self.fd.write(str(self.pid))
            self.fd.flush()
            return True
        except Exception:
            if self.fd:
                try:
                    self.fd.close()
                except Exception:
                    pass
                self.fd = None
        try:
            if os.path.exists(self.lock_path):
                try:
                    with open(self.lock_path, 'r') as f:
                        content = f.read().strip()
                        existing = int(content) if content else 0
                except Exception:
                    existing = 0
                if existing:
                    try:
                        os.kill(existing, 0)
                        return False
                    except OSError:
                        try:
                            os.unlink(self.lock_path)
                        except Exception:
                            pass
                else:
                    try:
                        os.unlink(self.lock_path)
                    except Exception:
                        pass
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(self.pid).encode())
            os.close(fd)
            self.mode = 'pid'
            return True
        except Exception:
            return False
    def release(self):
        if self.mode == 'fcntl':
            try:
                import fcntl
                fcntl.lockf(self.fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.fd.close()
            except Exception:
                pass
            try:
                os.unlink(self.lock_path)
            except Exception:
                pass
        elif self.mode == 'pid':
            try:
                with open(self.lock_path, 'r') as f:
                    content = f.read().strip()
                if content == str(self.pid):
                    os.unlink(self.lock_path)
            except Exception:
                pass
        self.mode = None


def get_auto_monitor() -> AutoMonitor:
    """Получить глобальный экземпляр AutoMonitor"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = AutoMonitor(check_interval=43200)  # 12 часов
    return _global_monitor


def set_auto_monitor(monitor: Optional[AutoMonitor]) -> Optional[AutoMonitor]:
    """Явно установить глобальный экземпляр AutoMonitor."""
    global _global_monitor
    _global_monitor = monitor
    return _global_monitor


def start_auto_monitoring():
    """Запустить автомониторинг (вызывается при старте сервера)"""
    global _monitor_thread_started, _guard
    if _monitor_thread_started:
        return
    if _guard is None:
        _guard = MonitorGuard()
    if not _guard.acquire():
        logger.info("AutoMonitor guard active, skipping start")
        return
    
    monitor = get_auto_monitor()
    if not monitor.is_running():
        monitor.start()
        _monitor_thread_started = True


class MockOddsLoader:
    """Тестовый загрузчик для демо"""
    
    def is_configured(self):
        return True
    
    def get_upcoming_games(self, days_ahead=2):
        from src.apisports_odds_loader import get_demo_odds
        return get_demo_odds()


def _release_guard():
    global _guard
    try:
        if _guard:
            _guard.release()
    except Exception:
        pass

atexit.register(_release_guard)
