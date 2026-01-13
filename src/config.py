import json
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

CRITICAL_THRESHOLDS = {
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
}

PATTERN_BREAK_RATES = {
    'overall_alternation': 0.581,
    'home_alternation': 0.556,
    'overall_streak': 0.482,
    'home_streak': 0.469,
    'h2h_streak': 0.468,
    'away_streak': 0.234,
    'h2h_alternation': 0.50,
    'away_alternation': 0.50,
}

BASE_HOME_WIN_RATE = 0.543

DEFAULT_CONFIG = {
    'data': {
        'n_seasons': 10,
        'use_cache': True,
        'cache_dir': 'data/cache'
    },
    'patterns': {
        'critical_thresholds': CRITICAL_THRESHOLDS,
        'break_rates': PATTERN_BREAK_RATES,
        'base_home_win_rate': BASE_HOME_WIN_RATE,
        'min_games_for_pattern': 3,
        'bayesian_prior_samples': 10,
    },
    'model': {
        'n_estimators': 100,
        'max_depth': 10,
        'min_samples_split': 5,
        'min_samples_leaf': 2,
        'max_features': 'sqrt',
        'class_weight': 'balanced',
        'random_state': 42
    },
    'training': {
        'test_size': 0.2,
        'cv_folds': 5,
        'use_grid_search': False,
        'calibrate_probabilities': True,
        'break_threshold': 0.55,
        'continuation_threshold': 0.70
    },
    'output': {
        'artifacts_dir': 'artifacts',
        'save_predictions': True,
        'save_model': True,
        'n_prediction_examples': 10
    }
}

GRID_SEARCH_PARAMS = {
    'n_estimators': [50, 100, 200],
    'max_depth': [5, 10, 15, None],
    'min_samples_split': [2, 5, 10],
    'min_samples_leaf': [1, 2, 4],
    'max_features': ['sqrt', 'log2'],
    'class_weight': ['balanced', 'balanced_subsample']
}

class Config:
    def __init__(self, config_path=None):
        self.config = DEFAULT_CONFIG.copy()
        self.config_path = config_path or 'config.json'
        self.run_id = None
        
        if os.path.exists(self.config_path):
            self.load()
    
    def load(self):
        try:
            with open(self.config_path, 'r') as f:
                user_config = json.load(f)
            self._merge_config(user_config)
            logger.info(f"Конфигурация загружена из {self.config_path}")
        except Exception as e:
            logger.warning(f"Ошибка загрузки конфигурации: {e}")
    
    def save(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Конфигурация сохранена в {self.config_path}")
        except Exception as e:
            logger.warning(f"Ошибка сохранения конфигурации: {e}")
    
    def _merge_config(self, user_config):
        for section, values in user_config.items():
            if section in self.config and isinstance(values, dict):
                self.config[section].update(values)
            else:
                self.config[section] = values
    
    def get(self, section, key=None, default=None):
        if key is None:
            return self.config.get(section, default)
        return self.config.get(section, {}).get(key, default)
    
    def set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value
    
    def get_model_params(self):
        return self.config['model'].copy()
    
    def get_grid_search_params(self):
        return GRID_SEARCH_PARAMS.copy()
    
    def create_run_id(self):
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.run_id
    
    def get_artifacts_dir(self):
        if not self.run_id:
            self.create_run_id()
        
        artifacts_base = self.config['output']['artifacts_dir']
        run_dir = os.path.join(artifacts_base, self.run_id)
        os.makedirs(run_dir, exist_ok=True)
        return run_dir
    
    def save_run_metadata(self, metadata):
        run_dir = self.get_artifacts_dir()
        metadata_path = os.path.join(run_dir, 'run_metadata.json')
        
        full_metadata = {
            'run_id': self.run_id,
            'timestamp': datetime.now().isoformat(),
            'config': self.config,
            **metadata
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(full_metadata, f, indent=2, default=str)
        
        logger.info(f"Метаданные сохранены в {metadata_path}")
        return metadata_path
    
    def __str__(self):
        return json.dumps(self.config, indent=2)


def setup_logging(log_level=logging.INFO, log_file=None):
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)
    
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_format)
        root_logger.addHandler(file_handler)
    
    return root_logger
