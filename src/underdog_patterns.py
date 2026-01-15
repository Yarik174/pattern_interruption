import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict


def load_all_odds_data():
    odds_dir = Path('data/odds')
    all_dfs = []
    
    for csv_file in sorted(odds_dir.glob('sbro-*.csv')):
        df = pd.read_csv(csv_file)
        all_dfs.append(df)
        print(f"  Loaded {csv_file.name}: {len(df)} matches")
    
    if not all_dfs:
        print("No odds files found!")
        return pd.DataFrame()
    
    combined = pd.concat(all_dfs, ignore_index=True)
    combined['date'] = pd.to_datetime(combined['date'])
    combined = combined.sort_values('date').reset_index(drop=True)
    
    print(f"\nTotal: {len(combined)} matches with odds")
    return combined


def determine_underdog(row):
    if row['home_odds'] > row['away_odds']:
        return 'home'
    elif row['away_odds'] > row['home_odds']:
        return 'away'
    else:
        return 'even'


def add_underdog_info(df):
    df = df.copy()
    df['underdog'] = df.apply(determine_underdog, axis=1)
    df['underdog_won'] = (
        ((df['underdog'] == 'home') & (df['home_win'] == 1)) |
        ((df['underdog'] == 'away') & (df['home_win'] == 0))
    ).astype(int)
    df['underdog_team'] = df.apply(
        lambda r: r['home_team'] if r['underdog'] == 'home' else (
            r['away_team'] if r['underdog'] == 'away' else None
        ), axis=1
    )
    df['favorite_team'] = df.apply(
        lambda r: r['away_team'] if r['underdog'] == 'home' else (
            r['home_team'] if r['underdog'] == 'away' else None
        ), axis=1
    )
    return df


def find_underdog_win_streaks(df, team):
    team_games = df[
        ((df['home_team'] == team) | (df['away_team'] == team))
    ].sort_values('date').copy()
    
    if len(team_games) < 3:
        return []
    
    streaks = []
    current_streak = 0
    streak_start_idx = None
    
    for idx, row in team_games.iterrows():
        is_home = row['home_team'] == team
        is_underdog = (is_home and row['underdog'] == 'home') or (not is_home and row['underdog'] == 'away')
        won = (is_home and row['home_win'] == 1) or (not is_home and row['home_win'] == 0)
        
        if is_underdog and won:
            if current_streak == 0:
                streak_start_idx = idx
            current_streak += 1
        else:
            if current_streak >= 2:
                streaks.append({
                    'team': team,
                    'length': current_streak,
                    'end_idx': idx,
                    'streak_broken': True,
                    'next_game_idx': idx,
                    'next_game_was_underdog': is_underdog,
                    'next_game_won': won
                })
            current_streak = 0
    
    if current_streak >= 2:
        streaks.append({
            'team': team,
            'length': current_streak,
            'end_idx': None,
            'streak_broken': False,
            'next_game_idx': None,
            'next_game_was_underdog': None,
            'next_game_won': None
        })
    
    return streaks


def backtest_underdog_pattern(df, critical_length=4):
    print(f"\n{'='*60}")
    print(f"BACKTEST: UnderdogWinStreak >= {critical_length}")
    print(f"{'='*60}")
    
    df = add_underdog_info(df)
    teams = set(df['home_team'].unique()) | set(df['away_team'].unique())
    
    all_bets = []
    
    for team in teams:
        team_games = df[
            ((df['home_team'] == team) | (df['away_team'] == team))
        ].sort_values('date').reset_index(drop=True)
        
        current_streak = 0
        
        for i, row in team_games.iterrows():
            is_home = row['home_team'] == team
            is_underdog = (is_home and row['underdog'] == 'home') or (not is_home and row['underdog'] == 'away')
            won = (is_home and row['home_win'] == 1) or (not is_home and row['home_win'] == 0)
            
            if current_streak >= critical_length and is_underdog:
                underdog_odds = row['home_odds'] if is_home else row['away_odds']
                all_bets.append({
                    'team': team,
                    'date': row['date'],
                    'streak_before': current_streak,
                    'bet_on': 'favorite',
                    'won_bet': not won,
                    'odds': 1 / underdog_odds + 1 if not won else underdog_odds,
                    'underdog_odds': underdog_odds
                })
            
            if is_underdog and won:
                current_streak += 1
            else:
                current_streak = 0
    
    if not all_bets:
        print(f"No bets found with critical length {critical_length}")
        return None
    
    bets_df = pd.DataFrame(all_bets)
    total_bets = len(bets_df)
    wins = bets_df['won_bet'].sum()
    win_rate = wins / total_bets * 100
    
    profit = 0
    for _, bet in bets_df.iterrows():
        if bet['won_bet']:
            fav_odds = 1 / (1 - 1/bet['underdog_odds']) if bet['underdog_odds'] > 1 else 1.5
            fav_odds = min(fav_odds, 3.0)
            profit += fav_odds - 1
        else:
            profit -= 1
    
    roi = profit / total_bets * 100
    
    print(f"\nResults:")
    print(f"  Total bets: {total_bets}")
    print(f"  Wins: {wins} ({win_rate:.1f}%)")
    print(f"  Profit: {profit:.2f} units")
    print(f"  ROI: {roi:.1f}%")
    
    by_streak = bets_df.groupby('streak_before').agg({
        'won_bet': ['count', 'sum', 'mean']
    }).round(3)
    print(f"\nBy streak length:")
    print(by_streak)
    
    return {
        'critical_length': critical_length,
        'total_bets': total_bets,
        'wins': wins,
        'win_rate': win_rate,
        'profit': profit,
        'roi': roi,
        'bets': bets_df
    }


def run_full_backtest():
    print("Loading odds data...")
    df = load_all_odds_data()
    
    if df.empty:
        return
    
    print(f"\nDate range: {df['date'].min()} to {df['date'].max()}")
    
    results = {}
    for crit_len in [3, 4, 5, 6]:
        result = backtest_underdog_pattern(df, critical_length=crit_len)
        if result:
            results[crit_len] = result
    
    print("\n" + "="*60)
    print("SUMMARY: Optimal Critical Length")
    print("="*60)
    print(f"{'Length':<10} {'Bets':<10} {'Win%':<10} {'ROI':<10}")
    print("-"*40)
    for length, r in results.items():
        print(f"{length:<10} {r['total_bets']:<10} {r['win_rate']:.1f}%{'':<5} {r['roi']:.1f}%")
    
    return results


if __name__ == "__main__":
    run_full_backtest()
