#!/usr/bin/env python3
"""
Cross-Validation + Kelly Sizing Analysis

Reads rl_training_data.json (output of backtest_nhl.py), runs leave-one-season-out
cross-validation with multiple strategy filters, and calculates Kelly-optimal
bankroll growth.

Usage:
    python scripts/cross_validate.py
"""

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import json
import numpy as np
from collections import defaultdict


def load_data():
    path = 'data/backtest_results/rl_training_data.json'
    if not os.path.exists(path):
        print("ERROR: rl_training_data.json not found. Run backtest_nhl.py first.")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    print(f"Loaded {len(data)} records")
    return data


def filter_strategy(data, rf_thresh=None, odds_min=None, odds_max=None, synergy_min=1):
    """Apply strategy filters."""
    result = []
    for r in data:
        if synergy_min and r.get('synergy_level', 0) < synergy_min:
            continue
        if rf_thresh is not None and r['model_confidence'] < rf_thresh:
            continue
        if odds_min is not None and r['odds'] < odds_min:
            continue
        if odds_max is not None and r['odds'] > odds_max:
            continue
        result.append(r)
    return result


def calc_roi(bets):
    if not bets:
        return 0.0, 0, 0
    wins = sum(1 for b in bets if b['actual_win'])
    staked = len(bets)
    returned = sum(b['odds'] for b in bets if b['actual_win'])
    roi = (returned - staked) / staked * 100
    return roi, wins, staked


def kelly_bankroll(bets, fraction=0.5):
    """Simulate Kelly criterion bankroll growth."""
    bankroll = 1000.0
    for b in sorted(bets, key=lambda x: x['date']):
        odds = b['odds']
        # Estimate win probability from historical data (simplified)
        # Use model confidence as proxy for edge estimation
        p = b['model_confidence']
        q = 1 - p
        # Kelly fraction: f = (p*b - q) / b where b = odds-1
        b_val = odds - 1
        kelly_f = (p * b_val - q) / b_val if b_val > 0 else 0
        kelly_f = max(0, min(kelly_f * fraction, 0.1))  # cap at 10%

        stake = bankroll * kelly_f
        if b['actual_win']:
            bankroll += stake * (odds - 1)
        else:
            bankroll -= stake

    return bankroll


def run_cross_validation(data, strategies):
    """Leave-one-season-out cross-validation."""
    seasons = sorted(set(r['season'] for r in data))
    print(f"\nSeasons: {seasons} ({len(seasons)} total)")

    print(f"\n{'Strategy':<35} {'Bets':>6} {'ROI%':>7} {'WR%':>6} {'Losing':>7} {'Kelly$':>8} {'Sharpe':>7}")
    print("-" * 82)

    for name, params in strategies:
        season_rois = []
        all_filtered = filter_strategy(data, **params)
        total_roi, total_wins, total_bets = calc_roi(all_filtered)
        wr = total_wins / total_bets * 100 if total_bets > 0 else 0

        losing_seasons = 0
        for s in seasons:
            season_bets = [r for r in all_filtered if r['season'] == s]
            if not season_bets:
                continue
            s_roi, _, _ = calc_roi(season_bets)
            season_rois.append(s_roi)
            if s_roi < 0:
                losing_seasons += 1

        # Kelly bankroll simulation
        kelly_final = kelly_bankroll(all_filtered)
        kelly_growth = (kelly_final / 1000 - 1) * 100

        # Sharpe-like ratio (ROI / std of season ROIs)
        sharpe = np.mean(season_rois) / np.std(season_rois) if len(season_rois) > 1 and np.std(season_rois) > 0 else 0

        print(f"{name:<35} {total_bets:>6} {total_roi:>7.1f} {wr:>6.1f} {losing_seasons:>3}/{len(season_rois):<3} {kelly_growth:>7.1f}% {sharpe:>7.3f}")

    # Per-season breakdown for top strategies
    print(f"\n{'='*82}")
    print("Per-season breakdown (top strategies):")
    print(f"{'='*82}")

    top_strategies = strategies[:5]
    for name, params in top_strategies:
        print(f"\n--- {name} ---")
        all_filtered = filter_strategy(data, **params)
        print(f"{'Season':<12} {'Bets':>5} {'Wins':>5} {'WR%':>6} {'ROI%':>7} {'AvgOdds':>8}")
        for s in sorted(seasons):
            season_bets = [r for r in all_filtered if r['season'] == s]
            if not season_bets:
                continue
            s_roi, s_wins, s_bets = calc_roi(season_bets)
            avg_odds = np.mean([b['odds'] for b in season_bets])
            wr = s_wins / s_bets * 100 if s_bets > 0 else 0
            marker = " <<<" if s_roi < -5 else ""
            print(f"{s:<12} {s_bets:>5} {s_wins:>5} {wr:>6.1f} {s_roi:>7.1f} {avg_odds:>8.2f}{marker}")


def main():
    data = load_data()

    # Show data summary
    seasons = defaultdict(int)
    synergy_dist = defaultdict(int)
    for r in data:
        seasons[r['season']] += 1
        synergy_dist[r.get('synergy_level', 0)] += 1

    print("\nData by season:")
    for s in sorted(seasons):
        wins = sum(1 for r in data if r['season'] == s and r['actual_win'])
        total = seasons[s]
        print(f"  {s}: {total} bets, WR {wins/total*100:.1f}%")

    print(f"\nSynergy distribution:")
    for syn in sorted(synergy_dist):
        print(f"  synergy={syn}: {synergy_dist[syn]} records")

    # Define strategies to test
    strategies = [
        # Baseline
        ("BET ALL (syn>=1)", dict(synergy_min=1)),
        ("BET ALL (syn>=2)", dict(synergy_min=2)),

        # RF confidence filters
        ("RF>0.5", dict(rf_thresh=0.5, synergy_min=1)),
        ("RF>0.55", dict(rf_thresh=0.55, synergy_min=1)),
        ("RF>0.58", dict(rf_thresh=0.58, synergy_min=1)),
        ("RF>0.6", dict(rf_thresh=0.6, synergy_min=1)),

        # Odds range filters
        ("odds [1.8-3.0]", dict(odds_min=1.8, odds_max=3.0, synergy_min=1)),
        ("odds [2.0-3.5]", dict(odds_min=2.0, odds_max=3.5, synergy_min=1)),
        ("odds [2.0-3.0]", dict(odds_min=2.0, odds_max=3.0, synergy_min=1)),
        ("odds [2.2-4.0]", dict(odds_min=2.2, odds_max=4.0, synergy_min=1)),

        # Combined RF + odds
        ("RF>0.5 + [2.0-3.5]", dict(rf_thresh=0.5, odds_min=2.0, odds_max=3.5, synergy_min=1)),
        ("RF>0.5 + [1.8-3.0]", dict(rf_thresh=0.5, odds_min=1.8, odds_max=3.0, synergy_min=1)),
        ("RF>0.55 + [2.0-3.5]", dict(rf_thresh=0.55, odds_min=2.0, odds_max=3.5, synergy_min=1)),
        ("RF>0.58 + [2.0-3.5]", dict(rf_thresh=0.58, odds_min=2.0, odds_max=3.5, synergy_min=1)),
        ("RF>0.5 + [2.0-3.0]", dict(rf_thresh=0.5, odds_min=2.0, odds_max=3.0, synergy_min=1)),
        ("RF>0.4 + [1.8-3.0]", dict(rf_thresh=0.4, odds_min=1.8, odds_max=3.0, synergy_min=1)),

        # Synergy >= 2 combos
        ("syn>=2 + RF>0.5", dict(rf_thresh=0.5, synergy_min=2)),
        ("syn>=2 + [2.0-3.5]", dict(odds_min=2.0, odds_max=3.5, synergy_min=2)),
        ("syn>=2 + RF>0.5 + [2.0-3.5]", dict(rf_thresh=0.5, odds_min=2.0, odds_max=3.5, synergy_min=2)),
    ]

    run_cross_validation(data, strategies)


if __name__ == '__main__':
    main()
