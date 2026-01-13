import pandas as pd
import numpy as np
from src.pattern_engine import PatternEngine
from src.config import CRITICAL_THRESHOLDS, PATTERN_BREAK_RATES, BASE_HOME_WIN_RATE

class FeatureBuilder:
    def __init__(self, critical_thresholds=None):
        self.pattern_engine = PatternEngine(critical_thresholds=critical_thresholds)
        self.feature_names = []
        
    def build_features(self, games_df):
        print("\n🔧 Формирование признаков для ML...")
        print("=" * 50)
        
        features_list = []
        targets = []
        game_info = []
        
        games_sorted = games_df.sort_values('date').reset_index(drop=True)
        
        min_history = 20
        
        total_games = len(games_sorted)
        processed = 0
        
        for idx in range(min_history, total_games):
            row = games_sorted.iloc[idx]
            history = games_sorted.iloc[:idx]
            
            home_team = row['home_team']
            away_team = row['away_team']
            game_date = row['date']
            
            home_features = self.pattern_engine.get_pattern_features(
                home_team, away_team, history, game_date
            )
            
            away_features = self.pattern_engine.get_pattern_features(
                away_team, home_team, history, game_date
            )
            
            combined_features = {}
            
            for key, value in home_features.items():
                combined_features[f'home_{key}'] = value
            
            for key, value in away_features.items():
                combined_features[f'away_{key}'] = value
            
            combined_features['streak_diff'] = home_features['overall_win_streak'] - away_features['overall_win_streak']
            combined_features['h2h_advantage'] = home_features['h2h_last_5_wins'] - away_features['h2h_last_5_wins']
            
            combined_features['home_any_critical'] = max(
                home_features['home_streak_critical'],
                home_features['h2h_streak_critical'],
                home_features['overall_streak_critical'],
                home_features.get('home_alt_critical', 0),
                home_features.get('h2h_alt_critical', 0),
                home_features.get('overall_alt_critical', 0)
            )
            combined_features['away_any_critical'] = max(
                away_features['away_streak_critical'],
                away_features['h2h_streak_critical'],
                away_features['overall_streak_critical'],
                away_features.get('away_alt_critical', 0),
                away_features.get('h2h_alt_critical', 0),
                away_features.get('overall_alt_critical', 0)
            )
            
            combined_features['home_total_critical'] = home_features.get('total_critical_patterns', 0)
            combined_features['away_total_critical'] = away_features.get('total_critical_patterns', 0)
            combined_features['max_streak_len'] = max(
                home_features.get('max_streak_len', 0),
                away_features.get('max_streak_len', 0)
            )
            combined_features['max_alternation_len'] = max(
                home_features.get('max_alternation_len', 0),
                away_features.get('max_alternation_len', 0)
            )
            
            combined_features['synergy_home'] = self._calculate_synergy(home_features, 'home')
            combined_features['synergy_away'] = self._calculate_synergy(away_features, 'away')
            
            home_crit_count, home_aligned = self._calculate_critical_synergy(home_features, 'home')
            away_crit_count, away_aligned = self._calculate_critical_synergy(away_features, 'away')
            combined_features['critical_synergy_home'] = home_crit_count
            combined_features['critical_synergy_away'] = away_crit_count
            combined_features['aligned_patterns_home'] = home_aligned
            combined_features['aligned_patterns_away'] = away_aligned
            combined_features['total_aligned'] = abs(home_aligned) + abs(away_aligned)
            
            home_expected = self._predict_from_pattern(home_features)
            away_expected = self._predict_from_pattern(away_features)
            combined_features['pattern_agreement'] = 1 if home_expected == (1 - away_expected) else 0
            combined_features['critical_pattern_exists'] = 1 if (
                home_features.get('total_critical_patterns', 0) > 0 or
                away_features.get('total_critical_patterns', 0) > 0
            ) else 0
            
            home_overgrowth = self._calculate_overgrowth(home_features)
            away_overgrowth = self._calculate_overgrowth(away_features)
            combined_features['home_streak_overgrowth'] = home_overgrowth
            combined_features['away_streak_overgrowth'] = away_overgrowth
            combined_features['max_overgrowth'] = max(home_overgrowth, away_overgrowth)
            
            home_alt_combo = self._calculate_alternation_combo(home_features)
            away_alt_combo = self._calculate_alternation_combo(away_features)
            combined_features['home_alternation_combo'] = home_alt_combo
            combined_features['away_alternation_combo'] = away_alt_combo
            combined_features['max_alternation_combo'] = max(home_alt_combo, away_alt_combo)
            
            combined_features['home_strong_signal'] = self._calculate_strong_signal(
                home_features, home_crit_count, home_alt_combo, home_overgrowth
            )
            combined_features['away_strong_signal'] = self._calculate_strong_signal(
                away_features, away_crit_count, away_alt_combo, away_overgrowth
            )
            combined_features['any_strong_signal'] = max(
                combined_features['home_strong_signal'],
                combined_features['away_strong_signal']
            )
            
            home_break_outcomes = self._calculate_predicted_break_outcome(home_features, 'home')
            away_break_outcomes = self._calculate_predicted_break_outcome(away_features, 'away')
            combined_features['home_predicted_break'] = len(home_break_outcomes)
            combined_features['away_predicted_break'] = len(away_break_outcomes)
            
            combined_features['home_independent_patterns'] = self._calculate_independent_patterns(home_features)
            combined_features['away_independent_patterns'] = self._calculate_independent_patterns(away_features)
            
            combined_features['home_weighted_break_prob'] = self._calculate_weighted_break_probability(home_features, 'home')
            combined_features['away_weighted_break_prob'] = self._calculate_weighted_break_probability(away_features, 'away')
            
            features_list.append(combined_features)
            
            target = int(row['home_win'])
            targets.append(target)
            
            game_info.append({
                'game_id': row['game_id'],
                'date': game_date,
                'home_team': home_team,
                'away_team': away_team,
                'home_win': row['home_win']
            })
            
            processed += 1
            if processed % 500 == 0:
                print(f"  Обработано {processed}/{total_games - min_history} матчей...")
        
        features_df = pd.DataFrame(features_list)
        targets = np.array(targets)
        
        self.feature_names = list(features_df.columns)
        
        print(f"\n✅ Сформировано {len(features_df)} образцов")
        print(f"   Количество признаков: {len(self.feature_names)}")
        print(f"   Распределение исходов:")
        print(f"     - Победа хозяев (1): {sum(targets)} ({100*sum(targets)/len(targets):.1f}%)")
        print(f"     - Победа гостей (0): {len(targets) - sum(targets)} ({100*(len(targets)-sum(targets))/len(targets):.1f}%)")
        
        return features_df, targets, pd.DataFrame(game_info)
    
    def _calculate_synergy(self, features, context):
        synergy = 0
        
        if context == 'home':
            streak = features['home_win_streak']
        else:
            streak = features['away_win_streak']
        
        h2h_streak = features['h2h_win_streak']
        overall_streak = features['overall_win_streak']
        
        if streak > 0 and h2h_streak > 0 and overall_streak > 0:
            synergy = 3
        elif (streak > 0 and h2h_streak > 0) or (streak > 0 and overall_streak > 0) or (h2h_streak > 0 and overall_streak > 0):
            synergy = 2
        elif streak > 0 or h2h_streak > 0 or overall_streak > 0:
            synergy = 1
        
        if streak < 0 and h2h_streak < 0 and overall_streak < 0:
            synergy = -3
        elif (streak < 0 and h2h_streak < 0) or (streak < 0 and overall_streak < 0) or (h2h_streak < 0 and overall_streak < 0):
            synergy = -2
        
        return synergy
    
    def _calculate_critical_synergy(self, features, context):
        if context == 'home':
            streak_crit = features.get('home_streak_critical', 0)
        else:
            streak_crit = features.get('away_streak_critical', 0)
        
        h2h_crit = features.get('h2h_streak_critical', 0)
        overall_crit = features.get('overall_streak_critical', 0)
        alt_crit = features.get('home_alt_critical', 0) if context == 'home' else features.get('away_alt_critical', 0)
        
        critical_count = streak_crit + h2h_crit + overall_crit + alt_crit
        
        if context == 'home':
            streak = features['home_win_streak']
        else:
            streak = features['away_win_streak']
        h2h = features['h2h_win_streak']
        overall = features['overall_win_streak']
        
        directions = []
        if streak_crit and streak != 0:
            directions.append(1 if streak > 0 else -1)
        if h2h_crit and h2h != 0:
            directions.append(1 if h2h > 0 else -1)
        if overall_crit and overall != 0:
            directions.append(1 if overall > 0 else -1)
        
        aligned = 0
        if len(directions) >= 2:
            if all(d == 1 for d in directions):
                aligned = len(directions)
            elif all(d == -1 for d in directions):
                aligned = -len(directions)
        
        return critical_count, aligned
    
    def _predict_from_pattern(self, features):
        critical_count = (
            features['home_streak_critical'] +
            features['away_streak_critical'] +
            features['h2h_streak_critical'] +
            features['overall_streak_critical']
        )
        
        if critical_count >= 2:
            if features['overall_win_streak'] > 0:
                return 0
            else:
                return 1
        
        if features['overall_win_streak'] > 0:
            return 1
        elif features['overall_win_streak'] < 0:
            return 0
        
        return 0.5
    
    def _calculate_target_combined(self, home_features, away_features, actual_result):
        """
        Рассчитывает target с учётом паттернов ОБЕИХ команд.
        actual_result: 1 = домашняя победа, 0 = гостевая победа
        
        Прерывание = 1 если любой критический паттерн прервался:
        - Домашняя команда: серия побед прервалась (actual=0) или серия поражений прервалась (actual=1)
        - Гостевая команда: серия побед прервалась (actual=1) или серия поражений прервалась (actual=0)
        """
        pattern_broken = 0
        
        home_critical = home_features.get('total_critical_patterns', 0)
        away_critical = away_features.get('total_critical_patterns', 0)
        
        if home_critical == 0 and away_critical == 0:
            home_streak = home_features['overall_win_streak']
            away_streak = away_features['overall_win_streak']
            
            if home_streak >= 3 and actual_result == 0:
                pattern_broken = 1
            elif home_streak <= -3 and actual_result == 1:
                pattern_broken = 1
            elif away_streak >= 3 and actual_result == 1:
                pattern_broken = 1
            elif away_streak <= -3 and actual_result == 0:
                pattern_broken = 1
            
            return pattern_broken
        
        if home_features.get('home_streak_critical', 0) == 1:
            streak = home_features['home_win_streak']
            if streak > 0 and actual_result == 0:
                pattern_broken = 1
            elif streak < 0 and actual_result == 1:
                pattern_broken = 1
        
        if home_features.get('overall_streak_critical', 0) == 1:
            streak = home_features['overall_win_streak']
            if streak > 0 and actual_result == 0:
                pattern_broken = 1
            elif streak < 0 and actual_result == 1:
                pattern_broken = 1
        
        if home_features.get('h2h_streak_critical', 0) == 1:
            streak = home_features['h2h_win_streak']
            if streak > 0 and actual_result == 0:
                pattern_broken = 1
            elif streak < 0 and actual_result == 1:
                pattern_broken = 1
        
        if home_features.get('home_alt_critical', 0) == 1:
            expected = home_features.get('home_expected_alt', -1)
            if expected != -1 and actual_result != expected:
                pattern_broken = 1
        
        if home_features.get('h2h_alt_critical', 0) == 1:
            expected = home_features.get('h2h_expected_alt', -1)
            if expected != -1 and actual_result != expected:
                pattern_broken = 1
        
        if home_features.get('overall_alt_critical', 0) == 1:
            expected = home_features.get('overall_expected_alt', -1)
            if expected != -1 and actual_result != expected:
                pattern_broken = 1
        
        if away_features.get('away_streak_critical', 0) == 1:
            streak = away_features['away_win_streak']
            if streak > 0 and actual_result == 1:
                pattern_broken = 1
            elif streak < 0 and actual_result == 0:
                pattern_broken = 1
        
        if away_features.get('overall_streak_critical', 0) == 1:
            streak = away_features['overall_win_streak']
            if streak > 0 and actual_result == 1:
                pattern_broken = 1
            elif streak < 0 and actual_result == 0:
                pattern_broken = 1
        
        if away_features.get('h2h_streak_critical', 0) == 1:
            streak = away_features['h2h_win_streak']
            if streak > 0 and actual_result == 1:
                pattern_broken = 1
            elif streak < 0 and actual_result == 0:
                pattern_broken = 1
        
        if away_features.get('away_alt_critical', 0) == 1:
            expected = away_features.get('away_expected_alt', -1)
            if expected != -1:
                away_expected_result = 1 - expected
                if actual_result != away_expected_result:
                    pattern_broken = 1
        
        if away_features.get('h2h_alt_critical', 0) == 1:
            expected = away_features.get('h2h_expected_alt', -1)
            if expected != -1:
                away_expected_result = 1 - expected
                if actual_result != away_expected_result:
                    pattern_broken = 1
        
        if away_features.get('overall_alt_critical', 0) == 1:
            expected = away_features.get('overall_expected_alt', -1)
            if expected != -1:
                away_expected_result = 1 - expected
                if actual_result != away_expected_result:
                    pattern_broken = 1
        
        return pattern_broken
    
    def _calculate_target(self, features, actual_result):
        """Legacy method for backwards compatibility"""
        return self._calculate_target_combined(features, {}, actual_result)
    
    def _calculate_overgrowth(self, features):
        critical_len = 5
        max_streak = max(
            abs(features.get('home_win_streak', 0)),
            abs(features.get('away_win_streak', 0)),
            abs(features.get('h2h_win_streak', 0)),
            abs(features.get('overall_win_streak', 0))
        )
        max_alt = max(
            features.get('home_alternation_len', 0),
            features.get('away_alternation_len', 0),
            features.get('h2h_alternation_len', 0),
            features.get('overall_alternation_len', 0)
        )
        max_pattern = max(max_streak, max_alt)
        overgrowth = max(0, max_pattern - critical_len)
        return min(overgrowth, 5)
    
    def _calculate_alternation_combo(self, features):
        combo = 0
        if features.get('home_alt_critical', 0) == 1:
            combo += 1
        if features.get('away_alt_critical', 0) == 1:
            combo += 1
        if features.get('h2h_alt_critical', 0) == 1:
            combo += 1
        if features.get('overall_alt_critical', 0) == 1:
            combo += 1
        return combo
    
    def _calculate_strong_signal(self, features, critical_count, alt_combo, overgrowth):
        score = 0
        if critical_count >= 2:
            score += 1
        if alt_combo >= 1:
            score += 1
        if overgrowth >= 1:
            score += 1
        if overgrowth >= 2:
            score += 1
        if critical_count >= 3:
            score += 1
        if alt_combo >= 2:
            score += 1
        return score
    
    def _calculate_predicted_break_outcome(self, features, team_context):
        predictions = {}
        
        if team_context == 'home':
            streak_key = 'home_win_streak'
            streak_crit_key = 'home_streak_critical'
            alt_crit_key = 'home_alt_critical'
            last_result_key = 'home_last_result'
        else:
            streak_key = 'away_win_streak'
            streak_crit_key = 'away_streak_critical'
            alt_crit_key = 'away_alt_critical'
            last_result_key = 'away_last_result'
        
        if features.get(streak_crit_key, 0) == 1:
            streak = features.get(streak_key, 0)
            if streak > 0:
                predictions['streak'] = 0
            elif streak < 0:
                predictions['streak'] = 1
        
        if features.get('overall_streak_critical', 0) == 1:
            overall_streak = features.get('overall_win_streak', 0)
            if overall_streak > 0:
                predictions['overall_streak'] = 0
            elif overall_streak < 0:
                predictions['overall_streak'] = 1
        
        if features.get('h2h_streak_critical', 0) == 1:
            h2h_streak = features.get('h2h_win_streak', 0)
            if h2h_streak > 0:
                predictions['h2h_streak'] = 0
            elif h2h_streak < 0:
                predictions['h2h_streak'] = 1
        
        if features.get(alt_crit_key, 0) == 1:
            last_result = features.get(last_result_key, -1)
            if last_result != -1:
                predictions['alternation'] = last_result
        
        if features.get('overall_alt_critical', 0) == 1:
            last_result = features.get('overall_last_result', -1)
            if last_result != -1:
                predictions['overall_alternation'] = last_result
        
        if features.get('h2h_alt_critical', 0) == 1:
            last_result = features.get('h2h_last_result', -1)
            if last_result != -1:
                predictions['h2h_alternation'] = last_result
        
        return predictions
    
    def _calculate_independent_patterns(self, features):
        independent_count = 0
        
        home_streak_crit = features.get('home_streak_critical', 0)
        away_streak_crit = features.get('away_streak_critical', 0)
        overall_streak_crit = features.get('overall_streak_critical', 0)
        h2h_streak_crit = features.get('h2h_streak_critical', 0)
        
        home_alt_crit = features.get('home_alt_critical', 0)
        away_alt_crit = features.get('away_alt_critical', 0)
        overall_alt_crit = features.get('overall_alt_critical', 0)
        h2h_alt_crit = features.get('h2h_alt_critical', 0)
        
        context_streak = home_streak_crit or away_streak_crit
        if context_streak and overall_streak_crit:
            independent_count += 1
        elif context_streak or overall_streak_crit:
            independent_count += 1
        
        if h2h_streak_crit:
            independent_count += 1
        
        context_alt = home_alt_crit or away_alt_crit
        if context_alt and overall_alt_crit:
            independent_count += 1
        elif context_alt or overall_alt_crit:
            independent_count += 1
        
        if h2h_alt_crit:
            independent_count += 1
        
        return independent_count
    
    def _calculate_opponent_strength(self, team, history):
        if len(history) == 0:
            return 0.5
        
        team_games = history[(history['home_team'] == team) | (history['away_team'] == team)]
        
        if len(team_games) == 0:
            return 0.5
        
        opponents = []
        for _, game in team_games.iterrows():
            if game['home_team'] == team:
                opponents.append(game['away_team'])
            else:
                opponents.append(game['home_team'])
        
        opponent_win_rates = []
        for opp in set(opponents):
            opp_games = history[(history['home_team'] == opp) | (history['away_team'] == opp)]
            if len(opp_games) < 5:
                continue
            
            opp_wins = 0
            for _, game in opp_games.iterrows():
                if game['home_team'] == opp and game['home_win'] == 1:
                    opp_wins += 1
                elif game['away_team'] == opp and game['home_win'] == 0:
                    opp_wins += 1
            
            opp_win_rate = opp_wins / len(opp_games)
            opponent_win_rates.append(opp_win_rate)
        
        if len(opponent_win_rates) == 0:
            return 0.5
        
        return sum(opponent_win_rates) / len(opponent_win_rates)
    
    def _calculate_weighted_break_probability(self, features, team_context):
        break_probs = []
        weights = []
        
        if team_context == 'home':
            streak_crit_key = 'home_streak_critical'
            alt_crit_key = 'home_alt_critical'
            streak_rate_key = 'home_streak'
            alt_rate_key = 'home_alternation'
        else:
            streak_crit_key = 'away_streak_critical'
            alt_crit_key = 'away_alt_critical'
            streak_rate_key = 'away_streak'
            alt_rate_key = 'away_alternation'
        
        if features.get(streak_crit_key, 0) == 1:
            rate = PATTERN_BREAK_RATES.get(streak_rate_key, 0.5)
            break_probs.append(rate)
            weights.append(1.0)
        
        if features.get('overall_streak_critical', 0) == 1:
            rate = PATTERN_BREAK_RATES.get('overall_streak', 0.5)
            break_probs.append(rate)
            weights.append(1.2)
        
        if features.get('h2h_streak_critical', 0) == 1:
            rate = PATTERN_BREAK_RATES.get('h2h_streak', 0.5)
            break_probs.append(rate)
            weights.append(1.0)
        
        if features.get(alt_crit_key, 0) == 1:
            rate = PATTERN_BREAK_RATES.get(alt_rate_key, 0.5)
            break_probs.append(rate)
            weights.append(1.0)
        
        if features.get('overall_alt_critical', 0) == 1:
            rate = PATTERN_BREAK_RATES.get('overall_alternation', 0.5)
            break_probs.append(rate)
            weights.append(1.2)
        
        if features.get('h2h_alt_critical', 0) == 1:
            rate = PATTERN_BREAK_RATES.get('h2h_alternation', 0.5)
            break_probs.append(rate)
            weights.append(1.0)
        
        if len(break_probs) == 0:
            return 0.0
        
        weighted_sum = sum(p * w for p, w in zip(break_probs, weights))
        total_weight = sum(weights)
        
        return weighted_sum / total_weight
    
    def get_feature_importance_names(self):
        return self.feature_names
