"""
Новые маршруты для системы прогнозирования
"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for
from datetime import datetime, timedelta
import os
from src.sports_config import SportType, get_leagues_for_sport, get_sport_config

routes_bp = Blueprint('routes', __name__)

db = None
Prediction = None
UserDecision = None
UserWatchlist = None
ModelVersion = None
TelegramSettings = None

odds_monitor = None
telegram_notifier = None
odds_loader = None


def set_odds_loader(loader):
    """Установить загрузчик коэффициентов"""
    global odds_loader
    odds_loader = loader


def _resolve_sport_type_from_league(league: str):
    """Определить вид спорта по коду лиги."""
    if not league:
        return SportType.HOCKEY
    for sport_type in (SportType.HOCKEY, SportType.FOOTBALL, SportType.BASKETBALL, SportType.VOLLEYBALL):
        if league in get_leagues_for_sport(sport_type):
            return sport_type
    return SportType.HOCKEY


def _get_odds_loader_for_sport(sport):
    """Вернуть loader для вида спорта.

    Поддерживает как старый single-loader, так и новый callable manager.
    """
    if callable(odds_loader):
        return odds_loader(sport)
    return odds_loader


def init_routes(database, models):
    """Инициализация маршрутов с моделями базы данных"""
    global db, Prediction, UserDecision, UserWatchlist, ModelVersion, TelegramSettings
    db = database
    Prediction = models['Prediction']
    UserDecision = models['UserDecision']
    UserWatchlist = models.get('UserWatchlist')
    ModelVersion = models['ModelVersion']
    TelegramSettings = models.get('TelegramSettings')


def set_monitor(monitor):
    """Установить монитор коэффициентов"""
    global odds_monitor
    odds_monitor = monitor


def set_telegram(notifier):
    """Установить Telegram нотификатор"""
    global telegram_notifier
    telegram_notifier = notifier


def _get_prediction_by_id(prediction_id):
    """Без legacy Query.get/get_or_404 API SQLAlchemy."""
    if not Prediction or not db:
        return None
    return db.session.get(Prediction, prediction_id)


def _get_prediction_target_odds(prediction):
    """Вытащить целевой коэффициент из данных прогноза без несуществующего поля odds."""
    import json

    patterns = prediction.patterns_data or {}
    if isinstance(patterns, str):
        try:
            patterns = json.loads(patterns)
        except Exception:
            patterns = {}

    target_odds = patterns.get('target_odds')
    if isinstance(target_odds, (int, float)) and target_odds > 0:
        return float(target_odds)

    bet_on = patterns.get('bet_on') or patterns.get('target')
    if bet_on == 'home' and prediction.home_odds:
        return prediction.home_odds
    if bet_on == 'away' and prediction.away_odds:
        return prediction.away_odds

    if prediction.predicted_outcome == prediction.home_team and prediction.home_odds:
        return prediction.home_odds
    if prediction.predicted_outcome == prediction.away_team and prediction.away_odds:
        return prediction.away_odds

    return prediction.home_odds or prediction.away_odds or 2.0


def _get_prediction_sport_slug(prediction) -> str:
    """Получить slug вида спорта из prediction или вывести по лиге."""
    sport_slug = getattr(prediction, 'sport_type', None)
    if sport_slug:
        return str(sport_slug).lower()
    return _resolve_sport_type_from_league(getattr(prediction, 'league', None)).name.lower()


@routes_bp.route('/predictions')
def predictions_page():
    """Страница списка прогнозов"""
    predictions = []
    stats = {'total': 0, 'pending': 0, 'win_rate': 0, 'roi': 0}
    
    if Prediction and db:
        try:
            predictions = Prediction.query.order_by(Prediction.match_date.desc()).limit(100).all()
            
            total = Prediction.query.count()
            pending = Prediction.query.filter(Prediction.user_decision == None).count()
            
            completed = Prediction.query.filter(Prediction.is_win != None).all()
            wins = sum(1 for p in completed if p.is_win)
            win_rate = (wins / len(completed) * 100) if completed else 0
            
            stats = {
                'total': total,
                'pending': pending,
                'win_rate': round(win_rate, 1),
                'roi': 0
            }
        except Exception as e:
            print(f"Error loading predictions: {e}")
    
    return render_template('predictions.html', predictions=predictions, stats=stats)

@routes_bp.route('/sports/<sport>')
def sports_predictions_page(sport):
    sport_map = {
        'hockey': SportType.HOCKEY,
        'football': SportType.FOOTBALL,
        'basketball': SportType.BASKETBALL,
        'volleyball': SportType.VOLLEYBALL
    }
    sport_type = sport_map.get(str(sport).lower())
    if not sport_type:
        return redirect(url_for('routes.predictions_page'))
    leagues = get_leagues_for_sport(sport_type)
    predictions = []
    stats = {'total': 0, 'pending': 0, 'win_rate': 0, 'roi': 0}
    if Prediction and db:
        try:
            query = Prediction.query.filter(Prediction.league.in_(leagues)).order_by(Prediction.match_date.desc())
            predictions = query.limit(100).all()
            total = Prediction.query.filter(Prediction.league.in_(leagues)).count()
            pending = Prediction.query.filter(Prediction.league.in_(leagues)).filter(Prediction.user_decision == None).count()
            completed = Prediction.query.filter(Prediction.league.in_(leagues)).filter(Prediction.is_win != None).all()
            wins = sum(1 for p in completed if p.is_win)
            win_rate = (wins / len(completed) * 100) if completed else 0
            stats = {
                'total': total,
                'pending': pending,
                'win_rate': round(win_rate, 1),
                'roi': 0
            }
        except Exception as e:
            print(f"Error loading sport predictions: {e}")
    sport_config = get_sport_config(sport_type)
    return render_template('sports/sport_predictions.html',
                           sport=sport,
                           sport_config=sport_config,
                           leagues=leagues,
                           predictions=predictions,
                           stats=stats)

@routes_bp.route('/prediction/<int:prediction_id>')
def prediction_detail(prediction_id):
    """Страница детального прогноза"""
    prediction = None
    home_history = []
    away_history = []
    h2h_history = []
    h2h_data = None
    
    if Prediction and db:
        try:
            prediction = _get_prediction_by_id(prediction_id)
            if prediction is None:
                return "Прогноз не найден", 404
            
            event_id = prediction.flashlive_event_id
            if not event_id and prediction.patterns_data:
                event_id = prediction.patterns_data.get('event_id', '')
                if event_id:
                    event_id = event_id.replace('flash_', '')
            
            loader = _get_odds_loader_for_sport(
                getattr(prediction, 'sport_type', None) or _resolve_sport_type_from_league(prediction.league)
            )

            if event_id and loader:
                try:
                    h2h_data = loader.get_h2h_data(event_id)
                    if h2h_data:
                        home_history = h2h_data.get('home_team_matches', [])
                        away_history = h2h_data.get('away_team_matches', [])
                except Exception as e:
                    print(f"Error loading H2H data: {e}")
                    
        except Exception as e:
            print(f"Error loading prediction: {e}")
            return "Прогноз не найден", 404
    
    # Получаем рекомендацию RL-агента
    rl_recommendation = None
    if prediction:
        try:
            from src.prediction_service import get_rl_recommendation_for_prediction
            prediction_data = {
                'confidence': prediction.confidence or 0.5,
                'home_odds': prediction.home_odds,
                'away_odds': prediction.away_odds,
                'patterns_data': prediction.patterns_data or {}
            }
            rl_recommendation = get_rl_recommendation_for_prediction(prediction_data)
        except Exception as e:
            print(f"Error getting RL recommendation: {e}")
    
    return render_template('prediction_detail.html', 
                         prediction=prediction,
                         home_history=home_history,
                         away_history=away_history,
                         h2h_history=h2h_history,
                         h2h_data=h2h_data,
                         rl_recommendation=rl_recommendation)


@routes_bp.route('/prediction/<int:prediction_id>/decide', methods=['POST'])
def prediction_decide(prediction_id):
    """Сохранить решение по прогнозу"""
    if not Prediction or not db or not UserDecision:
        return redirect(url_for('routes.predictions_page'))
    
    try:
        prediction = _get_prediction_by_id(prediction_id)
        if prediction is None:
            return redirect(url_for('routes.predictions_page'))
        
        decision = request.form.get('decision')
        comment = request.form.get('comment', '')
        
        if decision and decision in ['accepted', 'rejected']:
            user_decision = UserDecision(
                prediction_id=prediction_id,
                decision=decision,
                comment=comment
            )
            db.session.add(user_decision)
            db.session.commit()
    except Exception as e:
        print(f"Error saving decision: {e}")
        db.session.rollback()
    
    return redirect(url_for('routes.prediction_detail', prediction_id=prediction_id))


@routes_bp.route('/dashboard')
def dashboard_page():
    """Страница дашборда модели - впечатляющий AI Dashboard"""
    
    telegram_configured = bool(os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID'))
    
    monitor_running = False
    if odds_monitor:
        stats = odds_monitor.get_stats()
        monitor_running = stats.get('is_running', False)
    
    total_predictions = 0
    today_predictions = 0
    pending_decisions = 0
    avg_confidence = 7.2
    
    if Prediction and db:
        try:
            total_predictions = Prediction.query.count()
            
            today = datetime.now().date()
            today_predictions = Prediction.query.filter(
                db.func.date(Prediction.created_at) == today
            ).count()
            
            pending_decisions = Prediction.query.filter(
                Prediction.user_decision == None
            ).count()
            
            all_preds = Prediction.query.filter(Prediction.confidence_1_10 != None).all()
            if all_preds:
                avg_confidence = sum(p.confidence_1_10 for p in all_preds) / len(all_preds)
        except Exception as e:
            print(f"Error loading dashboard stats: {e}")
    
    return render_template('dashboard.html',
                         total_predictions=total_predictions,
                         today_predictions=today_predictions,
                         pending_decisions=pending_decisions,
                         avg_confidence=avg_confidence,
                         telegram_configured=telegram_configured,
                         monitor_running=monitor_running)


@routes_bp.route('/statistics')
def statistics_page():
    """Страница расширенной статистики с аналитикой точности модели"""
    from collections import defaultdict
    import json
    
    model_stats = {'total': 0, 'wins': 0, 'losses': 0, 'pending': 0, 'win_rate': 0, 'roi': 0}
    rl_stats = {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0, 'roi': 0, 'bet_count': 0, 'skip_count': 0}
    manual_stats = {'total': 0, 'wins': 0, 'win_rate': 0, 'roi': 0}
    sport_stats = {}
    league_stats = {}
    monthly_stats = []
    confidence_stats = {}
    pattern_stats = {}
    chart_data = {'labels': [], 'win_rates': [], 'totals': []}
    
    if Prediction and UserDecision and db:
        try:
            all_predictions = Prediction.query.all()
            completed = [p for p in all_predictions if p.is_win is not None]
            pending = [p for p in all_predictions if p.is_win is None]
            
            model_stats['total'] = len(completed)
            model_stats['wins'] = sum(1 for p in completed if p.is_win)
            model_stats['losses'] = sum(1 for p in completed if not p.is_win)
            model_stats['pending'] = len(pending)
            model_stats['win_rate'] = (model_stats['wins'] / model_stats['total'] * 100) if model_stats['total'] else 0
            
            profit = sum(_get_prediction_target_odds(p) - 1 for p in completed if p.is_win) - model_stats['losses']
            if model_stats['total'] > 0:
                model_stats['roi'] = (profit / model_stats['total']) * 100
            
            accepted = Prediction.query.join(UserDecision).filter(
                UserDecision.decision == 'accepted',
                Prediction.is_win != None
            ).all()
            manual_stats['total'] = len(accepted)
            manual_stats['wins'] = sum(1 for p in accepted if p.is_win)
            manual_stats['losses'] = len(accepted) - manual_stats['wins']
            manual_stats['win_rate'] = (manual_stats['wins'] / manual_stats['total'] * 100) if manual_stats['total'] else 0
            
            manual_profit = sum(_get_prediction_target_odds(p) - 1 for p in accepted if p.is_win) - manual_stats['losses']
            if manual_stats['total'] > 0:
                manual_stats['roi'] = (manual_profit / manual_stats['total']) * 100
            
            # RL-агент статистика
            # Считаем ВСЕ прогнозы с RL рекомендацией (включая pending)
            all_rl_bet = [p for p in all_predictions if p.rl_recommendation == 'BET']
            all_rl_skip = [p for p in all_predictions if p.rl_recommendation == 'SKIP']
            
            # Только completed для расчёта win rate
            rl_bet_completed = [p for p in completed if p.rl_recommendation == 'BET']
            rl_skip_completed = [p for p in completed if p.rl_recommendation == 'SKIP']
            
            rl_stats['bet_count'] = len(all_rl_bet)
            rl_stats['skip_count'] = len(all_rl_skip)
            rl_stats['total'] = len(rl_bet_completed)  # Только completed для win rate
            rl_stats['wins'] = sum(1 for p in rl_bet_completed if p.is_win)
            rl_stats['losses'] = rl_stats['total'] - rl_stats['wins']
            rl_stats['win_rate'] = (rl_stats['wins'] / rl_stats['total'] * 100) if rl_stats['total'] else 0
            
            # Сколько SKIP оказались проигрышами (спасённые ставки)
            skip_would_lose = sum(1 for p in rl_skip_completed if not p.is_win)
            rl_stats['skip_saved'] = skip_would_lose
            
            rl_profit = sum(_get_prediction_target_odds(p) - 1 for p in rl_bet_completed if p.is_win) - rl_stats['losses']
            if rl_stats['total'] > 0:
                rl_stats['roi'] = (rl_profit / rl_stats['total']) * 100
            
            sport_order = ['hockey', 'football', 'basketball', 'volleyball']

            for sport_slug in sport_order:
                sport_preds = [p for p in completed if _get_prediction_sport_slug(p) == sport_slug]
                if sport_preds:
                    wins = sum(1 for p in sport_preds if p.is_win)
                    losses = len(sport_preds) - wins
                    sport_profit = sum(_get_prediction_target_odds(p) - 1 for p in sport_preds if p.is_win) - losses
                    sport_type = {
                        'hockey': SportType.HOCKEY,
                        'football': SportType.FOOTBALL,
                        'basketball': SportType.BASKETBALL,
                        'volleyball': SportType.VOLLEYBALL,
                    }[sport_slug]
                    sport_config = get_sport_config(sport_type)
                    sport_stats[sport_slug] = {
                        'slug': sport_slug,
                        'name': sport_config.get('name', sport_slug.title()),
                        'name_ru': sport_config.get('name_ru', sport_slug.title()),
                        'icon': sport_config.get('icon', '🎯'),
                        'total': len(sport_preds),
                        'wins': wins,
                        'losses': losses,
                        'win_rate': wins / len(sport_preds) * 100,
                        'roi': (sport_profit / len(sport_preds)) * 100 if sport_preds else 0,
                    }

            for league in sorted({p.league for p in completed if p.league}):
                league_preds = [p for p in completed if p.league == league]
                if league_preds:
                    wins = sum(1 for p in league_preds if p.is_win)
                    losses = len(league_preds) - wins
                    league_profit = sum(_get_prediction_target_odds(p) - 1 for p in league_preds if p.is_win) - losses
                    roi = (league_profit / len(league_preds)) * 100 if league_preds else 0
                    sport_slug = _get_prediction_sport_slug(league_preds[0])
                    sport_type = {
                        'hockey': SportType.HOCKEY,
                        'football': SportType.FOOTBALL,
                        'basketball': SportType.BASKETBALL,
                        'volleyball': SportType.VOLLEYBALL,
                    }.get(sport_slug, SportType.HOCKEY)
                    sport_config = get_sport_config(sport_type)
                    league_stats[league] = {
                        'total': len(league_preds),
                        'wins': wins,
                        'losses': losses,
                        'win_rate': wins / len(league_preds) * 100,
                        'roi': roi,
                        'sport_slug': sport_slug,
                        'sport_name': sport_config.get('name_ru', sport_slug.title()),
                        'sport_icon': sport_config.get('icon', '🎯'),
                    }
            
            for conf_level in range(1, 11):
                conf_preds = [p for p in completed if p.confidence_1_10 == conf_level]
                if conf_preds:
                    wins = sum(1 for p in conf_preds if p.is_win)
                    confidence_stats[conf_level] = {
                        'total': len(conf_preds),
                        'wins': wins,
                        'win_rate': wins / len(conf_preds) * 100
                    }
            
            pattern_counts = defaultdict(lambda: {'total': 0, 'wins': 0})
            for pred in completed:
                if pred.patterns_data:
                    patterns = pred.patterns_data
                    if isinstance(patterns, str):
                        try:
                            patterns = json.loads(patterns)
                        except:
                            patterns = {}
                    
                    pattern_type = patterns.get('pattern_type', 'unknown')
                    if pattern_type and pattern_type != 'unknown':
                        pattern_counts[pattern_type]['total'] += 1
                        if pred.is_win:
                            pattern_counts[pattern_type]['wins'] += 1
            
            for pattern_type, counts in pattern_counts.items():
                if counts['total'] >= 3:
                    pattern_stats[pattern_type] = {
                        'total': counts['total'],
                        'wins': counts['wins'],
                        'win_rate': counts['wins'] / counts['total'] * 100
                    }
            
            pattern_stats = dict(sorted(pattern_stats.items(), 
                                       key=lambda x: x[1]['win_rate'], reverse=True))
            
            monthly_data = defaultdict(lambda: {'total': 0, 'wins': 0, 'accepted': 0})
            for pred in completed:
                if pred.match_date:
                    month_key = pred.match_date.strftime('%Y-%m')
                    monthly_data[month_key]['total'] += 1
                    if pred.is_win:
                        monthly_data[month_key]['wins'] += 1
            
            for pred in accepted:
                if pred.match_date:
                    month_key = pred.match_date.strftime('%Y-%m')
                    monthly_data[month_key]['accepted'] += 1
            
            sorted_months = sorted(monthly_data.keys())
            prev_win_rate = None
            for month in sorted_months:
                data = monthly_data[month]
                win_rate = data['wins'] / data['total'] * 100 if data['total'] else 0
                trend = 0
                if prev_win_rate is not None:
                    trend = 1 if win_rate > prev_win_rate else (-1 if win_rate < prev_win_rate else 0)
                prev_win_rate = win_rate
                
                month_preds = [p for p in completed if p.match_date and p.match_date.strftime('%Y-%m') == month]
                month_wins = [p for p in month_preds if p.is_win]
                month_losses = len(month_preds) - len(month_wins)
                month_profit = sum(_get_prediction_target_odds(p) - 1 for p in month_wins) - month_losses
                roi = (month_profit / len(month_preds)) * 100 if month_preds else 0
                
                monthly_stats.append({
                    'month': month,
                    'total': data['total'],
                    'wins': data['wins'],
                    'win_rate': win_rate,
                    'roi': roi,
                    'accepted': data['accepted'],
                    'trend': trend
                })
            
            chart_data['labels'] = sorted_months[-12:]
            chart_data['cumulative_roi'] = []
            cumulative_profit = 0
            cumulative_total = 0
            
            for month in chart_data['labels']:
                data = monthly_data[month]
                win_rate = data['wins'] / data['total'] * 100 if data['total'] else 0
                chart_data['win_rates'].append(round(win_rate, 1))
                chart_data['totals'].append(data['total'])
                
                # Накопительный ROI
                month_preds = [p for p in completed if p.match_date and p.match_date.strftime('%Y-%m') == month]
                month_wins = [p for p in month_preds if p.is_win]
                month_losses = len(month_preds) - len(month_wins)
                month_profit = sum(_get_prediction_target_odds(p) - 1 for p in month_wins) - month_losses
                
                cumulative_profit += month_profit
                cumulative_total += len(month_preds)
                
                cum_roi = (cumulative_profit / cumulative_total) * 100 if cumulative_total > 0 else 0
                chart_data['cumulative_roi'].append(round(cum_roi, 1))
                    
        except Exception as e:
            print(f"Error loading statistics: {e}")
            import traceback
            traceback.print_exc()
    
    return render_template('statistics.html',
                         model_stats=model_stats,
                         rl_stats=rl_stats,
                         manual_stats=manual_stats,
                         sport_stats=sport_stats,
                         league_stats=league_stats,
                         league_order=list(league_stats.keys()),
                         monthly_stats=monthly_stats,
                         confidence_stats=confidence_stats,
                         pattern_stats=pattern_stats,
                         chart_data=chart_data)


@routes_bp.route('/settings/telegram')
def telegram_setup_page():
    """Страница настройки Telegram"""
    bot_configured = bool(os.environ.get('TELEGRAM_BOT_TOKEN'))
    chat_configured = bool(os.environ.get('TELEGRAM_CHAT_ID'))
    is_active = bot_configured and chat_configured
    bot_info = None
    
    if telegram_notifier and is_active:
        bot_info = telegram_notifier.test_connection()
        if not bot_info.get('ok'):
            bot_info = None
    
    return render_template('telegram_setup.html',
                         bot_configured=bot_configured,
                         chat_configured=chat_configured,
                         is_active=is_active,
                         bot_info=bot_info)


@routes_bp.route('/api/telegram/test', methods=['POST'])
def api_telegram_test():
    """API: Тест Telegram соединения"""
    data = request.get_json() or {}
    bot_token = data.get('bot_token')
    
    if not bot_token:
        return jsonify({'ok': False, 'error': 'Token required'})
    
    try:
        import requests as req
        response = req.get(
            f"https://api.telegram.org/bot{bot_token}/getMe",
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                bot_info = result.get('result', {})
                return jsonify({
                    'ok': True,
                    'bot_username': bot_info.get('username'),
                    'bot_name': bot_info.get('first_name')
                })
        
        return jsonify({'ok': False, 'error': 'Invalid token'})
        
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@routes_bp.route('/api/monitor/start', methods=['POST'])
def api_monitor_start():
    """API: Запустить мониторинг"""
    if odds_monitor:
        odds_monitor.start()
        return jsonify({'ok': True, 'message': 'Мониторинг запущен'})
    return jsonify({'ok': False, 'error': 'Monitor not configured'})


@routes_bp.route('/api/monitor/stop', methods=['POST'])
def api_monitor_stop():
    """API: Остановить мониторинг"""
    if odds_monitor:
        odds_monitor.stop()
        return jsonify({'ok': True, 'message': 'Мониторинг остановлен'})
    return jsonify({'ok': False, 'error': 'Monitor not configured'})


@routes_bp.route('/api/monitor/check', methods=['POST'])
def api_monitor_check():
    """API: Проверить коэффициенты сейчас"""
    if odds_monitor:
        result = odds_monitor.check_now()
        return jsonify(result)
    return jsonify({'ok': False, 'error': 'Monitor not configured'})


@routes_bp.route('/api/monitor/stats')
def api_monitor_stats():
    """API: Статистика мониторинга"""
    from datetime import datetime, timedelta
    
    stats = {'is_running': False}
    if odds_monitor:
        stats = odds_monitor.get_stats()
    
    # Количество матчей (5 лиг)
    loader = _get_odds_loader_for_sport(SportType.HOCKEY)
    if loader:
        if hasattr(loader, 'get_upcoming_games'):
            try:
                matches = loader.get_upcoming_games(days_ahead=1)
                stats['matches_available'] = len(matches)
            except Exception:
                stats['matches_available'] = 0
        else:
            stats['matches_available'] = 0
    
    # Количество предложенных ставок сегодня
    if Prediction and db:
        try:
            today = datetime.utcnow().date()
            today_start = datetime.combine(today, datetime.min.time())
            today_predictions = Prediction.query.filter(
                Prediction.created_at >= today_start
            ).count()
            stats['bets_suggested'] = today_predictions
        except Exception:
            stats['bets_suggested'] = 0
    else:
        stats['bets_suggested'] = 0
    
    return jsonify(stats)


@routes_bp.route('/api/predictions')
def api_predictions():
    """API: Список прогнозов"""
    predictions = []
    
    if Prediction and db:
        try:
            limit = request.args.get('limit', 50, type=int)
            league = request.args.get('league')
            
            query = Prediction.query.order_by(Prediction.match_date.desc())
            
            if league:
                query = query.filter(Prediction.league == league)
            
            predictions = [p.to_dict() for p in query.limit(limit).all()]
        except Exception as e:
            print(f"Error in API: {e}")
    
    return jsonify({'predictions': predictions})


@routes_bp.route('/api/predictions/<int:prediction_id>')
def api_prediction_detail(prediction_id):
    """API: Детали прогноза"""
    if Prediction and db:
        try:
            prediction = _get_prediction_by_id(prediction_id)
            if prediction is None:
                return jsonify({'error': 'Not found'}), 404
            return jsonify(prediction.to_dict())
        except Exception as e:
            return jsonify({'error': str(e)}), 404
    
    return jsonify({'error': 'Not found'}), 404


@routes_bp.route('/logs')
def logs_page():
    """Страница логов системы"""
    from models import SystemLog
    from src.odds_monitor import get_auto_monitor
    from src.data_refresh import get_last_refresh_info
    
    log_type = request.args.get('type', '')
    level = request.args.get('level', '')
    limit = request.args.get('limit', 50, type=int)
    
    query = SystemLog.query.order_by(SystemLog.timestamp.desc())
    
    if log_type:
        query = query.filter(SystemLog.log_type == log_type)
    if level:
        query = query.filter(SystemLog.level == level)
    
    logs = query.limit(limit).all()
    
    monitor = get_auto_monitor()
    monitor_stats = monitor.get_stats() if monitor else {}
    
    refresh_info = get_last_refresh_info() or {}
    
    log_types = ['data_update', 'monitoring', 'prediction', 'error', 'system']
    levels = ['INFO', 'WARNING', 'ERROR', 'CRITICAL']
    
    return render_template('logs.html',
                          logs=logs,
                          log_types=log_types,
                          levels=levels,
                          selected_type=log_type,
                          selected_level=level,
                          limit=limit,
                          monitor_stats=monitor_stats,
                          refresh_info=refresh_info)


@routes_bp.route('/api/logs')
def api_logs():
    """API: Получить логи"""
    from models import SystemLog
    
    log_type = request.args.get('type', '')
    level = request.args.get('level', '')
    limit = request.args.get('limit', 50, type=int)
    
    query = SystemLog.query.order_by(SystemLog.timestamp.desc())
    
    if log_type:
        query = query.filter(SystemLog.log_type == log_type)
    if level:
        query = query.filter(SystemLog.level == level)
    
    logs = [log.to_dict() for log in query.limit(limit).all()]
    
    return jsonify({'logs': logs})


@routes_bp.route('/api/auto-monitor/stats')
def api_auto_monitor_stats():
    """API: Статистика автомониторинга"""
    from src.odds_monitor import get_auto_monitor
    from src.data_refresh import get_last_refresh_info
    
    monitor = get_auto_monitor()
    stats = monitor.get_stats() if monitor else {'is_running': False}
    
    refresh_info = get_last_refresh_info()
    if refresh_info:
        stats['last_data_refresh_info'] = refresh_info
    
    return jsonify(stats)


@routes_bp.route('/api/auto-monitor/check', methods=['POST'])
def api_auto_monitor_check():
    """API: Выполнить проверку автомониторинга сейчас"""
    from src.odds_monitor import get_auto_monitor

    monitor = get_auto_monitor()
    if monitor:
        result = monitor.check_now()
        return jsonify({'ok': True, 'result': result})
    return jsonify({'ok': False, 'error': 'AutoMonitor not available'})


# ── Watchlist ─────────────────────────────────────────────────────────────────

@routes_bp.route('/watchlist')
def watchlist_page():
    """Страница отобранных матчей"""
    entries = []
    if UserWatchlist and db:
        try:
            entries = UserWatchlist.query.order_by(UserWatchlist.created_at.desc()).all()
        except Exception as e:
            print(f"Error loading watchlist: {e}")
    return render_template('watchlist.html', entries=entries)


@routes_bp.route('/api/watchlist/<int:prediction_id>', methods=['POST'])
def api_watchlist_add(prediction_id):
    """API: Добавить матч в отобранные"""
    if not UserWatchlist or not db:
        return jsonify({'error': 'Unavailable'}), 503
    try:
        existing = UserWatchlist.query.filter_by(prediction_id=prediction_id).first()
        if existing:
            return jsonify({'status': 'already_added'})
        entry = UserWatchlist(prediction_id=prediction_id)
        db.session.add(entry)
        db.session.commit()
        return jsonify({'status': 'added'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@routes_bp.route('/api/watchlist/<int:prediction_id>', methods=['DELETE'])
def api_watchlist_remove(prediction_id):
    """API: Убрать матч из отобранных"""
    if not UserWatchlist or not db:
        return jsonify({'error': 'Unavailable'}), 503
    try:
        entry = UserWatchlist.query.filter_by(prediction_id=prediction_id).first()
        if entry:
            db.session.delete(entry)
            db.session.commit()
        return jsonify({'status': 'removed'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@routes_bp.route('/api/watchlist/<int:prediction_id>/note', methods=['PATCH'])
def api_watchlist_note(prediction_id):
    """API: Обновить заметку"""
    if not UserWatchlist or not db:
        return jsonify({'error': 'Unavailable'}), 503
    try:
        entry = UserWatchlist.query.filter_by(prediction_id=prediction_id).first()
        if not entry:
            return jsonify({'error': 'Not found'}), 404
        data = request.get_json() or {}
        entry.note = data.get('note', '')
        db.session.commit()
        return jsonify({'status': 'ok'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
