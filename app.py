"""
NHL Pattern Prediction Web Interface
Веб-интерфейс для тестирования прогнозов на реальных матчах
"""

import warnings
warnings.filterwarnings('ignore', category=UserWarning)

from flask import Flask, render_template, jsonify, request, redirect, url_for
import joblib
import pandas as pd
from datetime import datetime, timedelta
import requests
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_loader import NHLDataLoader
from src.pattern_engine import PatternEngine
from src.feature_builder import FeatureBuilder

app = Flask(__name__, static_folder='static')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.environ.get("SESSION_SECRET")

if not app.secret_key:
    raise RuntimeError("SESSION_SECRET environment variable is required. Please set it in the Secrets tab.")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

from models import db, Prediction, UserDecision, ModelVersion, TelegramSettings, OddsMonitorLog
db.init_app(app)

with app.app_context():
    db.create_all()
    
from src.routes import routes_bp, init_routes, set_monitor, set_telegram, set_odds_loader
init_routes(db, {
    'Prediction': Prediction,
    'UserDecision': UserDecision,
    'ModelVersion': ModelVersion,
    'TelegramSettings': TelegramSettings
})
app.register_blueprint(routes_bp)

from src.telegram_bot import TelegramNotifier
from src.apisports_odds_loader import APISportsOddsLoader, get_demo_odds
from src.allbestbets_loader import AllBestBetsLoader, get_demo_matches
from src.flashlive_loader import FlashLiveLoader
from src.odds_monitor import OddsMonitor

telegram_notifier = TelegramNotifier()
odds_loader = APISportsOddsLoader()
allbestbets_loader = AllBestBetsLoader()
flashlive_loader = FlashLiveLoader()
set_telegram(telegram_notifier)
set_odds_loader(flashlive_loader)  # FlashLive as primary source (281 matches vs 1 from AllBestBets)

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

data_loader = None
pattern_engine = None
feature_builder = None
model = None
all_games = None
feature_names = None
odds_cache = {}
odds_cache_time = None

ODDS_API_KEY = os.environ.get('ODDS_API_KEY')

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
    'UTA': ['Utah Hockey Club', 'Utah HC'],
    'VAN': ['Vancouver Canucks', 'Canucks'],
    'VGK': ['Vegas Golden Knights', 'Golden Knights'],
    'WSH': ['Washington Capitals', 'Capitals'],
    'WPG': ['Winnipeg Jets', 'Jets']
}

def get_abbrev_from_full_name(full_name):
    """Конвертировать полное название команды в аббревиатуру"""
    full_name_lower = full_name.lower()
    for abbrev, names in NHL_TEAM_MAPPING.items():
        for name in names:
            if name.lower() in full_name_lower or full_name_lower in name.lower():
                return abbrev
    return None

def init_system():
    """Инициализация системы при первом запросе"""
    global data_loader, pattern_engine, feature_builder, model, all_games, feature_names
    
    if data_loader is None:
        print("🔄 Инициализация системы...")
        data_loader = NHLDataLoader()
        pattern_engine = PatternEngine()
        feature_builder = FeatureBuilder(pattern_engine)
        
        print("📥 Загрузка исторических данных...")
        seasons = NHLDataLoader.get_default_seasons(n_seasons=10)
        all_games = data_loader.load_all_data(seasons=seasons)
        
        print("🔍 Анализ паттернов...")
        pattern_engine.analyze_all_patterns(all_games)
        
        model_path = None
        latest_artifact = get_latest_artifact()
        if latest_artifact:
            model_path = f"{latest_artifact}/model.pkl"
        
        if model_path and os.path.exists(model_path):
            print(f"📦 Загрузка модели из {model_path}...")
            model_data = joblib.load(model_path)
            model = model_data.get('model') if isinstance(model_data, dict) else model_data
            print("✅ Модель загружена!")
            
            if hasattr(model, 'feature_names_in_'):
                feature_names = list(model.feature_names_in_)
                print(f"📋 Загружено {len(feature_names)} признаков из модели")
            else:
                fi_path = model_path.replace('model.pkl', 'feature_importance.csv')
                if os.path.exists(fi_path):
                    fi_df = pd.read_csv(fi_path)
                    feature_names = fi_df['feature'].tolist()
                    print(f"📋 Загружено {len(feature_names)} признаков из CSV")
        
        print("✅ Система инициализирована!")

def get_latest_artifact():
    """Получить путь к последнему артефакту (только папки с датой)"""
    artifacts_dir = "artifacts"
    if not os.path.exists(artifacts_dir):
        return None
    
    dirs = [d for d in os.listdir(artifacts_dir) 
            if os.path.isdir(os.path.join(artifacts_dir, d)) 
            and d.startswith('202')]
    if not dirs:
        return None
    
    dirs.sort(reverse=True)
    return os.path.join(artifacts_dir, dirs[0])

def fetch_odds():
    """Получить коэффициенты NHL из The Odds API"""
    global odds_cache, odds_cache_time
    
    if odds_cache_time and (datetime.now() - odds_cache_time).seconds < 300:
        return odds_cache
    
    if not ODDS_API_KEY:
        print("⚠️ ODDS_API_KEY не установлен")
        return {}
    
    try:
        url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'us,eu',
            'markets': 'h2h',
            'oddsFormat': 'decimal'
        }
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            print(f"📊 Загружено {len(data)} матчей с коэффициентами")
            
            odds_dict = {}
            for game in data:
                home_abbrev = get_abbrev_from_full_name(game.get('home_team', ''))
                away_abbrev = get_abbrev_from_full_name(game.get('away_team', ''))
                
                if not home_abbrev or not away_abbrev:
                    continue
                
                game_key = f"{home_abbrev}_{away_abbrev}"
                
                best_home_odds = 0
                best_away_odds = 0
                bookmaker_name = None
                
                for bookmaker in game.get('bookmakers', []):
                    for market in bookmaker.get('markets', []):
                        if market.get('key') == 'h2h':
                            outcomes = market.get('outcomes', [])
                            for outcome in outcomes:
                                price = outcome.get('price', 0)
                                name = outcome.get('name', '')
                                
                                home_match = get_abbrev_from_full_name(name) == home_abbrev
                                away_match = get_abbrev_from_full_name(name) == away_abbrev
                                
                                if home_match and price > best_home_odds:
                                    best_home_odds = price
                                    bookmaker_name = bookmaker.get('title')
                                elif away_match and price > best_away_odds:
                                    best_away_odds = price
                
                if best_home_odds > 0 or best_away_odds > 0:
                    odds_dict[game_key] = {
                        'home_odds': best_home_odds,
                        'away_odds': best_away_odds,
                        'bookmaker': bookmaker_name,
                        'home_team_full': game.get('home_team'),
                        'away_team_full': game.get('away_team'),
                        'commence_time': game.get('commence_time')
                    }
            
            odds_cache = odds_dict
            odds_cache_time = datetime.now()
            print(f"✅ Кэшировано {len(odds_dict)} матчей с коэффициентами")
            return odds_dict
        else:
            print(f"❌ Ошибка API коэффициентов: {response.status_code}")
            return {}
    except Exception as e:
        print(f"❌ Ошибка загрузки коэффициентов: {e}")
        return {}

def get_upcoming_games():
    """Получить предстоящие матчи NHL"""
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"https://api-web.nhle.com/v1/schedule/{today}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            games = []
            
            for game_week in data.get('gameWeek', []):
                for game in game_week.get('games', []):
                    if game.get('gameState') in ['FUT', 'PRE']:
                        games.append({
                            'id': game.get('id'),
                            'date': game_week.get('date'),
                            'time': game.get('startTimeUTC'),
                            'home_team': game.get('homeTeam', {}).get('abbrev'),
                            'home_team_name': game.get('homeTeam', {}).get('placeName', {}).get('default', ''),
                            'away_team': game.get('awayTeam', {}).get('abbrev'),
                            'away_team_name': game.get('awayTeam', {}).get('placeName', {}).get('default', ''),
                            'venue': game.get('venue', {}).get('default', '')
                        })
            
            return games
    except Exception as e:
        print(f"Ошибка загрузки расписания: {e}")
    
    return []

def analyze_game(home_team, away_team):
    """Анализ паттернов для матча"""
    init_system()
    
    game_date = datetime.now()
    
    home_features = pattern_engine.get_pattern_features(
        home_team, away_team, all_games, game_date
    )
    
    away_features = pattern_engine.get_pattern_features(
        away_team, home_team, all_games, game_date
    )
    
    if home_features is None or away_features is None:
        return None
    
    home_synergy = sum([
        home_features.get('home_streak_critical', 0),
        home_features.get('h2h_streak_critical', 0),
        home_features.get('overall_streak_critical', 0),
        home_features.get('home_alt_critical', 0),
        home_features.get('h2h_alt_critical', 0),
        home_features.get('overall_alt_critical', 0)
    ])
    
    away_synergy = sum([
        away_features.get('away_streak_critical', 0),
        away_features.get('h2h_streak_critical', 0),
        away_features.get('overall_streak_critical', 0),
        away_features.get('away_alt_critical', 0),
        away_features.get('h2h_alt_critical', 0),
        away_features.get('overall_alt_critical', 0)
    ])
    
    home_alt_combo = sum([
        1 if home_features.get('home_alt_critical', 0) else 0,
        1 if home_features.get('h2h_alt_critical', 0) else 0,
        1 if home_features.get('overall_alt_critical', 0) else 0
    ])
    
    away_alt_combo = sum([
        1 if away_features.get('away_alt_critical', 0) else 0,
        1 if away_features.get('h2h_alt_critical', 0) else 0,
        1 if away_features.get('overall_alt_critical', 0) else 0
    ])
    
    def calc_overgrowth(features):
        max_len = features.get('max_streak_len', 0)
        if max_len >= 8:
            return 3
        elif max_len >= 7:
            return 2
        elif max_len >= 6:
            return 1
        return 0
    
    home_overgrowth = calc_overgrowth(home_features)
    away_overgrowth = calc_overgrowth(away_features)
    
    def get_cpp_prediction(home_f, away_f):
        """
        CPP логика:
        - Серия: прерывание = противоположный результат
        - Чередование: прерывание = повтор последнего
        """
        home_preds = []
        away_preds = []
        
        home_streak = home_f.get('home_win_streak', 0)
        if home_f.get('home_streak_critical', 0):
            if home_streak > 0:
                away_preds.append({'type': 'home_streak', 'reason': f'Прерывание домашней серии побед ({home_streak})'})
            elif home_streak < 0:
                home_preds.append({'type': 'home_streak', 'reason': f'Прерывание домашней серии поражений ({home_streak})'})
        
        overall_streak = home_f.get('overall_win_streak', 0)
        if home_f.get('overall_streak_critical', 0):
            if overall_streak > 0:
                away_preds.append({'type': 'overall_streak', 'reason': f'Прерывание общей серии побед хозяев ({overall_streak})'})
            elif overall_streak < 0:
                home_preds.append({'type': 'overall_streak', 'reason': f'Прерывание общей серии поражений хозяев ({overall_streak})'})
        
        if home_f.get('home_alt_critical', 0):
            last = home_f.get('home_last_result', 0)
            if last == 1:
                home_preds.append({'type': 'home_alt', 'reason': 'Прерывание чередования дома (последний W → W)'})
            else:
                away_preds.append({'type': 'home_alt', 'reason': 'Прерывание чередования дома (последний L → L)'})
        
        if home_f.get('overall_alt_critical', 0):
            last = home_f.get('overall_last_result', 0)
            if last == 1:
                home_preds.append({'type': 'overall_alt', 'reason': 'Прерывание общего чередования хозяев (последний W → W)'})
            else:
                away_preds.append({'type': 'overall_alt', 'reason': 'Прерывание общего чередования хозяев (последний L → L)'})
        
        away_streak = away_f.get('away_win_streak', 0)
        if away_f.get('away_streak_critical', 0):
            if away_streak > 0:
                home_preds.append({'type': 'away_streak', 'reason': f'Прерывание гостевой серии побед ({away_streak})'})
            elif away_streak < 0:
                away_preds.append({'type': 'away_streak', 'reason': f'Прерывание гостевой серии поражений ({away_streak})'})
        
        away_overall = away_f.get('overall_win_streak', 0)
        if away_f.get('overall_streak_critical', 0):
            if away_overall > 0:
                home_preds.append({'type': 'away_overall', 'reason': f'Прерывание общей серии побед гостей ({away_overall})'})
            elif away_overall < 0:
                away_preds.append({'type': 'away_overall', 'reason': f'Прерывание общей серии поражений гостей ({away_overall})'})
        
        if away_f.get('overall_alt_critical', 0):
            last = away_f.get('overall_last_result', 0)
            if last == 1:
                away_preds.append({'type': 'away_alt', 'reason': 'Прерывание общего чередования гостей (последний W → W)'})
            else:
                home_preds.append({'type': 'away_alt', 'reason': 'Прерывание общего чередования гостей (последний L → L)'})
        
        h2h_streak = home_f.get('h2h_win_streak', 0)
        if home_f.get('h2h_streak_critical', 0):
            if h2h_streak > 0:
                away_preds.append({'type': 'h2h_streak', 'reason': f'Прерывание серии H2H ({h2h_streak})'})
            elif h2h_streak < 0:
                home_preds.append({'type': 'h2h_streak', 'reason': f'Прерывание серии H2H ({h2h_streak})'})
        
        if home_f.get('h2h_alt_critical', 0):
            last = home_f.get('h2h_last_result', 0)
            if last == 1:
                home_preds.append({'type': 'h2h_alt', 'reason': 'Прерывание чередования H2H (последний W → W)'})
            else:
                away_preds.append({'type': 'h2h_alt', 'reason': 'Прерывание чередования H2H (последний L → L)'})
        
        home_synergy_count = len(home_preds)
        away_synergy_count = len(away_preds)
        
        if home_synergy_count > away_synergy_count:
            return {'team': 'home', 'synergy': home_synergy_count, 'patterns': home_preds}
        elif away_synergy_count > home_synergy_count:
            return {'team': 'away', 'synergy': away_synergy_count, 'patterns': away_preds}
        else:
            return {'team': None, 'synergy': 0, 'patterns': []}
    
    cpp_prediction = get_cpp_prediction(home_features, away_features)
    
    def calc_strong_signal(synergy, alt_combo, overgrowth):
        score = 0
        if synergy >= 2:
            score += synergy
        if alt_combo >= 1:
            score += alt_combo
        score += overgrowth
        return min(score, 6)
    
    home_strong = calc_strong_signal(home_synergy, home_alt_combo, home_overgrowth)
    away_strong = calc_strong_signal(away_synergy, away_alt_combo, away_overgrowth)
    
    analysis = {
        'home_team': home_team,
        'away_team': away_team,
        'patterns': {},
        'strong_signal': {
            'home': home_strong,
            'away': away_strong,
            'max': max(home_strong, away_strong)
        },
        'cpp_prediction': {
            'team': cpp_prediction['team'],
            'synergy': cpp_prediction['synergy'],
            'patterns': [p['reason'] for p in cpp_prediction['patterns']],
            'bet_recommendation': home_team if cpp_prediction['team'] == 'home' and cpp_prediction['synergy'] >= 2 else (
                away_team if cpp_prediction['team'] == 'away' and cpp_prediction['synergy'] >= 2 else None
            )
        },
        'prediction': None
    }
    
    analysis['patterns']['home'] = {
        'win_streak': home_features.get('home_win_streak', 0),
        'overall_streak': home_features.get('overall_win_streak', 0),
        'any_critical': 1 if home_synergy > 0 else 0,
        'synergy': home_synergy,
        'alternation_combo': home_alt_combo,
        'overgrowth': home_overgrowth,
        'max_alternation_len': home_features.get('max_alternation_len', 0)
    }
    
    analysis['patterns']['away'] = {
        'win_streak': away_features.get('away_win_streak', 0),
        'overall_streak': away_features.get('overall_win_streak', 0),
        'any_critical': 1 if away_synergy > 0 else 0,
        'synergy': away_synergy,
        'alternation_combo': away_alt_combo,
        'overgrowth': away_overgrowth,
        'max_alternation_len': away_features.get('max_alternation_len', 0)
    }
    
    if model is not None:
        try:
            combined_features = {}
            for key, value in home_features.items():
                combined_features[f'home_{key}'] = value
            for key, value in away_features.items():
                combined_features[f'away_{key}'] = value
            
            combined_features['streak_diff'] = home_features.get('overall_win_streak', 0) - away_features.get('overall_win_streak', 0)
            combined_features['h2h_advantage'] = home_features.get('h2h_last_5_wins', 0) - away_features.get('h2h_last_5_wins', 0)
            combined_features['home_any_critical'] = 1 if home_synergy > 0 else 0
            combined_features['away_any_critical'] = 1 if away_synergy > 0 else 0
            combined_features['home_total_critical'] = home_features.get('total_critical_patterns', 0)
            combined_features['away_total_critical'] = away_features.get('total_critical_patterns', 0)
            combined_features['max_streak_len'] = max(home_features.get('max_streak_len', 0), away_features.get('max_streak_len', 0))
            combined_features['max_alternation_len'] = max(home_features.get('max_alternation_len', 0), away_features.get('max_alternation_len', 0))
            combined_features['synergy_home'] = home_synergy
            combined_features['synergy_away'] = away_synergy
            combined_features['critical_synergy_home'] = home_synergy
            combined_features['critical_synergy_away'] = away_synergy
            combined_features['aligned_patterns_home'] = 0
            combined_features['aligned_patterns_away'] = 0
            combined_features['total_aligned'] = 0
            combined_features['pattern_agreement'] = 0
            combined_features['critical_pattern_exists'] = 1 if (home_synergy > 0 or away_synergy > 0) else 0
            combined_features['home_streak_overgrowth'] = home_overgrowth
            combined_features['away_streak_overgrowth'] = away_overgrowth
            combined_features['max_overgrowth'] = max(home_overgrowth, away_overgrowth)
            combined_features['home_alternation_combo'] = home_alt_combo
            combined_features['away_alternation_combo'] = away_alt_combo
            combined_features['max_alternation_combo'] = max(home_alt_combo, away_alt_combo)
            combined_features['home_strong_signal'] = home_strong
            combined_features['away_strong_signal'] = away_strong
            combined_features['any_strong_signal'] = max(home_strong, away_strong)
            
            X_dict = {name: combined_features.get(name, 0) for name in feature_names}
            X = pd.DataFrame([X_dict])[feature_names]
            
            proba = model.predict_proba(X)[0]
            home_prob = proba[1] if len(proba) > 1 else proba[0]
            
            analysis['prediction'] = {
                'home_probability': round(home_prob * 100, 1),
                'away_probability': round((1 - home_prob) * 100, 1),
                'predicted_winner': 'home' if home_prob >= 0.5 else 'away',
                'recommendation': home_team if home_prob >= 0.5 else away_team
            }
        except Exception as e:
            print(f"Ошибка предсказания: {e}")
            import traceback
            traceback.print_exc()
    
    return analysis

@app.route('/')
def index():
    """Главная страница - перенаправление на прогнозы"""
    return redirect(url_for('routes.predictions_page'))

@app.route('/api/upcoming')
def api_upcoming():
    """API: предстоящие матчи"""
    games = get_upcoming_games()
    return jsonify({'matches': games})

@app.route('/api/analyze/<home_team>/<away_team>')
def api_analyze(home_team, away_team):
    """API: анализ матча"""
    analysis = analyze_game(home_team.upper(), away_team.upper())
    if analysis:
        return jsonify(analysis)
    return jsonify({'error': 'Не удалось проанализировать матч'}), 400

@app.route('/api/analyze-all')
def api_analyze_all():
    """API: анализ всех предстоящих матчей"""
    games = get_upcoming_games()
    odds_data = fetch_odds()
    results = []
    
    for game in games:
        analysis = analyze_game(game['home_team'], game['away_team'])
        if analysis:
            analysis['game_info'] = game
            
            game_key = f"{game['home_team']}_{game['away_team']}"
            if game_key in odds_data:
                odds = odds_data[game_key]
                analysis['odds'] = {
                    'home': odds['home_odds'],
                    'away': odds['away_odds'],
                    'bookmaker': odds['bookmaker']
                }
                
                if analysis.get('prediction'):
                    home_prob = analysis['prediction']['home_probability'] / 100
                    away_prob = analysis['prediction']['away_probability'] / 100
                    home_odds = odds['home_odds']
                    away_odds = odds['away_odds']
                    
                    predicted_winner = analysis['prediction']['predicted_winner']
                    
                    if predicted_winner == 'home':
                        bet_team = 'home'
                        bet_prob = home_prob
                        bet_odds = home_odds
                        bet_reasoning = f"Модель прогнозирует победу {analysis['home_team']} ({home_prob*100:.0f}%)"
                    else:
                        bet_team = 'away'
                        bet_prob = away_prob
                        bet_odds = away_odds
                        bet_reasoning = f"Модель прогнозирует победу {analysis['away_team']} ({away_prob*100:.0f}%)"
                    
                    ev = (bet_prob * (bet_odds - 1)) - (1 - bet_prob)
                    analysis['odds']['target'] = bet_team
                    analysis['odds']['target_odds'] = bet_odds
                    analysis['odds']['reasoning'] = bet_reasoning
                    analysis['odds']['ev'] = round(ev * 100, 1)
                    analysis['odds']['profitable'] = bool(ev > 0)
            
            results.append(analysis)
    
    results.sort(key=lambda x: x['strong_signal']['max'], reverse=True)
    
    return jsonify({'matches': results, 'odds_available': len(odds_data) > 0})

@app.route('/api/odds')
def api_odds():
    """API: получить коэффициенты"""
    odds_data = fetch_odds()
    return jsonify({'odds': odds_data, 'count': len(odds_data)})

multi_league_engine = None

def init_multi_league():
    """Инициализация мульти-лигового движка"""
    global multi_league_engine
    
    if multi_league_engine is None:
        from src.multi_league_predictor import MultiLeaguePatternEngine
        print("🌍 Инициализация мульти-лигового движка...")
        multi_league_engine = MultiLeaguePatternEngine(critical_length=5)
        multi_league_engine.load_leagues(['KHL', 'SHL', 'Liiga', 'DEL'], n_seasons=4)
        print("✅ Мульти-лиговый движок готов!")
    
    return multi_league_engine

def warmup_multi_league():
    """Предзагрузка данных мульти-лиг при старте сервера"""
    try:
        print("🔄 Предзагрузка данных европейских лиг...")
        init_multi_league()
        print("✅ Предзагрузка завершена")
    except Exception as e:
        print(f"⚠️ Ошибка предзагрузки: {e}")

@app.route('/api/multi-league/summary')
def api_multi_league_summary():
    """API: сводка по всем лигам"""
    engine = init_multi_league()
    
    summary = {}
    for league in ['KHL', 'SHL', 'Liiga', 'DEL']:
        patterns = engine.analyze_team_patterns(league)
        
        critical_teams = []
        for team, pat in patterns.items():
            if pat.get('overall_critical') or pat.get('alt_critical'):
                score = engine.calc_strong_signal(pat)
                critical_teams.append({
                    'team': team,
                    'streak': pat.get('overall_streak', 0),
                    'alt': pat.get('overall_alt', 0),
                    'score': score
                })
        
        critical_teams.sort(key=lambda x: abs(x['streak']), reverse=True)
        
        summary[league] = {
            'total_teams': len(patterns),
            'critical_teams': critical_teams[:10],
            'critical_count': len(critical_teams)
        }
    
    return jsonify(summary)

@app.route('/api/multi-league/upcoming')
def api_multi_league_upcoming():
    """API: предстоящие матчи всех лиг с анализом"""
    engine = init_multi_league()
    
    leagues = ['KHL', 'SHL', 'Liiga', 'DEL']
    analyzed = engine.get_all_upcoming_with_analysis(leagues, include_odds=True)
    
    result = {
        'matches': [],
        'leagues': {}
    }
    
    for m in analyzed:
        match_info = {
            'league': m['league'],
            'home_team': m['home_team'],
            'away_team': m['away_team'],
            'date': m.get('date'),
            'time': m.get('time'),
            'home_score': m.get('home_score', 0),
            'away_score': m.get('away_score', 0),
            'max_score': m.get('max_score', 0),
            'home_streak': m.get('home_pattern', {}).get('overall_streak', 0),
            'away_streak': m.get('away_pattern', {}).get('overall_streak', 0),
            'recommendation': m.get('recommendation', ''),
            'odds': m.get('odds'),
            'ev': m.get('ev')
        }
        result['matches'].append(match_info)
        
        league = m['league']
        if league not in result['leagues']:
            result['leagues'][league] = 0
        result['leagues'][league] += 1
    
    return jsonify(result)

@app.route('/api/multi-league/analyze/<league>/<home>/<away>')
def api_multi_league_analyze(league, home, away):
    """API: анализ конкретного матча в лиге"""
    engine = init_multi_league()
    
    if league not in ['KHL', 'SHL', 'Liiga', 'DEL', 'NHL']:
        return jsonify({'error': 'Неизвестная лига'}), 400
    
    analysis = engine.analyze_match(league, home, away)
    
    return jsonify(analysis)


euro_league_engine = None
euro_league_data = {}

def init_euro_leagues():
    """Инициализация движка европейских лиг"""
    global euro_league_engine, euro_league_data
    
    if euro_league_engine is None:
        from src.euro_league_loader import EuroLeagueLoader, EURO_LEAGUES
        print("🏒 Инициализация европейских лиг...")
        
        loader = EuroLeagueLoader()
        euro_league_data = loader.load_all_european_leagues(n_seasons=4)
        
        euro_league_engine = PatternEngine()
        
        for league_name, df in euro_league_data.items():
            if not df.empty:
                euro_league_engine.analyze_all_patterns(df)
                print(f"✅ {league_name}: паттерны проанализированы")
        
        print("✅ Европейские лиги готовы!")
    
    return euro_league_engine, euro_league_data


def get_euro_cpp_signals(league_name, home_team, away_team):
    """Получить CPP сигналы для матча европейской лиги"""
    engine, data = init_euro_leagues()
    
    if league_name not in data or data[league_name].empty:
        return None
    
    league_df = data[league_name]
    
    if league_df['date'].dtype.tz is not None:
        from datetime import timezone
        game_date = datetime.now(timezone.utc)
    else:
        game_date = datetime.now()
    
    home_features = engine.get_pattern_features(home_team, away_team, league_df, game_date)
    away_features = engine.get_pattern_features(away_team, home_team, league_df, game_date)
    
    if home_features is None or away_features is None:
        return None
    
    home_synergy = sum([
        home_features.get('home_streak_critical', 0),
        home_features.get('h2h_streak_critical', 0),
        home_features.get('overall_streak_critical', 0),
        home_features.get('home_alt_critical', 0),
        home_features.get('h2h_alt_critical', 0),
        home_features.get('overall_alt_critical', 0)
    ])
    
    away_synergy = sum([
        away_features.get('away_streak_critical', 0),
        away_features.get('h2h_streak_critical', 0),
        away_features.get('overall_streak_critical', 0),
        away_features.get('away_alt_critical', 0),
        away_features.get('h2h_alt_critical', 0),
        away_features.get('overall_alt_critical', 0)
    ])
    
    home_alt_combo = sum([
        1 if home_features.get('home_alt_critical', 0) else 0,
        1 if home_features.get('h2h_alt_critical', 0) else 0,
        1 if home_features.get('overall_alt_critical', 0) else 0
    ])
    
    away_alt_combo = sum([
        1 if away_features.get('away_alt_critical', 0) else 0,
        1 if away_features.get('h2h_alt_critical', 0) else 0,
        1 if away_features.get('overall_alt_critical', 0) else 0
    ])
    
    def calc_overgrowth(features):
        max_len = features.get('max_streak_len', 0)
        if max_len >= 8:
            return 3
        elif max_len >= 7:
            return 2
        elif max_len >= 6:
            return 1
        return 0
    
    home_overgrowth = calc_overgrowth(home_features)
    away_overgrowth = calc_overgrowth(away_features)
    
    def calc_strong_signal(synergy, alt_combo, overgrowth):
        score = 0
        if synergy >= 2:
            score += synergy
        if alt_combo >= 1:
            score += alt_combo
        score += overgrowth
        return min(score, 6)
    
    home_strong = calc_strong_signal(home_synergy, home_alt_combo, home_overgrowth)
    away_strong = calc_strong_signal(away_synergy, away_alt_combo, away_overgrowth)
    
    cpp_patterns = []
    predicted_team = None
    
    home_streak = home_features.get('overall_win_streak', 0)
    if home_features.get('overall_streak_critical', 0):
        if home_streak > 0:
            cpp_patterns.append(f'Прерывание серии побед хозяев ({home_streak})')
            predicted_team = 'away'
        elif home_streak < 0:
            cpp_patterns.append(f'Прерывание серии поражений хозяев ({home_streak})')
            predicted_team = 'home'
    
    away_streak = away_features.get('overall_win_streak', 0)
    if away_features.get('overall_streak_critical', 0):
        if away_streak > 0:
            cpp_patterns.append(f'Прерывание серии побед гостей ({away_streak})')
            if predicted_team is None:
                predicted_team = 'home'
        elif away_streak < 0:
            cpp_patterns.append(f'Прерывание серии поражений гостей ({away_streak})')
            if predicted_team is None:
                predicted_team = 'away'
    
    if home_features.get('home_alt_critical', 0):
        cpp_patterns.append('Критическое чередование хозяев дома')
    if away_features.get('overall_alt_critical', 0):
        cpp_patterns.append('Критическое чередование гостей')
    
    synergy_count = len(cpp_patterns)
    
    return {
        'home_team': home_team,
        'away_team': away_team,
        'patterns': {
            'home': {
                'win_streak': home_features.get('home_win_streak', 0),
                'overall_streak': home_features.get('overall_win_streak', 0),
                'synergy': home_synergy,
                'alternation_combo': home_alt_combo,
                'overgrowth': home_overgrowth
            },
            'away': {
                'win_streak': away_features.get('away_win_streak', 0),
                'overall_streak': away_features.get('overall_win_streak', 0),
                'synergy': away_synergy,
                'alternation_combo': away_alt_combo,
                'overgrowth': away_overgrowth
            }
        },
        'strong_signal': {
            'home': home_strong,
            'away': away_strong,
            'max': max(home_strong, away_strong)
        },
        'cpp_prediction': {
            'team': predicted_team,
            'synergy': synergy_count,
            'patterns': cpp_patterns,
            'bet_recommendation': (home_team if predicted_team == 'home' else 
                                   away_team if predicted_team == 'away' else None) if synergy_count >= 2 else None
        }
    }


euro_odds_cache = {}
euro_odds_cache_time = None


def fetch_european_odds():
    """Получить коэффициенты для Liiga и SHL"""
    global euro_odds_cache, euro_odds_cache_time
    
    if euro_odds_cache_time and (datetime.now() - euro_odds_cache_time).seconds < 300:
        return euro_odds_cache
    
    if not ODDS_API_KEY:
        print("⚠️ ODDS_API_KEY не установлен")
        return {}
    
    leagues = {
        'Liiga': 'icehockey_liiga',
        'SHL': 'icehockey_sweden_hockey_league'
    }
    
    all_odds = {}
    
    for league_name, sport_key in leagues.items():
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            params = {
                'apiKey': ODDS_API_KEY,
                'regions': 'eu',
                'markets': 'h2h',
                'oddsFormat': 'decimal'
            }
            
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                print(f"📊 {league_name}: {len(data)} матчей с odds")
                
                league_odds = {}
                for game in data:
                    home_team = game.get('home_team', '')
                    away_team = game.get('away_team', '')
                    
                    best_home = 0
                    best_away = 0
                    bookmaker = None
                    
                    for bm in game.get('bookmakers', []):
                        for market in bm.get('markets', []):
                            if market.get('key') == 'h2h':
                                for outcome in market.get('outcomes', []):
                                    price = outcome.get('price', 0)
                                    name = outcome.get('name', '')
                                    if name == home_team and price > best_home:
                                        best_home = price
                                        bookmaker = bm.get('title')
                                    elif name == away_team and price > best_away:
                                        best_away = price
                    
                    if best_home > 0 or best_away > 0:
                        league_odds[f"{home_team}_{away_team}"] = {
                            'home_odds': best_home,
                            'away_odds': best_away,
                            'bookmaker': bookmaker,
                            'home_team': home_team,
                            'away_team': away_team,
                            'commence_time': game.get('commence_time')
                        }
                
                all_odds[league_name] = league_odds
                
            elif response.status_code == 404:
                print(f"⚠️ {league_name}: нет матчей")
                all_odds[league_name] = {}
            else:
                print(f"❌ {league_name}: ошибка {response.status_code}")
                all_odds[league_name] = {}
                
        except Exception as e:
            print(f"❌ Ошибка {league_name}: {e}")
            all_odds[league_name] = {}
    
    euro_odds_cache = all_odds
    euro_odds_cache_time = datetime.now()
    return all_odds


def match_euro_odds(home_team, away_team, league_odds):
    """Найти коэффициенты для матча"""
    if not league_odds:
        return None
    
    home_lower = home_team.lower()
    away_lower = away_team.lower()
    
    for key, odds in league_odds.items():
        odds_home = odds.get('home_team', '').lower()
        odds_away = odds.get('away_team', '').lower()
        
        if (home_lower in odds_home or odds_home in home_lower) and \
           (away_lower in odds_away or odds_away in away_lower):
            return odds
        
        home_parts = home_lower.split()
        away_parts = away_lower.split()
        
        for part in home_parts:
            if len(part) > 3 and part in odds_home:
                for apart in away_parts:
                    if len(apart) > 3 and apart in odds_away:
                        return odds
    
    return None


@app.route('/api/european_matches')
def api_european_matches():
    """API: матчи европейских лиг с CPP анализом"""
    engine, data = init_euro_leagues()
    
    euro_odds = fetch_european_odds()
    
    results = {
        'KHL': {'matches': [], 'has_odds': False},
        'SHL': {'matches': [], 'has_odds': True},
        'Liiga': {'matches': [], 'has_odds': True},
        'DEL': {'matches': [], 'has_odds': False}
    }
    
    for league_name, df in data.items():
        if df.empty:
            continue
        
        teams = list(set(df['home_team'].unique()) | set(df['away_team'].unique()))
        
        for team in teams[:20]:
            team_games = df[
                (df['home_team'] == team) | (df['away_team'] == team)
            ].sort_values('date').tail(10)
            
            if len(team_games) >= 5:
                last_game = team_games.iloc[-1]
                home = last_game['home_team']
                away = last_game['away_team']
                
                analysis = get_euro_cpp_signals(league_name, home, away)
                if analysis and analysis['strong_signal']['max'] >= 2:
                    match_data = {
                        'home': home,
                        'away': away,
                        'score': analysis['strong_signal']['max'],
                        'home_streak': analysis['patterns']['home']['overall_streak'],
                        'away_streak': analysis['patterns']['away']['overall_streak'],
                        'home_synergy': analysis['patterns']['home']['synergy'],
                        'away_synergy': analysis['patterns']['away']['synergy'],
                        'home_alt': analysis['patterns']['home']['alternation_combo'],
                        'away_alt': analysis['patterns']['away']['alternation_combo'],
                        'cpp_prediction': analysis['cpp_prediction'],
                        'odds': None,
                        'ev': None
                    }
                    
                    if league_name in euro_odds:
                        odds = match_euro_odds(home, away, euro_odds[league_name])
                        if odds:
                            match_data['odds'] = {
                                'home': odds['home_odds'],
                                'away': odds['away_odds'],
                                'bookmaker': odds['bookmaker']
                            }
                            
                            cpp = analysis['cpp_prediction']
                            if cpp['synergy'] >= 2 and cpp['team']:
                                bet_odds = odds['home_odds'] if cpp['team'] == 'home' else odds['away_odds']
                                if bet_odds > 0:
                                    prob = 0.55 + (cpp['synergy'] - 2) * 0.05
                                    ev = (prob * (bet_odds - 1)) - (1 - prob)
                                    match_data['ev'] = round(ev * 100, 1)
                                    match_data['odds']['ev'] = round(ev * 100, 1)
                                    match_data['odds']['profitable'] = ev > 0
                                    match_data['odds']['target'] = cpp['team']
                                    match_data['odds']['reasoning'] = f"CPP: {cpp['team']} (синергия {cpp['synergy']})"
                    
                    results[league_name]['matches'].append(match_data)
        
        results[league_name]['matches'].sort(key=lambda x: x['score'], reverse=True)
        results[league_name]['matches'] = results[league_name]['matches'][:10]
    
    return jsonify(results)


@app.route('/api/european_matches/<league>')
def api_european_matches_by_league(league):
    """API: матчи конкретной европейской лиги"""
    league_upper = league.upper()
    
    if league_upper == 'LIIGA':
        league_upper = 'Liiga'
    elif league_upper not in ['KHL', 'SHL', 'DEL']:
        return jsonify({'error': 'Неизвестная лига'}), 400
    
    engine, data = init_euro_leagues()
    
    if league_upper not in data or data[league_upper].empty:
        return jsonify({'matches': [], 'error': 'Нет данных для лиги'})
    
    df = data[league_upper]
    euro_odds = fetch_european_odds()
    league_odds = euro_odds.get(league_upper, {})
    
    matches = []
    teams = list(set(df['home_team'].unique()) | set(df['away_team'].unique()))
    
    processed_pairs = set()
    
    for team in teams:
        team_games = df[
            (df['home_team'] == team) | (df['away_team'] == team)
        ].sort_values('date').tail(5)
        
        if len(team_games) >= 3:
            last_game = team_games.iloc[-1]
            home = last_game['home_team']
            away = last_game['away_team']
            
            pair_key = f"{min(home, away)}_{max(home, away)}"
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)
            
            analysis = get_euro_cpp_signals(league_upper, home, away)
            if analysis:
                match_data = {
                    'home': home,
                    'away': away,
                    'score': analysis['strong_signal']['max'],
                    'home_streak': analysis['patterns']['home']['overall_streak'],
                    'away_streak': analysis['patterns']['away']['overall_streak'],
                    'home_synergy': analysis['patterns']['home']['synergy'],
                    'away_synergy': analysis['patterns']['away']['synergy'],
                    'home_alt': analysis['patterns']['home']['alternation_combo'],
                    'away_alt': analysis['patterns']['away']['alternation_combo'],
                    'cpp_prediction': analysis['cpp_prediction'],
                    'odds': None
                }
                
                if league_odds:
                    odds = match_euro_odds(home, away, league_odds)
                    if odds:
                        match_data['odds'] = {
                            'home': odds['home_odds'],
                            'away': odds['away_odds'],
                            'bookmaker': odds['bookmaker']
                        }
                        
                        cpp = analysis['cpp_prediction']
                        if cpp['synergy'] >= 2 and cpp['team']:
                            bet_odds = odds['home_odds'] if cpp['team'] == 'home' else odds['away_odds']
                            if bet_odds > 0:
                                prob = 0.55 + (cpp['synergy'] - 2) * 0.05
                                ev = (prob * (bet_odds - 1)) - (1 - prob)
                                match_data['odds']['ev'] = round(ev * 100, 1)
                                match_data['odds']['profitable'] = ev > 0
                                match_data['odds']['target'] = cpp['team']
                                match_data['odds']['reasoning'] = f"CPP: {cpp['team']} (синергия {cpp['synergy']})"
                
                matches.append(match_data)
    
    matches.sort(key=lambda x: x['score'], reverse=True)
    
    return jsonify({
        'league': league_upper,
        'matches': matches,
        'has_odds': league_upper in ['Liiga', 'SHL']
    })


sequence_model = None
sequence_preparer = None

def init_sequence_model():
    """Инициализация Sequence модели"""
    global sequence_model, sequence_preparer
    
    if sequence_model is None:
        model_path = 'artifacts/sequence_model'
        if os.path.exists(os.path.join(model_path, 'model.pth')):
            try:
                from src.sequence_model import load_sequence_model, SequenceModelTrainer
                sequence_model, sequence_preparer = load_sequence_model(model_path)
                print("✅ Sequence модель загружена!")
            except Exception as e:
                print(f"⚠️ Ошибка загрузки sequence модели: {e}")
                return None, None
        else:
            print("⚠️ Sequence модель не найдена. Запустите train_sequence.py для обучения.")
            return None, None
    
    return sequence_model, sequence_preparer


@app.route('/api/sequence/status')
def api_sequence_status():
    """API: статус Sequence модели"""
    model_path = 'artifacts/sequence_model'
    config_path = os.path.join(model_path, 'config.json')
    
    if os.path.exists(config_path):
        import json
        with open(config_path, 'r') as f:
            config = json.load(f)
        return jsonify({
            'status': 'ready',
            'config': config
        })
    else:
        return jsonify({
            'status': 'not_trained',
            'message': 'Модель не обучена. Запустите: python train_sequence.py'
        })


@app.route('/api/sequence/predict/<home>/<away>')
def api_sequence_predict(home, away):
    """API: прогноз Sequence модели для матча"""
    init_system()
    model, preparer = init_sequence_model()
    
    if model is None:
        return jsonify({
            'error': 'Sequence модель не загружена',
            'hint': 'Запустите: python train_sequence.py'
        }), 400
    
    import numpy as np
    
    if all_games is None or all_games.empty:
        return jsonify({
            'error': 'Данные матчей не загружены',
            'hint': 'Подождите инициализации системы'
        }), 400
    
    team_history = preparer.build_team_history(all_games)
    
    home_upper = home.upper()
    away_upper = away.upper()
    
    if home_upper not in team_history or away_upper not in team_history:
        return jsonify({
            'error': f'Команда не найдена: {home_upper if home_upper not in team_history else away_upper}'
        }), 400
    
    seq_len = preparer.sequence_length
    
    if len(team_history[home_upper]) < seq_len or len(team_history[away_upper]) < seq_len:
        return jsonify({
            'error': f'Недостаточно истории матчей (нужно минимум {seq_len})'
        }), 400
    
    home_hist = team_history[home_upper][-seq_len:]
    away_hist = team_history[away_upper][-seq_len:]
    
    home_seq = [[m[col] for col in preparer.feature_columns] for m in home_hist]
    away_seq = [[m[col] for col in preparer.feature_columns] for m in away_hist]
    
    home_seq = np.array([home_seq])
    away_seq = np.array([away_seq])
    
    home_norm, away_norm = preparer.normalize_sequences(home_seq, away_seq, fit=False)
    
    prediction = model.predict_match(home_norm[0], away_norm[0])
    
    return jsonify({
        'home_team': home_upper,
        'away_team': away_upper,
        'prediction': prediction,
        'model_type': 'LSTM Sequence',
        'sequence_length': seq_len
    })


def create_prediction_from_match(match_data):
    """
    Создать прогноз на основе данных матча
    
    Args:
        match_data: Данные матча с коэффициентами
        
    Returns:
        Prediction object или None
    """
    try:
        init_system()
        
        home_team = match_data.get('home_team', '')
        away_team = match_data.get('away_team', '')
        league = match_data.get('league', 'NHL')
        
        home_odds = match_data.get('home_odds')
        away_odds = match_data.get('away_odds')
        
        if not home_odds or not away_odds:
            return None
        
        if home_odds < away_odds:
            predicted_outcome = 'home'
            confidence = min(0.95, 1 / home_odds + 0.1)
        else:
            predicted_outcome = 'away'
            confidence = min(0.95, 1 / away_odds + 0.1)
        
        confidence_1_10 = max(1, min(10, int(confidence * 10)))
        
        prediction = Prediction(
            match_date=match_data.get('match_date', datetime.utcnow()),
            league=league,
            home_team=home_team,
            away_team=away_team,
            prediction_type='Money Line',
            predicted_outcome=predicted_outcome,
            confidence=confidence,
            confidence_1_10=confidence_1_10,
            home_odds=home_odds,
            away_odds=away_odds,
            draw_odds=match_data.get('draw_odds'),
            bookmaker=match_data.get('bookmaker', ''),
            patterns_data=match_data.get('patterns', {}),
            model_version='1.0.0'
        )
        
        with app.app_context():
            db.session.add(prediction)
            db.session.commit()
            
            if telegram_notifier.is_configured():
                telegram_notifier.send_prediction_alert(prediction.to_dict())
                prediction.notified_telegram = True
                db.session.commit()
        
        return prediction
        
    except Exception as e:
        print(f"Error creating prediction: {e}")
        return None


def init_odds_monitor():
    """Инициализация монитора коэффициентов"""
    global flashlive_loader
    
    def prediction_callback(match_data):
        return create_prediction_from_match(match_data)
    
    def notification_callback(prediction):
        if prediction and telegram_notifier.is_configured():
            return telegram_notifier.send_prediction_alert(prediction.to_dict())
        return False
    
    # FlashLive API - 281 матчей, все лиги, бесплатный план RapidAPI
    monitor = OddsMonitor(
        odds_loader=flashlive_loader,
        prediction_callback=prediction_callback,
        notification_callback=notification_callback,
        check_interval=300  # 5 минут
    )
    
    set_monitor(monitor)
    return monitor


_startup_done = False

def startup_initialization():
    """Выполняется один раз при старте приложения"""
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    
    import threading
    threading.Thread(target=warmup_multi_league, daemon=True).start()
    
    if flashlive_loader.is_configured():
        threading.Thread(target=init_odds_monitor, daemon=True).start()
        print("✅ Odds monitor initialized with FlashLive API (RapidAPI)")
    elif allbestbets_loader.is_configured():
        threading.Thread(target=init_odds_monitor, daemon=True).start()
        print("✅ Odds monitor initialized with AllBestBets API (fallback)")
    else:
        print("⚠️ No odds API configured (need RAPIDAPI_KEY or ALLBESTBETS_API_TOKEN)")


startup_initialization()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
