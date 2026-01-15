"""
Новые маршруты для системы прогнозирования
"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for
from datetime import datetime, timedelta
import os

routes_bp = Blueprint('routes', __name__)

db = None
Prediction = None
UserDecision = None
ModelVersion = None
TelegramSettings = None

odds_monitor = None
telegram_notifier = None
odds_loader = None


def set_odds_loader(loader):
    """Установить загрузчик коэффициентов"""
    global odds_loader
    odds_loader = loader


def init_routes(database, models):
    """Инициализация маршрутов с моделями базы данных"""
    global db, Prediction, UserDecision, ModelVersion, TelegramSettings
    db = database
    Prediction = models['Prediction']
    UserDecision = models['UserDecision']
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


@routes_bp.route('/prediction/<int:prediction_id>')
def prediction_detail(prediction_id):
    """Страница детального прогноза"""
    prediction = None
    home_history = []
    away_history = []
    h2h_history = []
    
    if Prediction and db:
        try:
            prediction = Prediction.query.get_or_404(prediction_id)
        except Exception as e:
            print(f"Error loading prediction: {e}")
            return "Прогноз не найден", 404
    
    return render_template('prediction_detail.html', 
                         prediction=prediction,
                         home_history=home_history,
                         away_history=away_history,
                         h2h_history=h2h_history)


@routes_bp.route('/prediction/<int:prediction_id>/decide', methods=['POST'])
def prediction_decide(prediction_id):
    """Сохранить решение по прогнозу"""
    if not Prediction or not db or not UserDecision:
        return redirect(url_for('routes.predictions_page'))
    
    try:
        prediction = Prediction.query.get_or_404(prediction_id)
        
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
    """Страница статистики"""
    model_stats = {'total': 0, 'wins': 0, 'win_rate': 0, 'roi': 0}
    manual_stats = {'total': 0, 'wins': 0, 'win_rate': 0, 'roi': 0}
    league_stats = {}
    monthly_stats = []
    confidence_stats = {}
    
    if Prediction and UserDecision and db:
        try:
            all_predictions = Prediction.query.filter(Prediction.is_win != None).all()
            model_stats['total'] = len(all_predictions)
            model_stats['wins'] = sum(1 for p in all_predictions if p.is_win)
            model_stats['win_rate'] = (model_stats['wins'] / model_stats['total'] * 100) if model_stats['total'] else 0
            
            accepted = Prediction.query.join(UserDecision).filter(
                UserDecision.decision == 'accepted',
                Prediction.is_win != None
            ).all()
            manual_stats['total'] = len(accepted)
            manual_stats['wins'] = sum(1 for p in accepted if p.is_win)
            manual_stats['win_rate'] = (manual_stats['wins'] / manual_stats['total'] * 100) if manual_stats['total'] else 0
            
            for league in ['NHL', 'KHL', 'SHL', 'Liiga', 'DEL']:
                league_preds = [p for p in all_predictions if p.league == league]
                if league_preds:
                    wins = sum(1 for p in league_preds if p.is_win)
                    league_stats[league] = {
                        'total': len(league_preds),
                        'win_rate': wins / len(league_preds) * 100,
                        'roi': 0
                    }
                    
        except Exception as e:
            print(f"Error loading statistics: {e}")
    
    return render_template('statistics.html',
                         model_stats=model_stats,
                         manual_stats=manual_stats,
                         league_stats=league_stats,
                         monthly_stats=monthly_stats,
                         confidence_stats=confidence_stats)


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
    if odds_loader:
        if hasattr(odds_loader, 'get_upcoming_games'):
            try:
                matches = odds_loader.get_upcoming_games(days_ahead=1)
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
            prediction = Prediction.query.get_or_404(prediction_id)
            return jsonify(prediction.to_dict())
        except Exception as e:
            return jsonify({'error': str(e)}), 404
    
    return jsonify({'error': 'Not found'}), 404
