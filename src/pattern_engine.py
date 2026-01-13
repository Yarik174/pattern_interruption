import pandas as pd
import numpy as np
from collections import defaultdict
from src.config import CRITICAL_THRESHOLDS

class PatternEngine:
    def __init__(self, critical_thresholds=None):
        self.thresholds = critical_thresholds or CRITICAL_THRESHOLDS
        self.patterns = defaultdict(list)
        
    def analyze_all_patterns(self, games_df):
        print("\n🔍 Анализ паттернов...")
        print("=" * 50)
        
        home_patterns = self._analyze_home_patterns(games_df)
        away_patterns = self._analyze_away_patterns(games_df)
        h2h_patterns = self._analyze_head_to_head_patterns(games_df)
        alternation_patterns = self._analyze_alternation_patterns(games_df)
        
        all_patterns = {
            'home': home_patterns,
            'away': away_patterns,
            'head_to_head': h2h_patterns,
            'alternation': alternation_patterns
        }
        
        self._print_pattern_stats(all_patterns)
        return all_patterns
    
    def _analyze_home_patterns(self, df):
        print("\n  📍 Анализ домашних паттернов...")
        patterns = []
        
        teams = df['home_team'].unique()
        
        for team in teams:
            home_games = df[df['home_team'] == team].sort_values('date')
            
            if len(home_games) < 3:
                continue
            
            results = home_games['home_win'].values
            result_str = ''.join(['W' if r == 1 else 'L' for r in results])
            
            streaks = self._find_streaks(result_str)
            alternations = self._find_alternations(result_str)
            
            for streak in streaks:
                patterns.append({
                    'team': team,
                    'type': 'home_streak',
                    'pattern': streak['pattern'],
                    'length': streak['length'],
                    'critical': streak['length'] >= self.thresholds['home_streak'],
                    'position': streak['position'],
                    'next_result': streak.get('next_result')
                })
            
            for alt in alternations:
                patterns.append({
                    'team': team,
                    'type': 'home_alternation',
                    'pattern': alt['pattern'],
                    'length': alt['length'],
                    'critical': alt['length'] >= self.thresholds['home_alternation'],
                    'position': alt['position'],
                    'next_result': alt.get('next_result')
                })
        
        return patterns
    
    def _analyze_away_patterns(self, df):
        print("  🚗 Анализ гостевых паттернов...")
        patterns = []
        
        teams = df['away_team'].unique()
        
        for team in teams:
            away_games = df[df['away_team'] == team].sort_values('date')
            
            if len(away_games) < 3:
                continue
            
            results = [1 if row['home_win'] == 0 else 0 for _, row in away_games.iterrows()]
            result_str = ''.join(['W' if r == 1 else 'L' for r in results])
            
            streaks = self._find_streaks(result_str)
            alternations = self._find_alternations(result_str)
            
            for streak in streaks:
                patterns.append({
                    'team': team,
                    'type': 'away_streak',
                    'pattern': streak['pattern'],
                    'length': streak['length'],
                    'critical': streak['length'] >= self.thresholds['away_streak'],
                    'position': streak['position'],
                    'next_result': streak.get('next_result')
                })
            
            for alt in alternations:
                patterns.append({
                    'team': team,
                    'type': 'away_alternation',
                    'pattern': alt['pattern'],
                    'length': alt['length'],
                    'critical': alt['length'] >= self.thresholds['away_alternation'],
                    'position': alt['position'],
                    'next_result': alt.get('next_result')
                })
        
        return patterns
    
    def _analyze_head_to_head_patterns(self, df):
        print("  🤝 Анализ личных встреч...")
        patterns = []
        
        matchups = df.groupby(['home_team', 'away_team']).size().reset_index()
        
        for _, row in matchups.iterrows():
            team1 = row['home_team']
            team2 = row['away_team']
            
            h2h_games = df[
                ((df['home_team'] == team1) & (df['away_team'] == team2)) |
                ((df['home_team'] == team2) & (df['away_team'] == team1))
            ].sort_values('date')
            
            if len(h2h_games) < 3:
                continue
            
            results = []
            for _, game in h2h_games.iterrows():
                if game['home_team'] == team1:
                    results.append('W' if game['home_win'] == 1 else 'L')
                else:
                    results.append('L' if game['home_win'] == 1 else 'W')
            
            result_str = ''.join(results)
            
            streaks = self._find_streaks(result_str)
            alternations = self._find_alternations(result_str)
            
            for streak in streaks:
                patterns.append({
                    'teams': (team1, team2),
                    'type': 'h2h_streak',
                    'pattern': streak['pattern'],
                    'length': streak['length'],
                    'critical': streak['length'] >= self.thresholds['h2h_streak'],
                    'position': streak['position'],
                    'next_result': streak.get('next_result')
                })
            
            for alt in alternations:
                patterns.append({
                    'teams': (team1, team2),
                    'type': 'h2h_alternation',
                    'pattern': alt['pattern'],
                    'length': alt['length'],
                    'critical': alt['length'] >= self.thresholds['h2h_alternation'],
                    'position': alt['position'],
                    'next_result': alt.get('next_result')
                })
        
        return patterns
    
    def _analyze_alternation_patterns(self, df):
        print("  🔄 Анализ чередований...")
        patterns = []
        
        teams = pd.concat([df['home_team'], df['away_team']]).unique()
        
        for team in teams:
            team_games = df[(df['home_team'] == team) | (df['away_team'] == team)].sort_values('date')
            
            if len(team_games) < 4:
                continue
            
            results = []
            for _, game in team_games.iterrows():
                if game['home_team'] == team:
                    results.append('W' if game['home_win'] == 1 else 'L')
                else:
                    results.append('L' if game['home_win'] == 1 else 'W')
            
            result_str = ''.join(results)
            
            complex_patterns = self._find_complex_patterns(result_str)
            
            for cp in complex_patterns:
                patterns.append({
                    'team': team,
                    'type': 'complex_alternation',
                    'pattern': cp['pattern'],
                    'length': cp['length'],
                    'critical': cp['length'] >= self.thresholds['alternation'],
                    'position': cp['position'],
                    'next_result': cp.get('next_result')
                })
        
        return patterns
    
    def _find_streaks(self, result_str):
        streaks = []
        i = 0
        
        while i < len(result_str):
            char = result_str[i]
            streak_len = 1
            
            while i + streak_len < len(result_str) and result_str[i + streak_len] == char:
                streak_len += 1
            
            if streak_len >= 3:
                next_result = None
                if i + streak_len < len(result_str):
                    next_result = result_str[i + streak_len]
                
                streaks.append({
                    'pattern': char * streak_len,
                    'length': streak_len,
                    'position': i,
                    'next_result': next_result
                })
            
            i += streak_len
        
        return streaks
    
    def _find_alternations(self, result_str):
        alternations = []
        
        for i in range(len(result_str) - 3):
            if result_str[i] != result_str[i + 1]:
                alt_len = 2
                is_alternating = True
                
                while i + alt_len < len(result_str) and is_alternating:
                    expected = result_str[i] if alt_len % 2 == 0 else result_str[i + 1]
                    if result_str[i + alt_len] == expected:
                        alt_len += 1
                    else:
                        is_alternating = False
                
                if alt_len >= 4:
                    next_result = None
                    if i + alt_len < len(result_str):
                        next_result = result_str[i + alt_len]
                    
                    alternations.append({
                        'pattern': result_str[i:i + alt_len],
                        'length': alt_len,
                        'position': i,
                        'next_result': next_result,
                        'broke': next_result is not None and next_result == result_str[i + alt_len - 1]
                    })
        
        return alternations
    
    def _find_complex_patterns(self, result_str):
        patterns = []
        
        for unit_len in [2, 3]:
            if len(result_str) < unit_len * 3:
                continue
            
            for start in range(len(result_str) - unit_len * 2):
                unit = result_str[start:start + unit_len]
                repetitions = 1
                pos = start + unit_len
                
                while pos + unit_len <= len(result_str) and result_str[pos:pos + unit_len] == unit:
                    repetitions += 1
                    pos += unit_len
                
                total_games = unit_len * repetitions
                if repetitions >= 3:
                    pattern_end = start + total_games
                    next_result = None
                    if pattern_end < len(result_str):
                        next_result = result_str[pattern_end]
                    
                    patterns.append({
                        'pattern': unit,
                        'length': total_games,
                        'repetitions': repetitions,
                        'position': start,
                        'next_result': next_result,
                        'unit': unit
                    })
        
        return patterns
    
    def _print_pattern_stats(self, all_patterns):
        print("\n📊 Статистика паттернов:")
        print("-" * 40)
        
        total = 0
        critical_total = 0
        
        for pattern_type, patterns in all_patterns.items():
            critical = sum(1 for p in patterns if p.get('critical', False))
            print(f"  {pattern_type}: {len(patterns)} (критических: {critical})")
            total += len(patterns)
            critical_total += critical
        
        print("-" * 40)
        print(f"  ВСЕГО: {total} паттернов")
        print(f"  Критических: {critical_total}")
    
    def get_pattern_features(self, team, opponent, games_df, game_date):
        features = {}
        
        home_games = games_df[
            (games_df['home_team'] == team) & 
            (games_df['date'] < game_date)
        ].sort_values('date').tail(15)
        
        if len(home_games) > 0:
            home_results = home_games['home_win'].values
            features['home_win_streak'] = self._current_streak(home_results)
            features['home_last_5_wins'] = sum(home_results[-5:]) if len(home_results) >= 5 else sum(home_results)
            home_str = ''.join(['W' if r == 1 else 'L' for r in home_results])
            features['home_alternation_len'] = self._get_alternation_length(home_str)
            features['home_last_result'] = int(home_results[-1])
            features['home_expected_alt'] = 1 - int(home_results[-1]) if features['home_alternation_len'] >= 4 else -1
        else:
            features['home_win_streak'] = 0
            features['home_last_5_wins'] = 0
            features['home_alternation_len'] = 0
            features['home_last_result'] = -1
            features['home_expected_alt'] = -1
        
        away_games = games_df[
            (games_df['away_team'] == team) &
            (games_df['date'] < game_date)
        ].sort_values('date').tail(15)
        
        if len(away_games) > 0:
            away_results = [1 if r == 0 else 0 for r in away_games['home_win'].values]
            features['away_win_streak'] = self._current_streak(away_results)
            features['away_last_5_wins'] = sum(away_results[-5:]) if len(away_results) >= 5 else sum(away_results)
            away_str = ''.join(['W' if r == 1 else 'L' for r in away_results])
            features['away_alternation_len'] = self._get_alternation_length(away_str)
            features['away_last_result'] = int(away_results[-1])
            features['away_expected_alt'] = 1 - int(away_results[-1]) if features['away_alternation_len'] >= 4 else -1
        else:
            features['away_win_streak'] = 0
            features['away_last_5_wins'] = 0
            features['away_alternation_len'] = 0
            features['away_last_result'] = -1
            features['away_expected_alt'] = -1
        
        h2h_games = games_df[
            (((games_df['home_team'] == team) & (games_df['away_team'] == opponent)) |
             ((games_df['home_team'] == opponent) & (games_df['away_team'] == team))) &
            (games_df['date'] < game_date)
        ].sort_values('date').tail(15)
        
        if len(h2h_games) > 0:
            h2h_results = []
            for _, game in h2h_games.iterrows():
                if game['home_team'] == team:
                    h2h_results.append(int(game['home_win']))
                else:
                    h2h_results.append(int(1 - game['home_win']))
            
            features['h2h_win_streak'] = self._current_streak(h2h_results)
            features['h2h_last_5_wins'] = sum(h2h_results[-5:]) if len(h2h_results) >= 5 else sum(h2h_results)
            features['h2h_games_count'] = len(h2h_results)
            h2h_str = ''.join(['W' if r == 1 else 'L' for r in h2h_results])
            features['h2h_alternation_len'] = self._get_alternation_length(h2h_str)
            features['h2h_last_result'] = int(h2h_results[-1])
            features['h2h_expected_alt'] = 1 - int(h2h_results[-1]) if features['h2h_alternation_len'] >= 4 else -1
        else:
            features['h2h_win_streak'] = 0
            features['h2h_last_5_wins'] = 0
            features['h2h_games_count'] = 0
            features['h2h_alternation_len'] = 0
            features['h2h_last_result'] = -1
            features['h2h_expected_alt'] = -1
        
        all_games = games_df[
            ((games_df['home_team'] == team) | (games_df['away_team'] == team)) &
            (games_df['date'] < game_date)
        ].sort_values('date').tail(20)
        
        if len(all_games) > 0:
            results = []
            for _, game in all_games.iterrows():
                if game['home_team'] == team:
                    results.append(int(game['home_win']))
                else:
                    results.append(int(1 - game['home_win']))
            
            features['overall_win_streak'] = self._current_streak(results)
            overall_str = ''.join(['W' if r == 1 else 'L' for r in results])
            features['overall_alternation_len'] = self._get_alternation_length(overall_str)
            features['overall_last_10_wins'] = sum(results[-10:]) if len(results) >= 10 else sum(results)
            features['overall_last_result'] = int(results[-1])
            features['overall_expected_alt'] = 1 - int(results[-1]) if features['overall_alternation_len'] >= 4 else -1
        else:
            features['overall_win_streak'] = 0
            features['overall_alternation_len'] = 0
            features['overall_last_10_wins'] = 0
            features['overall_last_result'] = -1
            features['overall_expected_alt'] = -1
        
        features['home_streak_critical'] = 1 if abs(features['home_win_streak']) >= self.thresholds['home_streak'] else 0
        features['away_streak_critical'] = 1 if abs(features['away_win_streak']) >= self.thresholds['away_streak'] else 0
        features['h2h_streak_critical'] = 1 if abs(features['h2h_win_streak']) >= self.thresholds['h2h'] else 0
        features['overall_streak_critical'] = 1 if abs(features['overall_win_streak']) >= self.thresholds['overall_streak'] else 0
        
        features['home_alt_critical'] = 1 if features['home_alternation_len'] >= self.thresholds['home_alternation'] else 0
        features['away_alt_critical'] = 1 if features['away_alternation_len'] >= self.thresholds['away_alternation'] else 0
        features['h2h_alt_critical'] = 1 if features['h2h_alternation_len'] >= self.thresholds['h2h_alternation'] else 0
        features['overall_alt_critical'] = 1 if features['overall_alternation_len'] >= self.thresholds['overall_alternation'] else 0
        
        features['total_critical_patterns'] = (
            features['home_streak_critical'] + features['away_streak_critical'] +
            features['h2h_streak_critical'] + features['overall_streak_critical'] +
            features['home_alt_critical'] + features['away_alt_critical'] +
            features['h2h_alt_critical'] + features['overall_alt_critical']
        )
        
        features['max_streak_len'] = max(
            abs(features['home_win_streak']),
            abs(features['away_win_streak']),
            abs(features['h2h_win_streak']),
            abs(features['overall_win_streak'])
        )
        
        features['max_alternation_len'] = max(
            features['home_alternation_len'],
            features['away_alternation_len'],
            features['h2h_alternation_len'],
            features['overall_alternation_len']
        )
        
        return features
    
    def _get_alternation_length(self, result_str):
        if len(result_str) < 4:
            return 0
        
        alt_len = 1
        for i in range(len(result_str) - 2, -1, -1):
            if result_str[i] != result_str[i + 1]:
                alt_len += 1
            else:
                break
        
        return alt_len if alt_len >= 4 else 0
    
    def _current_streak(self, results):
        if len(results) == 0:
            return 0
        
        last_result = results[-1]
        streak = 1
        
        for i in range(len(results) - 2, -1, -1):
            if results[i] == last_result:
                streak += 1
            else:
                break
        
        return streak if last_result == 1 else -streak
    
    def _check_alternation(self, results):
        if len(results) < 4:
            return 0
        
        alt_count = 0
        for i in range(1, len(results)):
            if results[i] != results[i - 1]:
                alt_count += 1
        
        alt_ratio = alt_count / (len(results) - 1)
        
        if alt_ratio >= 0.8:
            return len(results)
        return 0
