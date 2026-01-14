#!/usr/bin/env python3
"""
ROI Backtest для CPP Strategy
Расчёт исторической доходности стратегии прерывания паттернов
Поддержка Money Line (Final) и 1X2 (Regulation) типов ставок
"""

import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict

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
        
        if home_features.get('home_alt_critical'):
            exp = home_features.get('home_expected_alt', -1)
            if exp == 1:
                home_synergy += 1
                home_patterns.append('HomeAlt→Win')
            elif exp == 0:
                away_synergy += 1
                away_patterns.append('HomeAlt→Loss')
        
        if away_features.get('away_alt_critical'):
            exp = away_features.get('away_expected_alt', -1)
            if exp == 1:
                away_synergy += 1
                away_patterns.append('AwayAlt→Win')
            elif exp == 0:
                home_synergy += 1
                home_patterns.append('AwayAlt→Loss')
        
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
            'overtime': row.get('overtime', 0),
            'regulation_result': row.get('regulation_result', None)
        })
        
        if idx % 500 == 0:
            print(f"  Обработано {idx}/{len(games_sorted)} матчей...")
    
    return pd.DataFrame(signals)


def run_backtest_comparison(min_synergy=2, stake=100):
    """
    Запустить бэктест CPP стратегии с сравнением Money Line и 1X2
    """
    print("=" * 70)
    print("📊 CPP Backtest: Money Line vs 1X2")
    print("=" * 70)
    
    print("\n📥 Загрузка исторических коэффициентов...")
    odds_loader = OddsLoader()
    odds_df = odds_loader.load_all_odds()
    
    if len(odds_df) == 0:
        print("❌ Нет данных для бэктеста")
        return
    
    has_overtime_data = (odds_df['overtime'] == 1).sum() > 0
    print(f"  Данные с овертаймом: {'✅ Да' if has_overtime_data else '❌ Нет (только Money Line)'}")
        
    print(f"\n🔍 Расчёт CPP сигналов для {len(odds_df)} матчей...")
    signals_df = calculate_cpp_signals(odds_df)
    
    merge_cols = ['date', 'home_team', 'away_team', 'home_odds', 'away_odds', 
                  'home_win', 'overtime', 'regulation_result']
    merge_cols = [c for c in merge_cols if c in odds_df.columns]
    
    merged = signals_df.merge(
        odds_df[merge_cols],
        on=['date', 'home_team', 'away_team'],
        how='left',
        suffixes=('', '_odds')
    )
    
    for col in ['home_win', 'overtime', 'regulation_result']:
        if f'{col}_odds' in merged.columns:
            merged[col] = merged[f'{col}_odds']
            merged.drop(columns=[f'{col}_odds'], inplace=True)
    
    ml_by_pattern = defaultdict(lambda: {'wins': 0, 'total': 0, 'staked': 0, 'return': 0})
    x12_by_pattern = defaultdict(lambda: {'wins': 0, 'total': 0, 'staked': 0, 'return': 0})
    
    ml_total = {'wins': 0, 'total': 0, 'staked': 0, 'return': 0}
    x12_total = {'wins': 0, 'total': 0, 'staked': 0, 'return': 0}
    
    print(f"\n📊 Бэктест с минимальной синергией = {min_synergy}")
    print("-" * 70)
    
    for _, row in merged.iterrows():
        bet_side = None
        patterns = ''
        odds = None
        
        if row['home_synergy'] >= min_synergy and row['away_synergy'] < row['home_synergy']:
            bet_side = 'home'
            patterns = row['home_patterns']
            odds = row.get('home_odds')
        elif row['away_synergy'] >= min_synergy and row['home_synergy'] < row['away_synergy']:
            bet_side = 'away'
            patterns = row['away_patterns']
            odds = row.get('away_odds')
        
        if not bet_side or pd.isna(odds) or not patterns:
            continue
            
        ml_result = row['home_win'] if bet_side == 'home' else (1 - row['home_win'] if pd.notna(row['home_win']) else None)
        
        if pd.notna(ml_result):
            ml_total['total'] += 1
            ml_total['staked'] += stake
            ml_by_pattern[patterns]['total'] += 1
            ml_by_pattern[patterns]['staked'] += stake
            
            if ml_result == 1:
                ml_total['wins'] += 1
                ml_total['return'] += stake * odds
                ml_by_pattern[patterns]['wins'] += 1
                ml_by_pattern[patterns]['return'] += stake * odds
        
        if has_overtime_data and pd.notna(row.get('regulation_result')):
            reg_result = row['regulation_result']
            
            if bet_side == 'home':
                x12_win = 1 if reg_result == 0 else 0
            else:
                x12_win = 1 if reg_result == 1 else 0
            
            x12_total['total'] += 1
            x12_total['staked'] += stake
            x12_by_pattern[patterns]['total'] += 1
            x12_by_pattern[patterns]['staked'] += stake
            
            if x12_win == 1:
                x12_total['wins'] += 1
                x12_total['return'] += stake * odds
                x12_by_pattern[patterns]['wins'] += 1
                x12_by_pattern[patterns]['return'] += stake * odds
    
    print("\n" + "=" * 70)
    print("📈 РЕЗУЛЬТАТЫ БЭКТЕСТА")
    print("=" * 70)
    
    def calc_roi(stats):
        if stats['staked'] > 0:
            return (stats['return'] - stats['staked']) / stats['staked'] * 100
        return 0
    
    def calc_wr(stats):
        if stats['total'] > 0:
            return stats['wins'] / stats['total'] * 100
        return 0
    
    print(f"\n{'Тип ставки':<20} | {'ROI':>8} | {'Win Rate':>9} | {'Ставок':>8} | {'Профит':>10}")
    print("-" * 70)
    
    ml_roi = calc_roi(ml_total)
    ml_wr = calc_wr(ml_total)
    ml_profit = ml_total['return'] - ml_total['staked']
    print(f"{'Money Line (Final)':<20} | {ml_roi:>+7.1f}% | {ml_wr:>8.1f}% | {ml_total['total']:>8} | ${ml_profit:>+9,.0f}")
    
    if has_overtime_data and x12_total['total'] > 0:
        x12_roi = calc_roi(x12_total)
        x12_wr = calc_wr(x12_total)
        x12_profit = x12_total['return'] - x12_total['staked']
        print(f"{'1X2 (Regulation)':<20} | {x12_roi:>+7.1f}% | {x12_wr:>8.1f}% | {x12_total['total']:>8} | ${x12_profit:>+9,.0f}")
    
    print("\n" + "=" * 70)
    print("📊 СРАВНЕНИЕ ПО КОМБИНАЦИЯМ ПАТТЕРНОВ")
    print("=" * 70)
    
    all_patterns = set(ml_by_pattern.keys()) | set(x12_by_pattern.keys())
    pattern_stats = []
    
    for p in all_patterns:
        ml_stats = ml_by_pattern.get(p, {'wins': 0, 'total': 0, 'staked': 0, 'return': 0})
        x12_stats = x12_by_pattern.get(p, {'wins': 0, 'total': 0, 'staked': 0, 'return': 0})
        
        pattern_stats.append({
            'pattern': p,
            'ml_roi': calc_roi(ml_stats),
            'ml_n': ml_stats['total'],
            'x12_roi': calc_roi(x12_stats),
            'x12_n': x12_stats['total']
        })
    
    pattern_stats.sort(key=lambda x: x['ml_roi'], reverse=True)
    
    print(f"\n{'Комбинация':<40} | {'ML ROI':>8} | {'1X2 ROI':>8} | {'n (ML)':>7} | {'n (1X2)':>7}")
    print("-" * 85)
    
    for ps in pattern_stats[:15]:
        p_name = ps['pattern'][:38] + '..' if len(ps['pattern']) > 40 else ps['pattern']
        
        x12_str = f"{ps['x12_roi']:>+7.1f}%" if has_overtime_data and ps['x12_n'] > 0 else "    N/A"
        x12_n_str = f"{ps['x12_n']:>7}" if has_overtime_data else "    N/A"
        
        print(f"{p_name:<40} | {ps['ml_roi']:>+7.1f}% | {x12_str} | {ps['ml_n']:>7} | {x12_n_str}")
    
    if len(pattern_stats) > 15:
        print(f"\n  ... и ещё {len(pattern_stats) - 15} комбинаций")
    
    print("\n" + "=" * 70)
    print("📋 ЛЕГЕНДА ПАТТЕРНОВ")
    print("=" * 70)
    print("""
  HomeWin→Break    = Серия домашних побед достигла критического уровня
  HomeLoss→Break   = Серия домашних поражений достигла критического уровня
  AwayWin→Break    = Серия гостевых побед достигла критического уровня
  AwayLoss→Break   = Серия гостевых поражений достигла критического уровня
  H2H_Home→Break   = Серия побед в личных встречах (дома)
  H2H_Away→Break   = Серия поражений в личных встречах (в гостях)
  Overall→Break    = Общая серия побед команды
  OverallLoss→Break= Общая серия поражений команды
  HomeAlt→Win/Loss = Чередование домашних результатов
  AwayAlt→Win/Loss = Чередование гостевых результатов
    """)
    
    return {
        'ml_total': ml_total,
        'x12_total': x12_total,
        'ml_by_pattern': dict(ml_by_pattern),
        'x12_by_pattern': dict(x12_by_pattern),
        'pattern_stats': pattern_stats
    }


def run_backtest(min_synergy=2, stake=100):
    """
    Запустить бэктест CPP стратегии (совместимость с прошлым API)
    """
    return run_backtest_comparison(min_synergy=min_synergy, stake=stake)


if __name__ == '__main__':
    print("\n🎯 Тест: Минимальная синергия = 2")
    results = run_backtest_comparison(min_synergy=2)
