import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
from src.underdog_patterns import load_all_odds_data, add_underdog_info


def build_team_history(df):
    teams = set(df['home_team'].unique()) | set(df['away_team'].unique())
    
    team_states = {}
    for team in teams:
        team_states[team] = {
            'home_win_streak': 0,
            'home_loss_streak': 0,
            'away_win_streak': 0,
            'away_loss_streak': 0,
            'overall_win_streak': 0,
            'overall_loss_streak': 0,
            'underdog_win_streak': 0,
        }
    
    return team_states


def update_team_state(state, is_home, won, is_underdog, underdog_won):
    if is_home:
        if won:
            state['home_win_streak'] += 1
            state['home_loss_streak'] = 0
        else:
            state['home_loss_streak'] += 1
            state['home_win_streak'] = 0
    else:
        if won:
            state['away_win_streak'] += 1
            state['away_loss_streak'] = 0
        else:
            state['away_loss_streak'] += 1
            state['away_win_streak'] = 0
    
    if won:
        state['overall_win_streak'] += 1
        state['overall_loss_streak'] = 0
    else:
        state['overall_loss_streak'] += 1
        state['overall_win_streak'] = 0
    
    if is_underdog:
        if won:
            state['underdog_win_streak'] += 1
        else:
            state['underdog_win_streak'] = 0


def backtest_synergy(df, 
                     underdog_streak_min=3,
                     home_streak_min=4,
                     require_home_pattern=True,
                     require_underdog_pattern=True):
    
    print(f"\n{'='*70}")
    print(f"SYNERGY BACKTEST")
    print(f"  Underdog streak >= {underdog_streak_min}")
    print(f"  Home streak >= {home_streak_min}")
    print(f"  Require both: {require_home_pattern and require_underdog_pattern}")
    print(f"{'='*70}")
    
    df = add_underdog_info(df)
    df = df.sort_values('date').reset_index(drop=True)
    
    teams = set(df['home_team'].unique()) | set(df['away_team'].unique())
    team_states = {team: {
        'home_win_streak': 0,
        'home_loss_streak': 0,
        'away_win_streak': 0,
        'away_loss_streak': 0,
        'overall_win_streak': 0,
        'overall_loss_streak': 0,
        'underdog_win_streak': 0,
    } for team in teams}
    
    bets = []
    
    for idx, row in df.iterrows():
        home_team = row['home_team']
        away_team = row['away_team']
        home_won = row['home_win'] == 1
        
        home_state = team_states[home_team]
        away_state = team_states[away_team]
        
        home_is_underdog = row['underdog'] == 'home'
        away_is_underdog = row['underdog'] == 'away'
        
        home_patterns = []
        away_patterns = []
        
        if home_state['home_win_streak'] >= home_streak_min:
            home_patterns.append(f"HomeWin{home_state['home_win_streak']}")
        if home_state['underdog_win_streak'] >= underdog_streak_min and home_is_underdog:
            home_patterns.append(f"UnderdogWin{home_state['underdog_win_streak']}")
        
        if away_state['away_win_streak'] >= 3:
            away_patterns.append(f"AwayWin{away_state['away_win_streak']}")
        if away_state['underdog_win_streak'] >= underdog_streak_min and away_is_underdog:
            away_patterns.append(f"UnderdogWin{away_state['underdog_win_streak']}")
        
        has_home_pattern = len([p for p in home_patterns if 'HomeWin' in p]) > 0
        has_underdog_home = len([p for p in home_patterns if 'UnderdogWin' in p]) > 0
        
        has_away_pattern = len([p for p in away_patterns if 'AwayWin' in p]) > 0
        has_underdog_away = len([p for p in away_patterns if 'UnderdogWin' in p]) > 0
        
        if require_home_pattern and require_underdog_pattern:
            if has_home_pattern and has_underdog_home:
                fav_odds = row['away_odds']
                bets.append({
                    'date': row['date'],
                    'home': home_team,
                    'away': away_team,
                    'bet_on': away_team,
                    'bet_type': 'break_home_streak+underdog',
                    'patterns': home_patterns,
                    'won': not home_won,
                    'odds': fav_odds
                })
            
            if has_away_pattern and has_underdog_away:
                fav_odds = row['home_odds']
                bets.append({
                    'date': row['date'],
                    'home': home_team,
                    'away': away_team,
                    'bet_on': home_team,
                    'bet_type': 'break_away_streak+underdog',
                    'patterns': away_patterns,
                    'won': home_won,
                    'odds': fav_odds
                })
        
        update_team_state(home_state, is_home=True, won=home_won, 
                         is_underdog=home_is_underdog, 
                         underdog_won=home_is_underdog and home_won)
        update_team_state(away_state, is_home=False, won=not home_won,
                         is_underdog=away_is_underdog,
                         underdog_won=away_is_underdog and not home_won)
    
    if not bets:
        print("No bets found with these criteria")
        return None
    
    bets_df = pd.DataFrame(bets)
    total = len(bets_df)
    wins = bets_df['won'].sum()
    win_rate = wins / total * 100
    
    profit = sum(
        (bet['odds'] - 1) if bet['won'] else -1
        for _, bet in bets_df.iterrows()
    )
    roi = profit / total * 100
    
    print(f"\nResults:")
    print(f"  Total bets: {total}")
    print(f"  Wins: {wins} ({win_rate:.1f}%)")
    print(f"  Profit: {profit:.2f} units")
    print(f"  ROI: {roi:.1f}%")
    
    if total > 0:
        print(f"\nSample bets:")
        for _, bet in bets_df.head(5).iterrows():
            status = "WIN" if bet['won'] else "LOSS"
            print(f"  {bet['date'].strftime('%Y-%m-%d')}: {bet['bet_on']} @ {bet['odds']:.2f} - {status}")
            print(f"    Patterns: {bet['patterns']}")
    
    return {
        'total': total,
        'wins': wins,
        'win_rate': win_rate,
        'profit': profit,
        'roi': roi,
        'bets': bets_df
    }


def run_synergy_analysis():
    print("Loading odds data...")
    df = load_all_odds_data()
    
    if df.empty:
        return
    
    print("\n" + "="*70)
    print("SYNERGY ANALYSIS: HomeWinStreak + UnderdogWinStreak")
    print("="*70)
    
    results = {}
    for u_len in [2, 3, 4]:
        for h_len in [3, 4, 5]:
            key = f"U{u_len}_H{h_len}"
            result = backtest_synergy(df, 
                                      underdog_streak_min=u_len,
                                      home_streak_min=h_len)
            if result:
                results[key] = result
    
    print("\n" + "="*70)
    print("SUMMARY: All Combinations")
    print("="*70)
    print(f"{'Combo':<15} {'Bets':<10} {'Win%':<10} {'ROI':<10}")
    print("-"*45)
    for key, r in sorted(results.items(), key=lambda x: x[1]['roi'], reverse=True):
        print(f"{key:<15} {r['total']:<10} {r['win_rate']:.1f}%{'':<5} {r['roi']:.1f}%")
    
    return results


if __name__ == "__main__":
    run_synergy_analysis()
