"""
Legacy API routes previously registered directly on the Flask app object.

Extracted from app.py to reduce monolith size.
These routes handle: upcoming games, analysis, odds, sports list,
multi-league, european matches, sequence model.
"""
from __future__ import annotations

import os
import json

from flask import Blueprint, jsonify, request, redirect, url_for

from src.nhl_teams import resolve_sport_type, get_sport_slug
from src.sports_config import get_all_sports, get_leagues_for_sport
from src.odds_service import fetch_odds, get_upcoming_games, fetch_european_odds, match_euro_odds
from src.game_analysis import (
    analyze_game, init_system, init_multi_league, init_euro_leagues,
    get_euro_cpp_signals, init_sequence_model,
)

legacy_api_bp = Blueprint('legacy_api', __name__)


# ── Index ────────────────────────────────────────────────────────────────────

@legacy_api_bp.route('/')
def index():
    """Главная страница - перенаправление на прогнозы."""
    return redirect(url_for('routes.predictions_page'))


# ── Upcoming & Analyze ───────────────────────────────────────────────────────

@legacy_api_bp.route('/api/upcoming')
def api_upcoming():
    """API: предстоящие матчи."""
    sport = request.args.get('sport')
    league = request.args.get('league')
    days_ahead = request.args.get('days', 1, type=int)
    leagues = [league] if league else None

    if sport and resolve_sport_type(sport, default=None) is None:
        return jsonify({'error': 'Неизвестный вид спорта'}), 400

    if sport or league or days_ahead != 1:
        games = get_upcoming_games(sport=sport, leagues=leagues, days_ahead=days_ahead)
    else:
        games = get_upcoming_games()
    payload = {'matches': games}
    if sport:
        payload['sport'] = str(sport).lower()
    if league:
        payload['league'] = league
    return jsonify(payload)


@legacy_api_bp.route('/api/analyze/<home_team>/<away_team>')
def api_analyze(home_team, away_team):
    """API: анализ матча."""
    analysis = analyze_game(home_team.upper(), away_team.upper())
    if analysis:
        return jsonify(analysis)
    return jsonify({'error': 'Не удалось проанализировать матч'}), 400


@legacy_api_bp.route('/api/analyze-all')
def api_analyze_all():
    """API: анализ всех предстоящих матчей."""
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
                    'bookmaker': odds['bookmaker'],
                }

                if analysis.get('prediction'):
                    home_prob = analysis['prediction']['home_probability'] / 100
                    away_prob = analysis['prediction']['away_probability'] / 100
                    home_odds_val = odds['home_odds']
                    away_odds_val = odds['away_odds']

                    predicted_winner = analysis['prediction']['predicted_winner']

                    if predicted_winner == 'home':
                        bet_team = 'home'
                        bet_prob = home_prob
                        bet_odds = home_odds_val
                        bet_reasoning = f"Модель прогнозирует победу {analysis['home_team']} ({home_prob*100:.0f}%)"
                    else:
                        bet_team = 'away'
                        bet_prob = away_prob
                        bet_odds = away_odds_val
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


# ── Odds & Sports ───────────────────────────────────────────────────────────

@legacy_api_bp.route('/api/odds')
def api_odds():
    """API: получить коэффициенты."""
    sport = request.args.get('sport')
    league = request.args.get('league')
    days_ahead = request.args.get('days', 1, type=int)
    leagues = [league] if league else None

    if sport and resolve_sport_type(sport, default=None) is None:
        return jsonify({'error': 'Неизвестный вид спорта'}), 400

    if sport or league or days_ahead != 1:
        odds_data = fetch_odds(sport=sport, leagues=leagues, days_ahead=days_ahead)
    else:
        odds_data = fetch_odds()
    payload = {'odds': odds_data, 'count': len(odds_data)}
    if sport:
        payload['sport'] = str(sport).lower()
    if league:
        payload['league'] = league
    return jsonify(payload)


@legacy_api_bp.route('/api/sports')
def api_sports():
    """API: список поддерживаемых видов спорта и лиг."""
    sports = []
    for sport in get_all_sports():
        sports.append({
            'id': sport['id'],
            'slug': get_sport_slug(sport['type']),
            'name': sport['name'],
            'name_ru': sport['name_ru'],
            'icon': sport['icon'],
            'leagues': sport['leagues'],
        })
    return jsonify({'sports': sports})


# ── Multi-league ─────────────────────────────────────────────────────────────

@legacy_api_bp.route('/api/multi-league/summary')
def api_multi_league_summary():
    """API: сводка по всем лигам."""
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
                    'score': score,
                })

        critical_teams.sort(key=lambda x: abs(x['streak']), reverse=True)

        summary[league] = {
            'total_teams': len(patterns),
            'critical_teams': critical_teams[:10],
            'critical_count': len(critical_teams),
        }

    return jsonify(summary)


@legacy_api_bp.route('/api/multi-league/upcoming')
def api_multi_league_upcoming():
    """API: предстоящие матчи всех лиг с анализом."""
    engine = init_multi_league()

    leagues = ['KHL', 'SHL', 'Liiga', 'DEL']
    analyzed = engine.get_all_upcoming_with_analysis(leagues, include_odds=True)

    result = {
        'matches': [],
        'leagues': {},
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
            'ev': m.get('ev'),
        }
        result['matches'].append(match_info)

        league = m['league']
        if league not in result['leagues']:
            result['leagues'][league] = 0
        result['leagues'][league] += 1

    return jsonify(result)


@legacy_api_bp.route('/api/multi-league/analyze/<league>/<home>/<away>')
def api_multi_league_analyze(league, home, away):
    """API: анализ конкретного матча в лиге."""
    engine = init_multi_league()

    if league not in ['KHL', 'SHL', 'Liiga', 'DEL', 'NHL']:
        return jsonify({'error': 'Неизвестная лига'}), 400

    analysis = engine.analyze_match(league, home, away)
    return jsonify(analysis)


# ── European matches ─────────────────────────────────────────────────────────

@legacy_api_bp.route('/api/european_matches')
def api_european_matches():
    """API: матчи европейских лиг с CPP анализом."""
    engine, data = init_euro_leagues()

    euro_odds = fetch_european_odds()

    results = {
        'KHL': {'matches': [], 'has_odds': False},
        'SHL': {'matches': [], 'has_odds': True},
        'Liiga': {'matches': [], 'has_odds': True},
        'DEL': {'matches': [], 'has_odds': False},
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
                        'ev': None,
                    }

                    if league_name in euro_odds:
                        odds = match_euro_odds(home, away, euro_odds[league_name])
                        if odds:
                            match_data['odds'] = {
                                'home': odds['home_odds'],
                                'away': odds['away_odds'],
                                'bookmaker': odds['bookmaker'],
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


@legacy_api_bp.route('/api/european_matches/<league>')
def api_european_matches_by_league(league):
    """API: матчи конкретной европейской лиги."""
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
                    'odds': None,
                }

                if league_odds:
                    odds = match_euro_odds(home, away, league_odds)
                    if odds:
                        match_data['odds'] = {
                            'home': odds['home_odds'],
                            'away': odds['away_odds'],
                            'bookmaker': odds['bookmaker'],
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
        'has_odds': league_upper in ['Liiga', 'SHL'],
    })


# ── Sequence model ───────────────────────────────────────────────────────────

@legacy_api_bp.route('/api/sequence/status')
def api_sequence_status():
    """API: статус Sequence модели."""
    model_path = 'artifacts/sequence_model'
    config_path = os.path.join(model_path, 'config.json')

    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
        return jsonify({
            'status': 'ready',
            'config': config,
        })
    else:
        return jsonify({
            'status': 'not_trained',
            'message': 'Модель не обучена. Запустите: python train_sequence.py',
        })


@legacy_api_bp.route('/api/sequence/predict/<home>/<away>')
def api_sequence_predict(home, away):
    """API: прогноз Sequence модели для матча."""
    import numpy as np
    from src.game_analysis import all_games as _all_games

    init_system()
    seq_model, preparer = init_sequence_model()

    if seq_model is None:
        return jsonify({
            'error': 'Sequence модель не загружена',
            'hint': 'Запустите: python train_sequence.py',
        }), 400

    current_all_games = _all_games
    if current_all_games is None or current_all_games.empty:
        return jsonify({
            'error': 'Данные матчей не загружены',
            'hint': 'Подождите инициализации системы',
        }), 400

    team_history = preparer.build_team_history(current_all_games)

    home_upper = home.upper()
    away_upper = away.upper()

    if home_upper not in team_history or away_upper not in team_history:
        return jsonify({
            'error': f'Команда не найдена: {home_upper if home_upper not in team_history else away_upper}',
        }), 400

    seq_len = preparer.sequence_length

    if len(team_history[home_upper]) < seq_len or len(team_history[away_upper]) < seq_len:
        return jsonify({
            'error': f'Недостаточно истории матчей (нужно минимум {seq_len})',
        }), 400

    home_hist = team_history[home_upper][-seq_len:]
    away_hist = team_history[away_upper][-seq_len:]

    home_seq = [[m[col] for col in preparer.feature_columns] for m in home_hist]
    away_seq = [[m[col] for col in preparer.feature_columns] for m in away_hist]

    home_seq = np.array([home_seq])
    away_seq = np.array([away_seq])

    home_norm, away_norm = preparer.normalize_sequences(home_seq, away_seq, fit=False)

    prediction = seq_model.predict_match(home_norm[0], away_norm[0])

    return jsonify({
        'home_team': home_upper,
        'away_team': away_upper,
        'prediction': prediction,
        'model_type': 'LSTM Sequence',
        'sequence_length': seq_len,
    })
