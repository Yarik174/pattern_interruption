#!/usr/bin/env python3
"""
NHL Historical Backtest — Phase 1 of Overnight Pipeline

Loads 7 seasons of NHL data with real bookmaker odds,
runs PatternEngine to extract features (same logic as train_critical.py),
gets real RF model confidence, calibrates break rates by pattern type,
calculates ROI + EV by pattern combination, and saves RL training data.

Run from project root:
    python scripts/backtest_nhl.py
"""

import sys
import os

# Ensure project root is in path (script lives in scripts/, one level below root)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import json
import logging
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import joblib

from src.underdog_patterns import load_all_odds_data, add_underdog_info
from src.feature_builder import FeatureBuilder
from src.pattern_analysis import PatternAnalyzer

# ─── Setup ────────────────────────────────────────────────────────────────────

os.makedirs('logs', exist_ok=True)
os.makedirs('data/backtest_results', exist_ok=True)

_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'logs/backtest_nhl_{_ts}.log'),
    ],
)
log = logging.getLogger(__name__)

RF_MODEL_PATH = 'artifacts/20260319_003205/model.pkl'
MIN_HISTORY = 20  # минимум матчей на команду до начала анализа


# ─── RF Model ─────────────────────────────────────────────────────────────────

def load_rf_model() -> Tuple[Optional[object], List[str]]:
    """Загрузка обученной RF модели из артефактов."""
    try:
        artifact = joblib.load(RF_MODEL_PATH)
        model = artifact['model']
        feature_names = artifact['feature_names']
        log.info(f"RF model loaded: {len(feature_names)} features")
        return model, feature_names
    except Exception as e:
        log.error(f"RF model not found at {RF_MODEL_PATH}: {e}")
        log.warning("Falling back to neutral confidence (0.5)")
        return None, []


# ─── Feature Building ─────────────────────────────────────────────────────────

def build_feature_row(home_f: dict, away_f: dict, fb: FeatureBuilder) -> dict:
    """
    Собираем combined feature dict из выходов pe.get_pattern_features().
    Точно повторяет логику train_critical.py lines 73-136.
    """
    cf = {}
    for k, v in home_f.items():
        cf[f'home_{k}'] = v
    for k, v in away_f.items():
        cf[f'away_{k}'] = v

    cf['streak_diff'] = (
        home_f.get('overall_win_streak', 0) - away_f.get('overall_win_streak', 0)
    )
    cf['h2h_advantage'] = (
        home_f.get('h2h_last_5_wins', 0) - away_f.get('h2h_last_5_wins', 0)
    )

    cf['home_any_critical'] = max(
        home_f.get('home_streak_critical', 0),
        home_f.get('h2h_streak_critical', 0),
        home_f.get('overall_streak_critical', 0),
        home_f.get('home_alt_critical', 0),
        home_f.get('h2h_alt_critical', 0),
        home_f.get('overall_alt_critical', 0),
    )
    cf['away_any_critical'] = max(
        away_f.get('away_streak_critical', 0),
        away_f.get('h2h_streak_critical', 0),
        away_f.get('overall_streak_critical', 0),
        away_f.get('away_alt_critical', 0),
        away_f.get('h2h_alt_critical', 0),
        away_f.get('overall_alt_critical', 0),
    )

    cf['home_total_critical'] = home_f.get('total_critical_patterns', 0)
    cf['away_total_critical'] = away_f.get('total_critical_patterns', 0)
    cf['max_streak_len'] = max(
        home_f.get('max_streak_len', 0), away_f.get('max_streak_len', 0)
    )
    cf['max_alternation_len'] = max(
        home_f.get('max_alternation_len', 0), away_f.get('max_alternation_len', 0)
    )

    home_syn, home_aligned = fb._calculate_critical_synergy(home_f, 'home')
    away_syn, away_aligned = fb._calculate_critical_synergy(away_f, 'away')
    cf['synergy_home'] = fb._calculate_synergy(home_f, 'home')
    cf['synergy_away'] = fb._calculate_synergy(away_f, 'away')
    cf['critical_synergy_home'] = home_syn
    cf['critical_synergy_away'] = away_syn
    cf['aligned_patterns_home'] = home_aligned
    cf['aligned_patterns_away'] = away_aligned
    cf['total_aligned'] = abs(home_aligned) + abs(away_aligned)
    cf['pattern_agreement'] = (
        1 if fb._predict_from_pattern(home_f) == (1 - fb._predict_from_pattern(away_f)) else 0
    )
    cf['critical_pattern_exists'] = (
        1 if (cf['home_total_critical'] > 0 or cf['away_total_critical'] > 0) else 0
    )

    home_og = fb._calculate_overgrowth(home_f)
    away_og = fb._calculate_overgrowth(away_f)
    cf['home_streak_overgrowth'] = home_og
    cf['away_streak_overgrowth'] = away_og
    cf['max_overgrowth'] = max(home_og, away_og)

    home_ac = fb._calculate_alternation_combo(home_f)
    away_ac = fb._calculate_alternation_combo(away_f)
    cf['home_alternation_combo'] = home_ac
    cf['away_alternation_combo'] = away_ac
    cf['max_alternation_combo'] = max(home_ac, away_ac)

    cf['home_strong_signal'] = fb._calculate_strong_signal(home_f, home_syn, home_ac, home_og)
    cf['away_strong_signal'] = fb._calculate_strong_signal(away_f, away_syn, away_ac, away_og)
    cf['any_strong_signal'] = max(cf['home_strong_signal'], cf['away_strong_signal'])

    home_bp = fb._calculate_predicted_break_outcome(home_f, 'home')
    away_bp = fb._calculate_predicted_break_outcome(away_f, 'away')
    cf['home_predicted_break'] = len(home_bp)
    cf['away_predicted_break'] = len(away_bp)

    cf['home_independent_patterns'] = fb._calculate_independent_patterns(home_f)
    cf['away_independent_patterns'] = fb._calculate_independent_patterns(away_f)

    cf['home_weighted_break_prob'] = fb._calculate_weighted_break_probability(home_f, 'home')
    cf['away_weighted_break_prob'] = fb._calculate_weighted_break_probability(away_f, 'away')

    return cf


# ─── Betting Simulation ───────────────────────────────────────────────────────

def simulate_betting(features_list: List[dict], df: pd.DataFrame) -> dict:
    """
    Симулируем ставки на прерывание паттернов. Ставим ПРОТИВ команды
    с более сильным критическим паттерном. Считаем ROI + EV по комбинациям.
    """
    combos: dict = defaultdict(lambda: {
        'bets': 0, 'wins': 0, 'staked': 0.0, 'returned': 0.0, 'odds_sum': 0.0
    })

    for cf in features_list:
        if cf.get('critical_pattern_exists', 0) == 0:
            continue

        row_idx = cf.get('_row_idx')
        if row_idx is None or row_idx >= len(df):
            continue

        row = df.iloc[row_idx]
        home_odds = float(row.get('home_odds', 2.0))
        away_odds = float(row.get('away_odds', 2.0))
        home_win = int(row.get('home_win', 0))

        synergy_home = cf.get('critical_synergy_home', 0)
        synergy_away = cf.get('critical_synergy_away', 0)

        if synergy_home >= synergy_away and synergy_home > 0:
            bet_odds = away_odds
            bet_won = (home_win == 0)
        elif synergy_away > synergy_home:
            bet_odds = home_odds
            bet_won = (home_win == 1)
        else:
            continue

        # Build combo key from active critical pattern types
        parts = []
        if synergy_home >= synergy_away:
            if cf.get('home_home_streak_critical', 0):
                parts.append('home_streak')
            if cf.get('home_overall_streak_critical', 0):
                parts.append('overall_streak')
            if cf.get('home_home_alt_critical', 0):
                parts.append('home_alt')
            if cf.get('home_overall_alt_critical', 0):
                parts.append('overall_alt')
            if cf.get('home_h2h_streak_critical', 0):
                parts.append('h2h_streak')
            if home_odds > away_odds:
                parts.append('underdog')
        else:
            if cf.get('away_away_streak_critical', 0):
                parts.append('away_streak')
            if cf.get('away_overall_streak_critical', 0):
                parts.append('overall_streak')
            if cf.get('away_away_alt_critical', 0):
                parts.append('away_alt')
            if cf.get('away_overall_alt_critical', 0):
                parts.append('overall_alt')
            if cf.get('away_h2h_streak_critical', 0):
                parts.append('h2h_streak')
            if away_odds > home_odds:
                parts.append('underdog')

        synergy_level = max(synergy_home, synergy_away)
        combo_key = ('+'.join(sorted(set(parts))) or 'basic') + f'_syn{synergy_level}'

        combos[combo_key]['bets'] += 1
        combos[combo_key]['staked'] += 1.0
        combos[combo_key]['odds_sum'] += bet_odds
        if bet_won:
            combos[combo_key]['wins'] += 1
            combos[combo_key]['returned'] += bet_odds

    results = {}
    for combo, s in combos.items():
        if s['bets'] < 5:
            continue
        win_rate = s['wins'] / s['bets']
        roi = (s['returned'] - s['staked']) / s['staked'] * 100
        avg_odds = s['odds_sum'] / s['bets']
        ev = win_rate * (avg_odds - 1) - (1 - win_rate)
        results[combo] = {
            'bets': s['bets'],
            'wins': s['wins'],
            'win_rate': round(win_rate * 100, 1),
            'roi': round(roi, 2),
            'ev': round(ev, 4),
            'avg_odds': round(avg_odds, 3),
        }
    return results


# ─── RL Training Data ─────────────────────────────────────────────────────────

def build_rl_training_data(
    features_list: List[dict],
    targets: List[int],
    df: pd.DataFrame,
    rf_model,
    feature_names: List[str],
) -> List[dict]:
    """
    Строим RL training data с РЕАЛЬНЫМИ выходами RF модели.
    Сохраняется как JSON — только базовые типы Python.
    """
    # Batch RF predictions
    if rf_model is not None and feature_names:
        log.info("  Building feature matrix for RF batch prediction...")
        X_rows = []
        for cf in features_list:
            row_series = pd.Series({k: v for k, v in cf.items() if not k.startswith('_')})
            row_aligned = row_series.reindex(feature_names, fill_value=0.0)
            X_rows.append(row_aligned.values)
        X = np.array(X_rows, dtype=np.float32)
        try:
            confidences = rf_model.predict_proba(X)[:, 1]
            log.info(
                f"  RF confidence: mean={confidences.mean():.3f}, "
                f"std={confidences.std():.3f}, "
                f"range=[{confidences.min():.3f}, {confidences.max():.3f}]"
            )
        except Exception as e:
            log.error(f"  RF predict failed: {e}")
            confidences = np.full(len(features_list), 0.5)
    else:
        confidences = np.full(len(features_list), 0.5)
        log.warning("  Using neutral confidence 0.5 (no RF model)")

    training_data = []
    for cf, target_break, conf in zip(features_list, targets, confidences):
        row_idx = cf.get('_row_idx')
        if row_idx is None or row_idx >= len(df):
            continue

        row = df.iloc[row_idx]
        home_odds = float(row.get('home_odds', 2.0))
        away_odds = float(row.get('away_odds', 2.0))
        home_win = int(row.get('home_win', 0))

        synergy_home = cf.get('critical_synergy_home', 0)
        synergy_away = cf.get('critical_synergy_away', 0)

        if synergy_home >= synergy_away and synergy_home > 0:
            bet_odds = away_odds
            actual_win = (home_win == 0)
        elif synergy_away > synergy_home and synergy_away > 0:
            bet_odds = home_odds
            actual_win = (home_win == 1)
        else:
            # No synergy → no actionable signal → skip
            # Including these with target_break as actual_win (2.5% WR)
            # poisoned RL training data with 79% garbage records
            continue

        implied_prob = 1.0 / max(bet_odds, 1.01)

        training_data.append({
            'model_confidence': round(float(conf), 4),
            'predicted_probability': round(float(implied_prob), 4),
            'odds': round(float(bet_odds), 3),
            'home_series': float(cf.get('home_overall_win_streak', 0)),
            'away_series': float(cf.get('away_overall_win_streak', 0)),
            'h2h_advantage': float(cf.get('h2h_advantage', 0)),
            'actual_win': bool(actual_win),
            'season': str(row.get('season', '')),
            'date': str(row.get('date', '')),
            'home_team': str(row.get('home_team', '')),
            'away_team': str(row.get('away_team', '')),
            'critical_pattern_exists': int(cf.get('critical_pattern_exists', 0)),
            'synergy_level': int(max(synergy_home, synergy_away)),
        })

    log.info(f"  RL training records: {len(training_data)}")
    n_crit = sum(1 for r in training_data if r['critical_pattern_exists'])
    log.info(f"  Critical pattern records: {n_crit} ({100*n_crit/max(len(training_data),1):.1f}%)")
    return training_data


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("NHL HISTORICAL BACKTEST PIPELINE")
    log.info(f"Started: {_ts}")
    log.info("=" * 60)

    # ── 1. Load data ──────────────────────────────────────────────
    log.info("\n[1/5] Loading NHL historical data...")
    try:
        df = load_all_odds_data()
        if df.empty:
            log.critical("No data loaded. Check data/odds/sbro-*.csv")
            sys.exit(1)
        df = add_underdog_info(df)
        df['game_id'] = range(len(df))
        df = df.sort_values('date').reset_index(drop=True)
        log.info(f"Loaded {len(df)} matches, {df['season'].nunique()} seasons")
        log.info(f"Date range: {df['date'].min()} → {df['date'].max()}")
    except Exception as e:
        log.critical(f"Data loading failed: {e}", exc_info=True)
        sys.exit(1)

    # ── 2. Load RF model ──────────────────────────────────────────
    log.info("\n[2/5] Loading RF model...")
    rf_model, feature_names = load_rf_model()

    # ── 3. Build features ─────────────────────────────────────────
    log.info("\n[3/5] Building pattern features (~10-15 min)...")
    fb = FeatureBuilder()
    pe = fb.pattern_engine

    features_list = []
    targets = []
    team_game_count: dict = defaultdict(int)
    skipped = 0

    for idx in range(len(df)):
        row = df.iloc[idx]
        home_team, away_team = row['home_team'], row['away_team']

        if (team_game_count[home_team] < MIN_HISTORY or
                team_game_count[away_team] < MIN_HISTORY):
            team_game_count[home_team] += 1
            team_game_count[away_team] += 1
            skipped += 1
            continue

        history = df.iloc[:idx]
        game_date = row['date']

        try:
            home_f = pe.get_pattern_features(home_team, away_team, history, game_date)
            away_f = pe.get_pattern_features(away_team, home_team, history, game_date)
        except Exception as e:
            log.warning(f"[{idx}] {home_team} vs {away_team}: {e}")
            team_game_count[home_team] += 1
            team_game_count[away_team] += 1
            skipped += 1
            continue

        if home_f is None or away_f is None:
            team_game_count[home_team] += 1
            team_game_count[away_team] += 1
            skipped += 1
            continue

        cf = build_feature_row(home_f, away_f, fb)
        cf['_row_idx'] = idx

        target_break = fb._calculate_target_combined(home_f, away_f, int(row['home_win']))
        features_list.append(cf)
        targets.append(int(target_break))

        team_game_count[home_team] += 1
        team_game_count[away_team] += 1

        if idx % 500 == 0 and idx > 0:
            log.info(f"  Progress: {idx}/{len(df)} | features={len(features_list)}")

    log.info(f"Features built: {len(features_list)} ({skipped} skipped)")

    features_df = pd.DataFrame([
        {k: v for k, v in cf.items() if not k.startswith('_')}
        for cf in features_list
    ])
    targets_arr = np.array(targets)
    n_critical = int((features_df['critical_pattern_exists'] == 1).sum())
    log.info(f"Break rate (all): {targets_arr.mean():.3f}")
    log.info(f"Critical matches: {n_critical} ({100*n_critical/max(len(features_df),1):.1f}%)")

    # ── 4. Calibrate break rates ──────────────────────────────────
    log.info("\n[4/5] Calibrating break rates by pattern type...")
    analyzer = PatternAnalyzer()
    break_rates = analyzer.analyze_break_rates_by_pattern_type(
        features_df, targets_arr, None
    )

    # ── 5a. Simulate betting ──────────────────────────────────────
    log.info("\n[5a/5] Simulating betting by pattern combination...")
    combo_results = simulate_betting(features_list, df)
    sorted_combos = sorted(combo_results.items(), key=lambda x: x[1]['roi'], reverse=True)

    log.info(f"\nTop 10 pattern combos by ROI:")
    log.info(f"{'Combination':<55} {'Bets':>5} {'WR%':>6} {'ROI%':>8} {'EV':>8}")
    log.info("-" * 85)
    for combo, stats in sorted_combos[:10]:
        log.info(
            f"{combo:<55} {stats['bets']:>5} "
            f"{stats['win_rate']:>6.1f} {stats['roi']:>8.2f} {stats['ev']:>8.4f}"
        )

    # ── 5b. Build RL training data ────────────────────────────────
    log.info("\n[5b/5] Building RL training data with real RF confidence...")
    rl_data = build_rl_training_data(features_list, targets, df, rf_model, feature_names)

    # ── Save results ──────────────────────────────────────────────
    results = {
        'timestamp': _ts,
        'total_matches_in_csv': len(df),
        'features_built': len(features_list),
        'critical_matches': n_critical,
        'overall_break_rate': float(targets_arr.mean()),
        'break_rates_by_pattern': break_rates,
        'top_combos_by_roi': {k: v for k, v in sorted_combos[:20]},
        'total_combos_found': len(combo_results),
    }

    results_path = f'data/backtest_results/nhl_backtest_{_ts}.json'
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"\nBacktest results: {results_path}")

    rl_path = 'data/backtest_results/rl_training_data.json'
    with open(rl_path, 'w', encoding='utf-8') as f:
        json.dump(rl_data, f)
    log.info(f"RL training data: {rl_path} ({len(rl_data)} records)")

    # Save feature matrix via joblib (sklearn-standard, safe for numpy)
    feat_path = 'data/backtest_results/feature_matrix.joblib'
    joblib.dump({'features_df': features_df, 'targets': targets_arr}, feat_path)
    log.info(f"Feature matrix:   {feat_path}")

    log.info("\n" + "=" * 60)
    log.info("BACKTEST COMPLETE")
    log.info(f"  Matches processed:   {len(features_list)}")
    log.info(f"  RL training records: {len(rl_data)}")
    log.info(f"  Pattern combos:      {len(combo_results)}")
    if sorted_combos:
        best = sorted_combos[0]
        log.info(f"  Best ROI combo:      {best[0]} → {best[1]['roi']:.2f}%")
    log.info("=" * 60)


if __name__ == '__main__':
    main()
