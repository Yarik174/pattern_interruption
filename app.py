"""
NHL Pattern Prediction Web Interface
Веб-интерфейс для тестирования прогнозов на реальных матчах
"""

import warnings
warnings.filterwarnings('ignore', category=UserWarning)

from flask import Flask, render_template, jsonify
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
    """Главная страница"""
    return render_template('index.html')

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
        multi_league_engine.load_leagues(['KHL', 'SHL', 'Liiga', 'DEL'], n_seasons=3)
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


if __name__ == '__main__':
    import threading
    threading.Thread(target=warmup_multi_league, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=True)
