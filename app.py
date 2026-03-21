"""
pattern_interruption Web Interface
Веб-интерфейс для тестирования прогнозов на реальных матчах

Refactored: business logic extracted to src/game_analysis.py, src/odds_service.py,
src/nhl_teams.py; routes to src/routes/auth.py, src/routes/legacy_api.py.
"""
import warnings
warnings.filterwarnings('ignore', category=UserWarning)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask
import os
import sys
from sqlalchemy.pool import StaticPool
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.sports_config import SportType
from src.nhl_teams import env_flag, resolve_sport_type
from models import db, Prediction, UserDecision, UserWatchlist, ModelVersion, TelegramSettings, OddsMonitorLog, SystemLog, User
from src.routes import routes_bp, init_routes, set_monitor, set_telegram, set_odds_loader
from src.routes.auth import auth_bp
from src.routes.legacy_api import legacy_api_bp
from src.odds_monitor import OddsMonitor, start_auto_monitoring, get_auto_monitor
from src.odds_service import set_flashlive_loader_getter
from src.game_analysis import warmup_multi_league

app = Flask(__name__, static_folder='static')
app.config['TEMPLATES_AUTO_RELOAD'] = True

supabase = None
telegram_notifier = None
odds_loader = None
flashlive_loader = None
flashlive_loaders = {}
flashlive_multi_loader = None

_db_initialized = False
_routes_initialized = False


def get_flashlive_loader(sport=None):
    """FlashLive API disabled — saving API quota. Returns None for all sports.
    TODO: re-enable when ready to use RapidAPI again."""
    return None

def _get_flashlive_loader_real(sport=None):
    """Original loader factory — kept for re-enabling later."""
    global flashlive_loader, flashlive_loaders

    sport_type = resolve_sport_type(sport)
    loader = flashlive_loaders.get(sport_type)
    if loader is not None:
        return loader

    from src.flashlive_loader import FlashLiveLoader, set_telegram_notifier as set_flashlive_notifier

    loader = FlashLiveLoader(sport_type=sport_type)
    flashlive_loaders[sport_type] = loader

    if telegram_notifier is not None:
        set_flashlive_notifier(telegram_notifier)

    if sport_type == SportType.HOCKEY:
        flashlive_loader = loader

    return loader


def create_app(testing: bool = False, start_background: bool = True):
    """Сконфигурировать глобальный Flask app для рантайма или тестов."""
    global _db_initialized, _routes_initialized
    global supabase, telegram_notifier, odds_loader, flashlive_loader, flashlive_loaders, flashlive_multi_loader

    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['TESTING'] = testing

    if testing:
        app.secret_key = os.environ.get("SESSION_SECRET", "test-secret-key")
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///:memory:")
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
        supabase = None
    else:
        app.secret_key = os.environ.get("SESSION_SECRET")
        if not app.secret_key:
            raise RuntimeError("SESSION_SECRET environment variable is required. Please set it in the Secrets tab.")

        database_url = os.environ.get("DATABASE_URL", "")
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_recycle": 300,
            "pool_pre_ping": True,
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
        }

        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY")
        supabase = create_client(supabase_url, supabase_anon_key) if (
            create_client and supabase_url and supabase_anon_key
        ) else None

    app.config['_supabase'] = supabase
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if not _db_initialized:
        db.init_app(app)
        _db_initialized = True

    if not _routes_initialized:
        init_routes(db, {
            'Prediction': Prediction,
            'UserDecision': UserDecision,
            'UserWatchlist': UserWatchlist,
            'ModelVersion': ModelVersion,
            'TelegramSettings': TelegramSettings,
        })
        app.register_blueprint(routes_bp)
        app.register_blueprint(auth_bp)
        app.register_blueprint(legacy_api_bp)
        _routes_initialized = True

    with app.app_context():
        db.create_all()
        try:
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            if not inspector.has_table('users'):
                User.__table__.create(db.engine)
        except Exception:
            pass

    if testing:
        telegram_notifier = None
        odds_loader = None
        flashlive_loader = None
        flashlive_loaders = {}
        flashlive_multi_loader = None
        return app

    if telegram_notifier is None or odds_loader is None or flashlive_loader is None or flashlive_multi_loader is None:
        from src.telegram_bot import TelegramNotifier
        from src.flashlive_loader import MultiSportFlashLiveLoader, set_telegram_notifier as set_flashlive_notifier

        telegram_notifier = TelegramNotifier()
        flashlive_loader = get_flashlive_loader(SportType.HOCKEY)
        flashlive_multi_loader = MultiSportFlashLiveLoader()
        odds_loader = get_flashlive_loader
        set_telegram(telegram_notifier)
        set_odds_loader(get_flashlive_loader)
        set_flashlive_notifier(telegram_notifier)
        set_flashlive_loader_getter(get_flashlive_loader)

    if start_background:
        start_auto_monitoring()
        startup_initialization()

    return app


# ── Request hooks ────────────────────────────────────────────────────────────

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response


# ── Prediction creation & monitoring ─────────────────────────────────────────

def create_prediction_from_match(match_data):
    """Создать прогноз на основе данных матча."""
    try:
        home_odds = match_data.get('home_odds')
        away_odds = match_data.get('away_odds')

        if not home_odds and not away_odds:
            return None

        min_odds, max_odds = 2.0, 3.5
        target_odds = None
        bet_on = None

        if home_odds and min_odds <= home_odds <= max_odds:
            target_odds = home_odds
            bet_on = 'home'
        elif away_odds and min_odds <= away_odds <= max_odds:
            target_odds = away_odds
            bet_on = 'away'
        else:
            return None

        from src.prediction_service import create_prediction_from_match as create_live_prediction
        return create_live_prediction(match_data, bet_on, target_odds, flask_app=app)

    except Exception as e:
        print(f"Error creating prediction: {e}")
        return None


def init_odds_monitor():
    """Инициализация монитора коэффициентов."""
    global flashlive_loader, flashlive_multi_loader

    def prediction_callback(match_data):
        return create_prediction_from_match(match_data)

    def notification_callback(prediction):
        if prediction and telegram_notifier.is_configured():
            payload = prediction.to_dict() if hasattr(prediction, 'to_dict') else prediction
            return telegram_notifier.send_prediction_alert(payload)
        return False

    monitor = OddsMonitor(
        odds_loader=flashlive_multi_loader or flashlive_loader,
        prediction_callback=prediction_callback,
        notification_callback=notification_callback,
        check_interval=300,
    )

    set_monitor(monitor)
    return monitor


# ── Startup ──────────────────────────────────────────────────────────────────

_startup_done = False


def startup_initialization():
    """Выполняется один раз при старте приложения."""
    global _startup_done
    if _startup_done:
        return
    _startup_done = True

    import threading
    threading.Thread(target=warmup_multi_league, daemon=True).start()

    # OddsMonitor disabled — AutoMonitor (12h) handles everything with smart
    # pre-filtering.  The old 5-min OddsMonitor fetched odds for ALL ~500
    # matches every cycle, causing 40-50K API calls/day ($200+/month).
    if flashlive_loader and flashlive_loader.is_configured():
        print("✅ FlashLive API configured (odds via AutoMonitor smart filter)")
    else:
        print("⚠️ No odds API configured (need RAPIDAPI_KEY)")


create_app(
    testing=os.environ.get("TESTING", "").lower() in {"1", "true", "yes"},
    start_background=env_flag(
        "START_BACKGROUND",
        os.environ.get("TESTING", "").lower() not in {"1", "true", "yes"},
    ),
)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
