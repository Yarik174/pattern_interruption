"""
Game analysis business logic: pattern analysis, CPP predictions, synergy scoring.

Extracted from app.py to reduce monolith size.
All state (data_loader, pattern_engine, model, etc.) is managed via module-level
variables and lazy-init functions, matching the original app.py approach.
"""
import os

import joblib
import pandas as pd
from datetime import datetime
from typing import Optional

from src.data_loader import DataLoader
from src.pattern_engine import PatternEngine
from src.feature_builder import FeatureBuilder
from src.sports_config import SportType, get_leagues_for_sport

# ── Module state (lazy-initialized) ──────────────────────────────────────────

data_loader = None
pattern_engine = None
feature_builder = None
model = None
all_games = None
feature_names = None

multi_league_engine = None

euro_league_engine = None
euro_league_data = {}

sequence_model = None
sequence_preparer = None


# ── Initialization ───────────────────────────────────────────────────────────

def get_latest_artifact():
    """Получить путь к последнему артефакту (только папки с датой)."""
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


def init_system():
    """Инициализация системы при первом запросе."""
    global data_loader, pattern_engine, feature_builder, model, all_games, feature_names

    if data_loader is None:
        print("🔄 Инициализация системы...")
        data_loader = DataLoader()
        pattern_engine = PatternEngine()
        feature_builder = FeatureBuilder(pattern_engine)

        print("📥 Загрузка исторических данных...")
        seasons = data_loader.get_cached_seasons() or DataLoader.get_default_seasons(n_seasons=10)
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


def init_multi_league():
    """Инициализация мульти-лигового движка."""
    global multi_league_engine

    if multi_league_engine is None:
        from src.multi_league_predictor import MultiLeaguePatternEngine
        print("🌍 Инициализация мульти-лигового движка...")
        multi_league_engine = MultiLeaguePatternEngine(critical_length=5)
        multi_league_engine.load_leagues(['KHL', 'SHL', 'Liiga', 'DEL'], n_seasons=None)
        print("✅ Мульти-лиговый движок готов!")

    return multi_league_engine


def warmup_multi_league():
    """Предзагрузка данных мульти-лиг при старте сервера."""
    try:
        print("🔄 Предзагрузка данных европейских лиг...")
        init_multi_league()
        print("✅ Предзагрузка завершена")
    except Exception as e:
        print(f"⚠️ Ошибка предзагрузки: {e}")


def init_euro_leagues():
    """Инициализация движка европейских лиг."""
    global euro_league_engine, euro_league_data

    if euro_league_engine is None:
        from src.euro_league_loader import EuroLeagueLoader
        print("🏒 Инициализация европейских лиг...")

        loader = EuroLeagueLoader()
        euro_league_data = loader.load_all_european_leagues(n_seasons=None)

        euro_league_engine = PatternEngine()

        for league_name, df in euro_league_data.items():
            if not df.empty:
                euro_league_engine.analyze_all_patterns(df)
                print(f"✅ {league_name}: паттерны проанализированы")

        print("✅ Европейские лиги готовы!")

    return euro_league_engine, euro_league_data


def init_sequence_model():
    """Инициализация Sequence модели."""
    global sequence_model, sequence_preparer

    if sequence_model is None:
        model_path = 'artifacts/sequence_model'
        if os.path.exists(os.path.join(model_path, 'model.pth')):
            try:
                from src.sequence_model import load_sequence_model
                sequence_model, sequence_preparer = load_sequence_model(model_path)
                print("✅ Sequence модель загружена!")
            except Exception as e:
                print(f"⚠️ Ошибка загрузки sequence модели: {e}")
                return None, None
        else:
            print("⚠️ Sequence модель не найдена. Запустите train_sequence.py для обучения.")
            return None, None

    return sequence_model, sequence_preparer


# ── Scoring helpers ──────────────────────────────────────────────────────────

def calc_overgrowth(features):
    max_len = features.get('max_streak_len', 0)
    if max_len >= 8:
        return 3
    elif max_len >= 7:
        return 2
    elif max_len >= 6:
        return 1
    return 0


def calc_strong_signal(synergy, alt_combo, overgrowth):
    score = 0
    if synergy >= 2:
        score += synergy
    if alt_combo >= 1:
        score += alt_combo
    score += overgrowth
    return min(score, 6)


def get_cpp_prediction(home_features, away_features):
    """CPP логика: серия → прерывание, чередование → повтор последнего."""
    home_preds = []
    away_preds = []

    home_streak = home_features.get('home_win_streak', 0)
    if home_features.get('home_streak_critical', 0):
        if home_streak > 0:
            away_preds.append({'type': 'home_streak', 'reason': f'Прерывание домашней серии побед ({home_streak})'})
        elif home_streak < 0:
            home_preds.append({'type': 'home_streak', 'reason': f'Прерывание домашней серии поражений ({home_streak})'})

    overall_streak = home_features.get('overall_win_streak', 0)
    if home_features.get('overall_streak_critical', 0):
        if overall_streak > 0:
            away_preds.append({'type': 'overall_streak', 'reason': f'Прерывание общей серии побед хозяев ({overall_streak})'})
        elif overall_streak < 0:
            home_preds.append({'type': 'overall_streak', 'reason': f'Прерывание общей серии поражений хозяев ({overall_streak})'})

    if home_features.get('home_alt_critical', 0):
        last = home_features.get('home_last_result', 0)
        if last == 1:
            home_preds.append({'type': 'home_alt', 'reason': 'Прерывание чередования дома (последний W → W)'})
        else:
            away_preds.append({'type': 'home_alt', 'reason': 'Прерывание чередования дома (последний L → L)'})

    if home_features.get('overall_alt_critical', 0):
        last = home_features.get('overall_last_result', 0)
        if last == 1:
            home_preds.append({'type': 'overall_alt', 'reason': 'Прерывание общего чередования хозяев (последний W → W)'})
        else:
            away_preds.append({'type': 'overall_alt', 'reason': 'Прерывание общего чередования хозяев (последний L → L)'})

    away_streak = away_features.get('away_win_streak', 0)
    if away_features.get('away_streak_critical', 0):
        if away_streak > 0:
            home_preds.append({'type': 'away_streak', 'reason': f'Прерывание гостевой серии побед ({away_streak})'})
        elif away_streak < 0:
            away_preds.append({'type': 'away_streak', 'reason': f'Прерывание гостевой серии поражений ({away_streak})'})

    away_overall = away_features.get('overall_win_streak', 0)
    if away_features.get('overall_streak_critical', 0):
        if away_overall > 0:
            home_preds.append({'type': 'away_overall', 'reason': f'Прерывание общей серии побед гостей ({away_overall})'})
        elif away_overall < 0:
            away_preds.append({'type': 'away_overall', 'reason': f'Прерывание общей серии поражений гостей ({away_overall})'})

    if away_features.get('overall_alt_critical', 0):
        last = away_features.get('overall_last_result', 0)
        if last == 1:
            away_preds.append({'type': 'away_alt', 'reason': 'Прерывание общего чередования гостей (последний W → W)'})
        else:
            home_preds.append({'type': 'away_alt', 'reason': 'Прерывание общего чередования гостей (последний L → L)'})

    h2h_streak = home_features.get('h2h_win_streak', 0)
    if home_features.get('h2h_streak_critical', 0):
        if h2h_streak > 0:
            away_preds.append({'type': 'h2h_streak', 'reason': f'Прерывание серии H2H ({h2h_streak})'})
        elif h2h_streak < 0:
            home_preds.append({'type': 'h2h_streak', 'reason': f'Прерывание серии H2H ({h2h_streak})'})

    if home_features.get('h2h_alt_critical', 0):
        last = home_features.get('h2h_last_result', 0)
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


# ── Main analysis ────────────────────────────────────────────────────────────

def analyze_game(home_team, away_team):
    """Анализ паттернов для матча."""
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
        home_features.get('overall_alt_critical', 0),
    ])

    away_synergy = sum([
        away_features.get('away_streak_critical', 0),
        away_features.get('h2h_streak_critical', 0),
        away_features.get('overall_streak_critical', 0),
        away_features.get('away_alt_critical', 0),
        away_features.get('h2h_alt_critical', 0),
        away_features.get('overall_alt_critical', 0),
    ])

    home_alt_combo = sum([
        1 if home_features.get('home_alt_critical', 0) else 0,
        1 if home_features.get('h2h_alt_critical', 0) else 0,
        1 if home_features.get('overall_alt_critical', 0) else 0,
    ])

    away_alt_combo = sum([
        1 if away_features.get('away_alt_critical', 0) else 0,
        1 if away_features.get('h2h_alt_critical', 0) else 0,
        1 if away_features.get('overall_alt_critical', 0) else 0,
    ])

    home_overgrowth = calc_overgrowth(home_features)
    away_overgrowth = calc_overgrowth(away_features)

    cpp_prediction = get_cpp_prediction(home_features, away_features)

    home_strong = calc_strong_signal(home_synergy, home_alt_combo, home_overgrowth)
    away_strong = calc_strong_signal(away_synergy, away_alt_combo, away_overgrowth)

    analysis = {
        'home_team': home_team,
        'away_team': away_team,
        'patterns': {},
        'strong_signal': {
            'home': home_strong,
            'away': away_strong,
            'max': max(home_strong, away_strong),
        },
        'cpp_prediction': {
            'team': cpp_prediction['team'],
            'synergy': cpp_prediction['synergy'],
            'patterns': [p['reason'] for p in cpp_prediction['patterns']],
            'bet_recommendation': home_team if cpp_prediction['team'] == 'home' and cpp_prediction['synergy'] >= 2 else (
                away_team if cpp_prediction['team'] == 'away' and cpp_prediction['synergy'] >= 2 else None
            ),
        },
        'prediction': None,
    }

    analysis['patterns']['home'] = {
        'win_streak': home_features.get('home_win_streak', 0),
        'overall_streak': home_features.get('overall_win_streak', 0),
        'any_critical': 1 if home_synergy > 0 else 0,
        'synergy': home_synergy,
        'alternation_combo': home_alt_combo,
        'overgrowth': home_overgrowth,
        'max_alternation_len': home_features.get('max_alternation_len', 0),
    }

    analysis['patterns']['away'] = {
        'win_streak': away_features.get('away_win_streak', 0),
        'overall_streak': away_features.get('overall_win_streak', 0),
        'any_critical': 1 if away_synergy > 0 else 0,
        'synergy': away_synergy,
        'alternation_combo': away_alt_combo,
        'overgrowth': away_overgrowth,
        'max_alternation_len': away_features.get('max_alternation_len', 0),
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
            break_prob = proba[1] if len(proba) > 1 else proba[0]
            continue_prob = proba[0] if len(proba) > 1 else (1 - proba[0])

            bet_on = cpp_prediction.get('team')

            if bet_on == 'home':
                predicted_winner = 'away' if break_prob >= 0.5 else 'home'
            elif bet_on == 'away':
                predicted_winner = 'home' if break_prob >= 0.5 else 'away'
            else:
                predicted_winner = 'home' if break_prob >= 0.5 else 'away'

            analysis['prediction'] = {
                'break_probability': round(break_prob * 100, 1),
                'continue_probability': round(continue_prob * 100, 1),
                'home_probability': round(break_prob * 100, 1) if predicted_winner == 'home' else round(continue_prob * 100, 1),
                'away_probability': round(break_prob * 100, 1) if predicted_winner == 'away' else round(continue_prob * 100, 1),
                'predicted_winner': predicted_winner,
                'recommendation': home_team if predicted_winner == 'home' else away_team,
                'bet_on': bet_on,
            }
        except Exception as e:
            print(f"Ошибка предсказания: {e}")
            import traceback
            traceback.print_exc()

    return analysis


# ── Euro CPP signals ─────────────────────────────────────────────────────────

def get_euro_cpp_signals(league_name, home_team, away_team):
    """Получить CPP сигналы для матча европейской лиги."""
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
        home_features.get('overall_alt_critical', 0),
    ])

    away_synergy = sum([
        away_features.get('away_streak_critical', 0),
        away_features.get('h2h_streak_critical', 0),
        away_features.get('overall_streak_critical', 0),
        away_features.get('away_alt_critical', 0),
        away_features.get('h2h_alt_critical', 0),
        away_features.get('overall_alt_critical', 0),
    ])

    home_alt_combo = sum([
        1 if home_features.get('home_alt_critical', 0) else 0,
        1 if home_features.get('h2h_alt_critical', 0) else 0,
        1 if home_features.get('overall_alt_critical', 0) else 0,
    ])

    away_alt_combo = sum([
        1 if away_features.get('away_alt_critical', 0) else 0,
        1 if away_features.get('h2h_alt_critical', 0) else 0,
        1 if away_features.get('overall_alt_critical', 0) else 0,
    ])

    home_overgrowth = calc_overgrowth(home_features)
    away_overgrowth = calc_overgrowth(away_features)

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
                'overgrowth': home_overgrowth,
            },
            'away': {
                'win_streak': away_features.get('away_win_streak', 0),
                'overall_streak': away_features.get('overall_win_streak', 0),
                'synergy': away_synergy,
                'alternation_combo': away_alt_combo,
                'overgrowth': away_overgrowth,
            },
        },
        'strong_signal': {
            'home': home_strong,
            'away': away_strong,
            'max': max(home_strong, away_strong),
        },
        'cpp_prediction': {
            'team': predicted_team,
            'synergy': synergy_count,
            'patterns': cpp_patterns,
            'bet_recommendation': (home_team if predicted_team == 'home' else
                                   away_team if predicted_team == 'away' else None) if synergy_count >= 2 else None,
        },
    }
