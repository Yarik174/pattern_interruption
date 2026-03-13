"""
Unified Settings for the pattern_interruption system.

All configurable values live here, loaded from environment variables with
sensible defaults that match the old hardcoded values.

DI NOTES (for other agents):
--------------------------------------------------------------
- ``src/odds_monitor`` uses module-level globals ``_global_monitor``,
  ``_monitor_thread_started``, ``_guard`` and setter functions.
  The monitor should instead be stored on the Flask app (``app.extensions``)
  or injected via a factory.
- ``src/routes.py`` keeps ``db``, ``Prediction``, ``odds_monitor``,
  ``telegram_notifier``, ``odds_loader`` as module globals set by
  ``init_routes()`` / ``set_monitor()`` / ``set_telegram()`` /
  ``set_odds_loader()``.  These should be replaced by Blueprint-level
  dependency injection (e.g. ``current_app.extensions['monitor']``).
- ``src/rl_agent.py`` uses ``_rl_agent`` module global with
  ``get_rl_agent()`` singleton.  Should use app-level registry instead.
- ``app.py`` has ``telegram_notifier``, ``odds_loader``,
  ``flashlive_loader``, ``flashlive_loaders``, ``flashlive_multi_loader``
  as module globals.  ``create_app()`` should store them on ``app.extensions``.
--------------------------------------------------------------

Usage
-----
::

    from src.config import settings        # preferred
    # or
    from src.config.settings import Settings
    s = Settings()                          # reads env automatically
    print(s.db.database_url)
    print(s.patterns.critical_thresholds)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str = '') -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ('0', 'false', 'no', 'off', '')


# ---------------------------------------------------------------------------
# Section dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DatabaseSettings:
    """Database connection parameters."""
    database_url: str = ''
    pool_recycle: int = 300
    pool_pre_ping: bool = True
    track_modifications: bool = False

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        url = _env('DATABASE_URL', '')
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        return cls(
            database_url=url,
            pool_recycle=_env_int('DB_POOL_RECYCLE', 300),
            pool_pre_ping=_env_bool('DB_POOL_PRE_PING', True),
        )


@dataclass(frozen=True)
class ApiKeySettings:
    """Third-party API keys (all from env vars, no defaults)."""
    session_secret: str = ''
    rapidapi_key: str = ''
    api_sports_key: str = ''
    odds_api_key: str = ''
    supabase_url: str = ''
    supabase_anon_key: str = ''
    telegram_bot_token: str = ''
    telegram_chat_id: str = ''

    @classmethod
    def from_env(cls) -> ApiKeySettings:
        return cls(
            session_secret=_env('SESSION_SECRET'),
            rapidapi_key=_env('RAPIDAPI_KEY'),
            api_sports_key=_env('API_SPORTS_KEY'),
            odds_api_key=_env('ODDS_API_KEY'),
            supabase_url=_env('SUPABASE_URL'),
            supabase_anon_key=_env('SUPABASE_ANON_KEY'),
            telegram_bot_token=_env('TELEGRAM_BOT_TOKEN'),
            telegram_chat_id=_env('TELEGRAM_CHAT_ID'),
        )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)


@dataclass(frozen=True)
class PatternSettings:
    """Pattern detection thresholds and break rates."""
    # Critical thresholds - minimum streak/alternation lengths to flag
    critical_thresholds: dict[str, int] = field(default_factory=lambda: {
        'overall_streak': 5,
        'home_streak': 4,
        'away_streak': 3,
        'alternation': 6,
        'home_alternation': 6,
        'away_alternation': 6,
        'overall_alternation': 6,
        'h2h': 3,
        'h2h_streak': 3,
        'h2h_alternation': 6,
        'h2h_home_streak': 3,
        'h2h_away_streak': 2,
        'league_home_streak': 5,
    })

    # Empirical pattern break rates
    break_rates: dict[str, float] = field(default_factory=lambda: {
        'overall_alternation': 0.581,
        'home_alternation': 0.556,
        'overall_streak': 0.482,
        'home_streak': 0.469,
        'h2h_streak': 0.468,
        'away_streak': 0.234,
        'h2h_alternation': 0.50,
        'away_alternation': 0.50,
    })

    base_home_win_rate: float = 0.543
    min_games_for_pattern: int = 3
    bayesian_prior_samples: int = 10

    @classmethod
    def from_env(cls) -> PatternSettings:
        return cls(
            base_home_win_rate=_env_float('PATTERN_BASE_HOME_WIN_RATE', 0.543),
            min_games_for_pattern=_env_int('PATTERN_MIN_GAMES', 3),
            bayesian_prior_samples=_env_int('PATTERN_BAYESIAN_PRIOR', 10),
        )


@dataclass(frozen=True)
class ModelSettings:
    """Random Forest model hyperparameters."""
    n_estimators: int = 100
    max_depth: int = 10
    min_samples_split: int = 5
    min_samples_leaf: int = 2
    max_features: str = 'sqrt'
    class_weight: str = 'balanced'
    random_state: int = 42

    @classmethod
    def from_env(cls) -> ModelSettings:
        return cls(
            n_estimators=_env_int('MODEL_N_ESTIMATORS', 100),
            max_depth=_env_int('MODEL_MAX_DEPTH', 10),
            min_samples_split=_env_int('MODEL_MIN_SAMPLES_SPLIT', 5),
            min_samples_leaf=_env_int('MODEL_MIN_SAMPLES_LEAF', 2),
            max_features=_env('MODEL_MAX_FEATURES', 'sqrt'),
            class_weight=_env('MODEL_CLASS_WEIGHT', 'balanced'),
            random_state=_env_int('MODEL_RANDOM_STATE', 42),
        )

    def as_dict(self) -> dict:
        """Return params dict suitable for sklearn constructor."""
        return {
            'n_estimators': self.n_estimators,
            'max_depth': self.max_depth,
            'min_samples_split': self.min_samples_split,
            'min_samples_leaf': self.min_samples_leaf,
            'max_features': self.max_features,
            'class_weight': self.class_weight,
            'random_state': self.random_state,
        }


@dataclass(frozen=True)
class TrainingSettings:
    """Model training configuration."""
    test_size: float = 0.2
    cv_folds: int = 5
    use_grid_search: bool = False
    calibrate_probabilities: bool = True
    break_threshold: float = 0.55
    continuation_threshold: float = 0.70

    @classmethod
    def from_env(cls) -> TrainingSettings:
        return cls(
            test_size=_env_float('TRAIN_TEST_SIZE', 0.2),
            cv_folds=_env_int('TRAIN_CV_FOLDS', 5),
            use_grid_search=_env_bool('TRAIN_GRID_SEARCH', False),
            calibrate_probabilities=_env_bool('TRAIN_CALIBRATE', True),
            break_threshold=_env_float('TRAIN_BREAK_THRESHOLD', 0.55),
            continuation_threshold=_env_float('TRAIN_CONTINUATION_THRESHOLD', 0.70),
        )


@dataclass(frozen=True)
class DataSettings:
    """Data loading configuration."""
    n_seasons: int = 10
    use_cache: bool = True
    cache_dir: str = 'data/cache'

    @classmethod
    def from_env(cls) -> DataSettings:
        return cls(
            n_seasons=_env_int('DATA_N_SEASONS', 10),
            use_cache=_env_bool('DATA_USE_CACHE', True),
            cache_dir=_env('DATA_CACHE_DIR', 'data/cache'),
        )


@dataclass(frozen=True)
class OutputSettings:
    """Artifact output configuration."""
    artifacts_dir: str = 'artifacts'
    save_predictions: bool = True
    save_model: bool = True
    n_prediction_examples: int = 10

    @classmethod
    def from_env(cls) -> OutputSettings:
        return cls(
            artifacts_dir=_env('OUTPUT_ARTIFACTS_DIR', 'artifacts'),
            save_predictions=_env_bool('OUTPUT_SAVE_PREDICTIONS', True),
            save_model=_env_bool('OUTPUT_SAVE_MODEL', True),
            n_prediction_examples=_env_int('OUTPUT_N_EXAMPLES', 10),
        )


@dataclass(frozen=True)
class MonitoringSettings:
    """Odds monitor / auto-monitor configuration."""
    # OddsMonitor (manual)
    odds_check_interval: int = 7200       # seconds (2 hours)
    # AutoMonitor
    auto_check_interval: int = 43200      # seconds (12 hours)
    # Quality gate - odds range for bet candidates
    min_target_odds: float = 2.0
    max_target_odds: float = 3.5
    # Lock file
    monitor_lock_path: str = '/tmp/arena_monitor.lock'

    @classmethod
    def from_env(cls) -> MonitoringSettings:
        return cls(
            odds_check_interval=_env_int('MONITOR_ODDS_INTERVAL', 7200),
            auto_check_interval=_env_int('MONITOR_AUTO_INTERVAL', 43200),
            min_target_odds=_env_float('MONITOR_MIN_ODDS', 2.0),
            max_target_odds=_env_float('MONITOR_MAX_ODDS', 3.5),
            monitor_lock_path=_env('MONITOR_LOCK_PATH', '/tmp/arena_monitor.lock'),
        )


@dataclass(frozen=True)
class LoggingSettings:
    """Logging configuration."""
    log_level: str = 'INFO'
    log_file: str = ''
    log_format: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    @classmethod
    def from_env(cls) -> LoggingSettings:
        return cls(
            log_level=_env('LOG_LEVEL', 'INFO'),
            log_file=_env('LOG_FILE', ''),
            log_format=_env('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        )


# ---------------------------------------------------------------------------
# Top-level Settings aggregate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """Top-level settings object. Aggregates all section configs.

    Usage::

        s = Settings.from_env()
        # or simply
        s = Settings()          # uses defaults (for tests)
    """
    db: DatabaseSettings = field(default_factory=DatabaseSettings)
    api_keys: ApiKeySettings = field(default_factory=ApiKeySettings)
    patterns: PatternSettings = field(default_factory=PatternSettings)
    model: ModelSettings = field(default_factory=ModelSettings)
    training: TrainingSettings = field(default_factory=TrainingSettings)
    data: DataSettings = field(default_factory=DataSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    monitoring: MonitoringSettings = field(default_factory=MonitoringSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)

    @classmethod
    def from_env(cls) -> Settings:
        """Create Settings populated from environment variables."""
        return cls(
            db=DatabaseSettings.from_env(),
            api_keys=ApiKeySettings.from_env(),
            patterns=PatternSettings.from_env(),
            model=ModelSettings.from_env(),
            training=TrainingSettings.from_env(),
            data=DataSettings.from_env(),
            output=OutputSettings.from_env(),
            monitoring=MonitoringSettings.from_env(),
            logging=LoggingSettings.from_env(),
        )

    # ------------------------------------------------------------------
    # Legacy helpers (drop-in replacements for old Config class methods)
    # ------------------------------------------------------------------

    def as_legacy_dict(self) -> dict:
        """Return a dict in the shape of the old ``DEFAULT_CONFIG``."""
        return {
            'data': {
                'n_seasons': self.data.n_seasons,
                'use_cache': self.data.use_cache,
                'cache_dir': self.data.cache_dir,
            },
            'patterns': {
                'critical_thresholds': dict(self.patterns.critical_thresholds),
                'break_rates': dict(self.patterns.break_rates),
                'base_home_win_rate': self.patterns.base_home_win_rate,
                'min_games_for_pattern': self.patterns.min_games_for_pattern,
                'bayesian_prior_samples': self.patterns.bayesian_prior_samples,
            },
            'model': self.model.as_dict(),
            'training': {
                'test_size': self.training.test_size,
                'cv_folds': self.training.cv_folds,
                'use_grid_search': self.training.use_grid_search,
                'calibrate_probabilities': self.training.calibrate_probabilities,
                'break_threshold': self.training.break_threshold,
                'continuation_threshold': self.training.continuation_threshold,
            },
            'output': {
                'artifacts_dir': self.output.artifacts_dir,
                'save_predictions': self.output.save_predictions,
                'save_model': self.output.save_model,
                'n_prediction_examples': self.output.n_prediction_examples,
            },
        }


# ---------------------------------------------------------------------------
# Module-level singleton (lazy, populated on first access)
# ---------------------------------------------------------------------------
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the module-level Settings singleton, creating it from env on first call."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
