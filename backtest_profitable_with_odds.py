#!/usr/bin/env python3
"""
Бэктест прибыльных комбинаций CPP с фильтром по коэффициентам
"""

import pandas as pd
import numpy as np
from collections import defaultdict

from src.odds_loader import OddsLoader
from src.pattern_engine import PatternEngine


PROFITABLE_PATTERNS = [
    'AwayLoss→Break+HomeWin→Break+Overall→Break',
    'H2H_Away→Break+HomeLoss→Break',
    'AwayLoss→Break+HomeWin→Break',
    'AwayLoss→Break+H2H_Home→Break+HomeWin→Break',
    'H2H_Home→Break+Overall→Break',
    'AwayLoss→Break+Overall→Break',
]


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


def test_profitable_patterns(signals_df, min_odds=1.0, max_odds=10.0, stake=100):
    results_by_pattern = {}
    total = {'wins': 0, 'bets': 0, 'staked': 0, 'return': 0}
    
    for _, row in signals_df.iterrows():
        bet_side = None
        odds = None
        patterns = ''
        
        if row['home_synergy'] >= 2 and row['away_synergy'] < row['home_synergy']:
            bet_side = 'home'
            odds = row.get('home_odds')
            patterns = row['home_patterns']
        elif row['away_synergy'] >= 2 and row['home_synergy'] < row['away_synergy']:
            bet_side = 'away'
            odds = row.get('away_odds')
            patterns = row['away_patterns']
        
        if not bet_side or pd.isna(odds) or not patterns:
            continue
        
        if patterns not in PROFITABLE_PATTERNS:
            continue
        
        if odds < min_odds or odds > max_odds:
            continue
            
        result = row['home_win'] if bet_side == 'home' else (1 - row['home_win'] if pd.notna(row['home_win']) else None)
        
        if pd.notna(result):
            if patterns not in results_by_pattern:
                results_by_pattern[patterns] = {'wins': 0, 'bets': 0, 'staked': 0, 'return': 0}
            
            results_by_pattern[patterns]['bets'] += 1
            results_by_pattern[patterns]['staked'] += stake
            total['bets'] += 1
            total['staked'] += stake
            
            if result == 1:
                results_by_pattern[patterns]['wins'] += 1
                results_by_pattern[patterns]['return'] += stake * odds
                total['wins'] += 1
                total['return'] += stake * odds
    
    return total, results_by_pattern


def run_test():
    print("Loading data...")
    odds_loader = OddsLoader()
    odds_df = odds_loader.load_all_odds()
    
    print(f"\nCalculating CPP signals...")
    signals_df = calculate_cpp_signals(odds_df)
    print(f"Done! {len(signals_df)} signals.\n")
    
    print("="*70)
    print("PROFITABLE PATTERNS ONLY (no odds filter)")
    print("="*70)
    
    total, by_pattern = test_profitable_patterns(signals_df)
    
    if total['bets'] > 0:
        win_rate = total['wins'] / total['bets'] * 100
        profit = total['return'] - total['staked']
        roi = profit / total['staked'] * 100
        print(f"\nTotal: {total['bets']} bets, {win_rate:.1f}% win, {roi:+.1f}% ROI")
        
        print(f"\nBy pattern:")
        for p, stats in sorted(by_pattern.items(), key=lambda x: x[1]['bets'], reverse=True):
            if stats['bets'] > 0:
                wr = stats['wins'] / stats['bets'] * 100
                pr = stats['return'] - stats['staked']
                r = pr / stats['staked'] * 100
                print(f"  {p[:50]}: {stats['bets']} bets, {wr:.1f}% win, {r:+.1f}% ROI")
    
    print("\n" + "="*70)
    print("WITH ODDS FILTERS")
    print("="*70)
    
    configs = [
        (1.0, 10.0),
        (1.50, 10.0),
        (1.60, 10.0),
        (1.70, 10.0),
        (1.50, 3.0),
        (1.60, 3.0),
        (1.70, 3.0),
        (1.80, 2.5),
        (2.0, 3.5),
    ]
    
    results = []
    for min_odds, max_odds in configs:
        total, _ = test_profitable_patterns(signals_df, min_odds=min_odds, max_odds=max_odds)
        if total['bets'] > 0:
            win_rate = total['wins'] / total['bets'] * 100
            profit = total['return'] - total['staked']
            roi = profit / total['staked'] * 100
            results.append({
                'min_odds': min_odds,
                'max_odds': max_odds,
                'bets': total['bets'],
                'win_rate': win_rate,
                'roi': roi
            })
            print(f"  [{min_odds:.2f}, {max_odds:.2f}]: {total['bets']} bets, {win_rate:.1f}% win, {roi:+.1f}% ROI")
    
    print("\n" + "="*70)
    print("BEST CONFIGURATIONS")
    print("="*70)
    results_df = pd.DataFrame(results).sort_values('roi', ascending=False)
    print(results_df.head(10).to_string(index=False))


if __name__ == "__main__":
    run_test()
