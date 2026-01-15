#!/usr/bin/env python3
"""
Бэктест CPP с фильтром по коэффициентам
Проверяем: улучшает ли фильтр min_odds качество ставок
"""

import pandas as pd
import numpy as np
from collections import defaultdict

from src.odds_loader import OddsLoader
from src.pattern_engine import PatternEngine


def calculate_cpp_signals(games_df):
    engine = PatternEngine()
    signals = []
    
    games_sorted = games_df.sort_values('date').reset_index(drop=True)
    
    for idx in range(20, len(games_sorted)):
        row = games_sorted.iloc[idx]
        history = games_sorted.iloc[:idx]
        
        home_team = row['home_team']
        away_team = row['away_team']
        
        home_features = engine.get_pattern_features(home_team, away_team, history, row['date'])
        away_features = engine.get_pattern_features(away_team, home_team, history, row['date'])
        
        home_synergy = 0
        away_synergy = 0
        home_patterns = []
        away_patterns = []
        
        if home_features.get('home_streak_critical'):
            streak = home_features.get('home_win_streak', 0)
            if streak > 0:
                away_synergy += 1
                away_patterns.append('HomeWin→Break')
            else:
                home_synergy += 1
                home_patterns.append('HomeLoss→Break')
                
        if home_features.get('h2h_streak_critical'):
            streak = home_features.get('h2h_win_streak', 0)
            if streak > 0:
                away_synergy += 1
                away_patterns.append('H2H_Home→Break')
            else:
                home_synergy += 1
                home_patterns.append('H2H_Away→Break')
                
        if home_features.get('overall_streak_critical'):
            streak = home_features.get('overall_win_streak', 0)
            if streak > 0:
                away_synergy += 1
                away_patterns.append('Overall→Break')
            else:
                home_synergy += 1
                home_patterns.append('OverallLoss→Break')
                
        if away_features.get('away_streak_critical'):
            streak = away_features.get('away_win_streak', 0)
            if streak > 0:
                home_synergy += 1
                home_patterns.append('AwayWin→Break')
            else:
                away_synergy += 1
                away_patterns.append('AwayLoss→Break')
        
        signals.append({
            'idx': idx,
            'date': row['date'],
            'home_team': home_team,
            'away_team': away_team,
            'home_synergy': home_synergy,
            'away_synergy': away_synergy,
            'home_patterns': '+'.join(sorted(home_patterns)) if home_patterns else '',
            'away_patterns': '+'.join(sorted(away_patterns)) if away_patterns else '',
            'home_win': row.get('home_win', None),
            'home_odds': row.get('home_odds', None),
            'away_odds': row.get('away_odds', None),
        })
        
        if idx % 1000 == 0:
            print(f"  Processed {idx}/{len(games_sorted)}...")
    
    return pd.DataFrame(signals)


def test_odds_filter(signals_df, min_synergy=2, min_odds=1.0, max_odds=10.0, stake=100):
    total = {'wins': 0, 'bets': 0, 'staked': 0, 'return': 0}
    filtered_out = 0
    
    for _, row in signals_df.iterrows():
        bet_side = None
        odds = None
        
        if row['home_synergy'] >= min_synergy and row['away_synergy'] < row['home_synergy']:
            bet_side = 'home'
            odds = row.get('home_odds')
        elif row['away_synergy'] >= min_synergy and row['home_synergy'] < row['away_synergy']:
            bet_side = 'away'
            odds = row.get('away_odds')
        
        if not bet_side or pd.isna(odds):
            continue
        
        if odds < min_odds or odds > max_odds:
            filtered_out += 1
            continue
            
        result = row['home_win'] if bet_side == 'home' else (1 - row['home_win'] if pd.notna(row['home_win']) else None)
        
        if pd.notna(result):
            total['bets'] += 1
            total['staked'] += stake
            
            if result == 1:
                total['wins'] += 1
                total['return'] += stake * odds
    
    if total['bets'] == 0:
        return None
    
    win_rate = total['wins'] / total['bets'] * 100
    profit = total['return'] - total['staked']
    roi = profit / total['staked'] * 100
    
    return {
        'min_odds': min_odds,
        'max_odds': max_odds,
        'bets': total['bets'],
        'wins': total['wins'],
        'win_rate': win_rate,
        'profit': profit,
        'roi': roi,
        'filtered_out': filtered_out
    }


def run_full_odds_filter_test():
    print("Loading data...")
    odds_loader = OddsLoader()
    odds_df = odds_loader.load_all_odds()
    
    if len(odds_df) == 0:
        print("No data")
        return None
    
    print(f"\nCalculating CPP signals for {len(odds_df)} matches...")
    signals_df = calculate_cpp_signals(odds_df)
    print(f"Done! {len(signals_df)} signals calculated.\n")
    
    results = []
    
    print("="*70)
    print("TEST 1: Different MIN_ODDS thresholds")
    print("="*70)
    
    for min_odds in [1.0, 1.40, 1.50, 1.60, 1.70, 1.80, 2.00]:
        r = test_odds_filter(signals_df, min_synergy=2, min_odds=min_odds)
        if r:
            print(f"  min_odds={min_odds:.2f}: {r['bets']} bets, {r['win_rate']:.1f}% win, {r['roi']:+.1f}% ROI")
            results.append(r)
    
    print("\n" + "="*70)
    print("TEST 2: Different MAX_ODDS thresholds")
    print("="*70)
    
    for max_odds in [2.0, 2.5, 3.0, 4.0, 10.0]:
        r = test_odds_filter(signals_df, min_synergy=2, min_odds=1.0, max_odds=max_odds)
        if r:
            print(f"  max_odds={max_odds:.2f}: {r['bets']} bets, {r['win_rate']:.1f}% win, {r['roi']:+.1f}% ROI")
            results.append({'type': 'max', **r})
    
    print("\n" + "="*70)
    print("TEST 3: Combined filters (sweet spot)")
    print("="*70)
    
    for min_odds in [1.50, 1.60, 1.70]:
        for max_odds in [2.5, 3.0, 3.5]:
            r = test_odds_filter(signals_df, min_synergy=2, min_odds=min_odds, max_odds=max_odds)
            if r:
                print(f"  [{min_odds:.2f}, {max_odds:.2f}]: {r['bets']} bets, {r['win_rate']:.1f}% win, {r['roi']:+.1f}% ROI")
                results.append({'type': 'combined', **r})
    
    print("\n" + "="*70)
    print("SUMMARY: Best configurations")
    print("="*70)
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('roi', ascending=False)
    
    print(f"\n{'Min Odds':<10} {'Max Odds':<10} {'Bets':<8} {'Win%':<8} {'ROI':<10}")
    print("-"*50)
    for _, r in results_df.head(10).iterrows():
        print(f"{r['min_odds']:<10.2f} {r['max_odds']:<10.2f} {r['bets']:<8} {r['win_rate']:.1f}%{'':<3} {r['roi']:+.1f}%")
    
    return results_df


if __name__ == "__main__":
    run_full_odds_filter_test()
