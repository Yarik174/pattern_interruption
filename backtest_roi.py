#!/usr/bin/env python3
"""
ROI Backtest для CPP Strategy
Расчёт исторической доходности стратегии прерывания паттернов
"""

import pandas as pd
import numpy as np
from datetime import datetime

from src.odds_loader import OddsLoader
from src.pattern_engine import PatternEngine
from src.config import CRITICAL_THRESHOLDS


def calculate_cpp_signals(games_df):
    """
    Рассчитать CPP сигналы для каждого матча
    """
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
                away_patterns.append(f"Home win streak {streak} (break)")
            else:
                home_synergy += 1
                home_patterns.append(f"Home loss streak {abs(streak)} (break)")
                
        if home_features.get('h2h_streak_critical'):
            streak = home_features.get('h2h_win_streak', 0)
            if streak > 0:
                away_synergy += 1
                away_patterns.append(f"H2H home streak {streak}")
            else:
                home_synergy += 1
                home_patterns.append(f"H2H away streak {abs(streak)}")
                
        if home_features.get('overall_streak_critical'):
            streak = home_features.get('overall_win_streak', 0)
            if streak > 0:
                away_synergy += 1
                away_patterns.append(f"Overall streak {streak}")
            else:
                home_synergy += 1
                home_patterns.append(f"Overall loss streak {abs(streak)}")
                
        if away_features.get('away_streak_critical'):
            streak = away_features.get('away_win_streak', 0)
            if streak > 0:
                home_synergy += 1
                home_patterns.append(f"Away win streak {streak} (break)")
            else:
                away_synergy += 1
                away_patterns.append(f"Away loss streak {abs(streak)}")
        
        signals.append({
            'idx': idx,
            'date': row['date'],
            'home_team': home_team,
            'away_team': away_team,
            'home_synergy': home_synergy,
            'away_synergy': away_synergy,
            'home_patterns': home_patterns,
            'away_patterns': away_patterns,
            'home_win': row.get('home_win', None)
        })
        
        if idx % 200 == 0:
            print(f"  Обработано {idx}/{len(games_sorted)} матчей...")
    
    return pd.DataFrame(signals)


def run_backtest(min_synergy=2, stake=100):
    """
    Запустить бэктест CPP стратегии
    """
    print("=" * 60)
    print("🎯 CPP Strategy Backtest")
    print("=" * 60)
    
    print("\n📥 Загрузка исторических коэффициентов...")
    odds_loader = OddsLoader()
    odds_df = odds_loader.load_all_odds()
    
    if len(odds_df) == 0:
        print("❌ Нет данных для бэктеста")
        return
        
    print(f"\n🔍 Расчёт CPP сигналов для {len(odds_df)} матчей...")
    signals_df = calculate_cpp_signals(odds_df)
    
    merged = signals_df.merge(
        odds_df[['date', 'home_team', 'away_team', 'home_odds', 'away_odds', 'home_win']],
        on=['date', 'home_team', 'away_team'],
        how='left',
        suffixes=('', '_odds')
    )
    
    if 'home_win_odds' in merged.columns:
        merged['home_win'] = merged['home_win_odds']
        merged.drop(columns=['home_win_odds'], inplace=True)
    
    results = {
        'total_bets': 0,
        'wins': 0,
        'losses': 0,
        'total_staked': 0,
        'total_return': 0,
        'bets': []
    }
    
    print(f"\n📊 Бэктест с минимальной синергией = {min_synergy}")
    print("-" * 40)
    
    for _, row in merged.iterrows():
        bet = None
        
        if row['home_synergy'] >= min_synergy and row['away_synergy'] < row['home_synergy']:
            if pd.notna(row.get('home_odds')):
                bet = {
                    'date': row['date'],
                    'match': f"{row['away_team']} @ {row['home_team']}",
                    'bet_on': 'home',
                    'team': row['home_team'],
                    'odds': row['home_odds'],
                    'synergy': row['home_synergy'],
                    'patterns': row['home_patterns'],
                    'actual_result': row['home_win']
                }
                
        elif row['away_synergy'] >= min_synergy and row['home_synergy'] < row['away_synergy']:
            if pd.notna(row.get('away_odds')):
                bet = {
                    'date': row['date'],
                    'match': f"{row['away_team']} @ {row['home_team']}",
                    'bet_on': 'away',
                    'team': row['away_team'],
                    'odds': row['away_odds'],
                    'synergy': row['away_synergy'],
                    'patterns': row['away_patterns'],
                    'actual_result': 1 - row['home_win'] if pd.notna(row['home_win']) else None
                }
        
        if bet and pd.notna(bet['actual_result']):
            results['total_bets'] += 1
            results['total_staked'] += stake
            
            if bet['actual_result'] == 1:
                results['wins'] += 1
                results['total_return'] += stake * bet['odds']
            else:
                results['losses'] += 1
                
            results['bets'].append(bet)
    
    print("\n" + "=" * 60)
    print("📈 РЕЗУЛЬТАТЫ БЭКТЕСТА")
    print("=" * 60)
    
    if results['total_bets'] > 0:
        win_rate = results['wins'] / results['total_bets']
        profit = results['total_return'] - results['total_staked']
        roi = profit / results['total_staked']
        
        print(f"\n  Всего ставок: {results['total_bets']}")
        print(f"  Выигрышей: {results['wins']} ({win_rate:.1%})")
        print(f"  Проигрышей: {results['losses']}")
        print(f"\n  💰 Поставлено: ${results['total_staked']:,.0f}")
        print(f"  💵 Возврат: ${results['total_return']:,.0f}")
        print(f"  📊 Профит: ${profit:,.0f}")
        print(f"  📈 ROI: {roi:.1%}")
        
        avg_odds = np.mean([b['odds'] for b in results['bets']])
        print(f"\n  Средний коэффициент: {avg_odds:.2f}")
        
        print("\n  Примеры ставок:")
        for bet in results['bets'][:5]:
            result = "✅" if bet['actual_result'] == 1 else "❌"
            print(f"    {result} {bet['date'].strftime('%Y-%m-%d')} {bet['match']} → {bet['team']} @{bet['odds']:.2f}")
            
        synergy_stats = {}
        for bet in results['bets']:
            s = bet['synergy']
            if s not in synergy_stats:
                synergy_stats[s] = {'wins': 0, 'total': 0}
            synergy_stats[s]['total'] += 1
            synergy_stats[s]['wins'] += bet['actual_result']
            
        print("\n  Результаты по синергии:")
        for s in sorted(synergy_stats.keys()):
            stats = synergy_stats[s]
            wr = stats['wins'] / stats['total']
            print(f"    Синергия {s}: {stats['wins']}/{stats['total']} = {wr:.1%}")
    else:
        print("\n  ❌ Нет ставок с заданными критериями")
        
    return results


if __name__ == '__main__':
    print("\n🎯 Тест 1: Минимальная синергия = 2")
    results_2 = run_backtest(min_synergy=2)
    
    print("\n\n" + "=" * 60)
    print("\n🎯 Тест 2: Минимальная синергия = 3")
    results_3 = run_backtest(min_synergy=3)
