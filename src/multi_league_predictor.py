"""
Multi-League Pattern Predictor
Анализ паттернов и прогнозирование для нескольких хоккейных лиг
"""

import pandas as pd
from datetime import datetime
from collections import defaultdict
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.multi_league_loader import MultiLeagueLoader, LEAGUES
from src.config import PATTERN_BREAK_RATES, BASE_HOME_WIN_RATE, CRITICAL_THRESHOLDS


class MultiLeaguePatternEngine:
    """Анализ паттернов для нескольких лиг"""
    
    def __init__(self, critical_length=5):
        self.critical_length = critical_length
        self.loader = MultiLeagueLoader()
        self.league_data = {}
        self.team_patterns = {}
        
    def load_leagues(self, league_names, n_seasons=5):
        """Загрузить данные лиг и сразу проанализировать паттерны"""
        print("\n📥 Загрузка данных лиг...")
        self.league_data = self.loader.load_multiple_leagues(league_names, n_seasons)
        
        for league, games in self.league_data.items():
            if games:
                df = pd.DataFrame(games)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                self.league_data[league] = df.to_dict('records')
        
        for league in league_names:
            if league in self.league_data and self.league_data[league]:
                self.analyze_team_patterns(league)
                print(f"✅ {league}: паттерны проанализированы ({len(self.team_patterns.get(league, {}))} команд)")
        
        return self.league_data
    
    def analyze_team_patterns(self, league_name):
        """Анализировать паттерны команд в лиге"""
        if league_name not in self.league_data:
            return {}
        
        games = self.league_data[league_name]
        if not games:
            return {}
        
        team_history = defaultdict(list)
        home_history = defaultdict(list)
        away_history = defaultdict(list)
        h2h_history = defaultdict(list)
        
        for game in games:
            home = game['home_team']
            away = game['away_team']
            home_win = game['home_win']
            
            team_history[home].append(('W' if home_win else 'L', game['date']))
            team_history[away].append(('L' if home_win else 'W', game['date']))
            
            home_history[home].append('W' if home_win else 'L')
            away_history[away].append('W' if not home_win else 'L')
            
            h2h_key = tuple(sorted([home, away]))
            h2h_history[h2h_key].append((home, home_win))
        
        patterns = {}
        
        for team, results in team_history.items():
            results_only = [r[0] for r in results]
            
            overall_streak = self._calc_streak(results_only)
            home_streak = self._calc_streak(home_history.get(team, []))
            away_streak = self._calc_streak(away_history.get(team, []))
            
            overall_alt = self._check_alternation(results_only)
            home_alt = self._check_alternation(home_history.get(team, []))
            
            patterns[team] = {
                'overall_streak': overall_streak,
                'home_streak': home_streak,
                'away_streak': away_streak,
                'overall_alt': overall_alt,
                'home_alt': home_alt,
                'games_played': len(results),
                'overall_critical': abs(overall_streak) >= self.critical_length,
                'home_critical': abs(home_streak) >= self.critical_length,
                'away_critical': abs(away_streak) >= self.critical_length,
                'alt_critical': overall_alt >= self.critical_length,
            }
        
        self.team_patterns[league_name] = patterns
        return patterns
    
    def _calc_streak(self, results):
        """Вычислить текущую серию"""
        if not results:
            return 0
        
        streak = 0
        last = results[-1]
        
        for r in reversed(results):
            if r == last:
                streak += 1
            else:
                break
        
        return streak if last == 'W' else -streak
    
    def _check_alternation(self, results):
        """Проверить чередование (WLWLWL)"""
        if len(results) < 4:
            return 0
        
        alt_count = 0
        for i in range(len(results) - 1, 0, -1):
            if results[i] != results[i-1]:
                alt_count += 1
            else:
                break
        
        return alt_count
    
    def calc_strong_signal(self, team_pattern):
        """Вычислить силу сигнала прерывания"""
        score = 0
        
        if team_pattern.get('overall_critical'):
            score += 1
        if team_pattern.get('home_critical'):
            score += 1
        if team_pattern.get('away_critical'):
            score += 1
        if team_pattern.get('alt_critical'):
            score += 1
        
        synergy = sum([
            team_pattern.get('overall_critical', False),
            team_pattern.get('home_critical', False),
            team_pattern.get('away_critical', False)
        ])
        if synergy >= 2:
            score += 1
        
        streak = abs(team_pattern.get('overall_streak', 0))
        if streak >= 8:
            score += 2
        elif streak >= 6:
            score += 1
        
        return score
    
    def get_cpp_prediction(self, home_pattern, away_pattern):
        """
        Анализ CPP (Critical Pattern Prediction) для матча.
        
        CPP логика:
        - Серия (streak): критическая длина → прерывание → ПРОТИВОПОЛОЖНЫЙ результат
          - Серия побед → прерывание → поражение
          - Серия поражений → прерывание → победа
        - Чередование (alt): критическая длина → прерывание → ПОВТОРЕНИЕ последнего
          - Последний W → прерывание → снова W
          - Последний L → прерывание → снова L
        
        Returns:
            dict: {team: 'home'/'away'/None, synergy: int, patterns: list}
        """
        home_predictions = []
        away_predictions = []
        
        overall_streak = home_pattern.get('overall_streak', 0)
        if home_pattern.get('overall_critical'):
            if overall_streak > 0:
                away_predictions.append({
                    'type': 'overall_streak',
                    'length': abs(overall_streak),
                    'value': overall_streak,
                    'reason': f'Прерывание серии побед хозяев ({overall_streak})'
                })
            elif overall_streak < 0:
                home_predictions.append({
                    'type': 'overall_streak',
                    'length': abs(overall_streak),
                    'value': overall_streak,
                    'reason': f'Прерывание серии поражений хозяев ({overall_streak})'
                })
        
        home_streak = home_pattern.get('home_streak', 0)
        if home_pattern.get('home_critical'):
            if home_streak > 0:
                away_predictions.append({
                    'type': 'home_streak',
                    'length': abs(home_streak),
                    'value': home_streak,
                    'reason': f'Прерывание домашней серии побед ({home_streak})'
                })
            elif home_streak < 0:
                home_predictions.append({
                    'type': 'home_streak',
                    'length': abs(home_streak),
                    'value': home_streak,
                    'reason': f'Прерывание домашней серии поражений ({home_streak})'
                })
        
        if home_pattern.get('alt_critical'):
            last_result = 'W' if overall_streak > 0 else 'L'
            alt_len = home_pattern.get('overall_alt', 0)
            if last_result == 'W':
                home_predictions.append({
                    'type': 'overall_alternation',
                    'length': alt_len,
                    'value': alt_len,
                    'reason': f'Прерывание чередования хозяев (последний W, повтор)'
                })
            else:
                away_predictions.append({
                    'type': 'overall_alternation',
                    'length': alt_len,
                    'value': alt_len,
                    'reason': f'Прерывание чередования хозяев (последний L, повтор)'
                })
        
        away_overall_streak = away_pattern.get('overall_streak', 0)
        if away_pattern.get('overall_critical'):
            if away_overall_streak > 0:
                home_predictions.append({
                    'type': 'overall_streak',
                    'length': abs(away_overall_streak),
                    'value': away_overall_streak,
                    'reason': f'Прерывание серии побед гостей ({away_overall_streak})'
                })
            elif away_overall_streak < 0:
                away_predictions.append({
                    'type': 'overall_streak',
                    'length': abs(away_overall_streak),
                    'value': away_overall_streak,
                    'reason': f'Прерывание серии поражений гостей ({away_overall_streak})'
                })
        
        away_away_streak = away_pattern.get('away_streak', 0)
        if away_pattern.get('away_critical'):
            if away_away_streak > 0:
                home_predictions.append({
                    'type': 'away_streak',
                    'length': abs(away_away_streak),
                    'value': away_away_streak,
                    'reason': f'Прерывание гостевой серии побед ({away_away_streak})'
                })
            elif away_away_streak < 0:
                away_predictions.append({
                    'type': 'away_streak',
                    'length': abs(away_away_streak),
                    'value': away_away_streak,
                    'reason': f'Прерывание гостевой серии поражений ({away_away_streak})'
                })
        
        if away_pattern.get('alt_critical'):
            last_result = 'W' if away_overall_streak > 0 else 'L'
            alt_len = away_pattern.get('overall_alt', 0)
            if last_result == 'W':
                away_predictions.append({
                    'type': 'away_alternation',
                    'length': alt_len,
                    'value': alt_len,
                    'reason': f'Прерывание чередования гостей (последний W, повтор)'
                })
            else:
                home_predictions.append({
                    'type': 'away_alternation',
                    'length': alt_len,
                    'value': alt_len,
                    'reason': f'Прерывание чередования гостей (последний L, повтор)'
                })
        
        home_synergy = len(home_predictions)
        away_synergy = len(away_predictions)
        
        if home_synergy > away_synergy:
            predicted_team = 'home'
            synergy = home_synergy
            patterns = home_predictions
        elif away_synergy > home_synergy:
            predicted_team = 'away'
            synergy = away_synergy
            patterns = away_predictions
        elif home_synergy > 0:
            predicted_team = 'home' if home_synergy >= away_synergy else 'away'
            synergy = max(home_synergy, away_synergy)
            patterns = home_predictions if home_synergy >= away_synergy else away_predictions
        else:
            predicted_team = None
            synergy = 0
            patterns = []
        
        return {
            'team': predicted_team,
            'synergy': synergy,
            'patterns': patterns,
            'home_synergy': home_synergy,
            'away_synergy': away_synergy,
            'home_patterns': home_predictions,
            'away_patterns': away_predictions
        }
    
    def get_synergy_details(self, home_pattern, away_pattern):
        """
        Получить детали синергии паттернов для обеих команд.
        
        Returns:
            dict: {
                active_patterns: list,
                home_synergy: int,
                away_synergy: int,
                bet_recommendation: 'home'/'away'/None
            }
        """
        cpp = self.get_cpp_prediction(home_pattern, away_pattern)
        
        active_patterns = []
        
        for p in cpp['home_patterns']:
            active_patterns.append({
                'pattern': p['type'],
                'value': p['value'],
                'direction': 'home',
                'reason': p['reason']
            })
        
        for p in cpp['away_patterns']:
            active_patterns.append({
                'pattern': p['type'],
                'value': p['value'],
                'direction': 'away',
                'reason': p['reason']
            })
        
        bet_recommendation = None
        if cpp['synergy'] >= 2:
            bet_recommendation = cpp['team']
        
        return {
            'active_patterns': active_patterns,
            'home_synergy': cpp['home_synergy'],
            'away_synergy': cpp['away_synergy'],
            'bet_recommendation': bet_recommendation,
            'total_critical': len(active_patterns)
        }
    
    def analyze_match(self, league_name, home_team, away_team):
        """Анализ конкретного матча"""
        if league_name not in self.team_patterns:
            self.analyze_team_patterns(league_name)
        
        patterns = self.team_patterns.get(league_name, {})
        home_pattern = patterns.get(home_team, {})
        away_pattern = patterns.get(away_team, {})
        
        home_score = self.calc_strong_signal(home_pattern)
        away_score = self.calc_strong_signal(away_pattern)
        
        cpp_prediction = self.get_cpp_prediction(home_pattern, away_pattern)
        synergy_details = self.get_synergy_details(home_pattern, away_pattern)
        
        return {
            'league': league_name,
            'home_team': home_team,
            'away_team': away_team,
            'home_pattern': home_pattern,
            'away_pattern': away_pattern,
            'home_score': home_score,
            'away_score': away_score,
            'max_score': max(home_score, away_score),
            'recommendation': self._get_recommendation(home_pattern, away_pattern, home_score, away_score),
            'cpp_prediction': {
                'team': cpp_prediction['team'],
                'synergy': cpp_prediction['synergy'],
                'patterns': cpp_prediction['patterns'],
                'home_synergy': cpp_prediction['home_synergy'],
                'away_synergy': cpp_prediction['away_synergy']
            },
            'bet_recommendation': synergy_details['bet_recommendation']
        }
    
    def _get_recommendation(self, home_pattern, away_pattern, home_score, away_score):
        """Получить рекомендацию по ставке"""
        if home_score >= 4 or away_score >= 4:
            if home_score >= away_score:
                streak = home_pattern.get('overall_streak', 0)
                if streak > 0:
                    return f"Ставка на гостей (прерывание серии побед хозяев)"
                elif streak < 0:
                    return f"Ставка на хозяев (прерывание серии поражений)"
            else:
                streak = away_pattern.get('overall_streak', 0)
                if streak > 0:
                    return f"Ставка на хозяев (прерывание серии побед гостей)"
                elif streak < 0:
                    return f"Ставка на гостей (прерывание серии поражений)"
        
        if home_score >= 3 or away_score >= 3:
            return "Сигнал средний - возможно прерывание"
        
        return "Нет сильного сигнала"
    
    def get_all_upcoming_with_analysis(self, league_names=None, include_odds=True):
        """Получить все предстоящие матчи с анализом"""
        if league_names is None:
            league_names = list(LEAGUES.keys())
        
        for league in league_names:
            if league not in self.team_patterns:
                self.analyze_team_patterns(league)
        
        upcoming = self.loader.get_all_upcoming(league_names)
        
        all_odds = {}
        if include_odds:
            all_odds = self.loader.fetch_all_odds(league_names)
        
        analyzed = []
        for game in upcoming:
            league = game['league']
            analysis = self.analyze_match(league, game['home_team'], game['away_team'])
            analysis.update({
                'date': game.get('date'),
                'time': game.get('time'),
                'game_id': game.get('id')
            })
            
            if league in all_odds:
                odds_data = self._match_odds(game, all_odds[league])
                analysis['odds'] = odds_data
                
                if odds_data and analysis['max_score'] >= 3:
                    if league == 'NHL':
                        ev = self._calc_ev(analysis, odds_data)
                        analysis['ev'] = ev
                    else:
                        analysis['ev'] = {
                            'bet_on': None,
                            'available': False,
                            'note': 'EV недоступен для этой лиги (нет калиброванной модели)'
                        }
            
            analyzed.append(analysis)
        
        analyzed.sort(key=lambda x: x['max_score'], reverse=True)
        return analyzed
    
    def _match_odds(self, game, league_odds):
        """Найти коэффициенты для матча"""
        home = game['home_team']
        away = game['away_team']
        
        for key, odds in league_odds.items():
            odds_home = odds.get('home_team', '').lower()
            odds_away = odds.get('away_team', '').lower()
            
            if (home.lower() in odds_home or odds_home in home.lower() or
                away.lower() in odds_away or odds_away in away.lower()):
                return odds
            
            home_parts = home.lower().split()
            away_parts = away.lower().split()
            
            for part in home_parts:
                if len(part) > 3 and part in odds_home:
                    for apart in away_parts:
                        if len(apart) > 3 and apart in odds_away:
                            return odds
        
        return None
    
    def _calc_ev(self, analysis, odds_data):
        """Рассчитать Expected Value на основе CPP prediction
        
        Логика:
        1. Используем CPP prediction для определения направления ставки
        2. Требуем синергию >= 2 для рекомендации
        3. Рассчитываем EV по вероятности и коэффициенту
        """
        cpp_prediction = analysis.get('cpp_prediction', {})
        league = analysis.get('league', 'NHL')
        
        ev_result = {
            'bet_on': None,
            'odds': 0,
            'probability': 0,
            'ev': 0,
            'ev_percent': 0,
            'synergy': 0,
            'patterns': [],
            'calibrated': league == 'NHL',
            'note': 'Требуется синергия >= 2 паттернов'
        }
        
        synergy = cpp_prediction.get('synergy', 0)
        bet_team = cpp_prediction.get('team')
        patterns = cpp_prediction.get('patterns', [])
        
        if synergy < 2 or bet_team is None:
            ev_result['note'] = f'Синергия {synergy} < 2, рекомендация отсутствует'
            return ev_result
        
        if bet_team == 'home':
            odds = odds_data.get('home_odds', 0)
        else:
            odds = odds_data.get('away_odds', 0)
        
        if odds <= 0:
            ev_result['note'] = 'Коэффициенты недоступны'
            return ev_result
        
        probability = self._estimate_cpp_probability(patterns, synergy)
        
        ev = (probability * (odds - 1)) - (1 - probability)
        ev_percent = ev * 100
        
        ev_result = {
            'bet_on': bet_team,
            'odds': odds,
            'probability': round(probability * 100, 1),
            'ev': round(ev, 4),
            'ev_percent': round(ev_percent, 1),
            'synergy': synergy,
            'patterns': [p['reason'] for p in patterns],
            'calibrated': league == 'NHL',
            'note': f'Синергия {synergy} паттернов → {bet_team}'
        }
        
        return ev_result
    
    def _estimate_cpp_probability(self, patterns, synergy):
        """
        Calculate weighted break probability using real pattern weights.
        
        patterns: list of pattern details with type and length
        synergy: number of patterns agreeing
        """
        if synergy < 2 or not patterns:
            return 0.5
        
        total_weight = 0
        weighted_prob = 0
        
        for p in patterns:
            pattern_type = p.get('type', 'overall_streak')
            length = p.get('length', 5)
            
            base_rate = PATTERN_BREAK_RATES.get(pattern_type, 0.5)
            
            threshold = CRITICAL_THRESHOLDS.get(pattern_type, 5)
            excess = max(0, length - threshold)
            adjusted_rate = min(base_rate + excess * 0.015, 0.75)
            
            weight = self._get_pattern_weight(pattern_type)
            
            weighted_prob += adjusted_rate * weight
            total_weight += weight
        
        if total_weight > 0:
            raw_prob = weighted_prob / total_weight
            adjusted = 0.6 * raw_prob + 0.4 * (1 - BASE_HOME_WIN_RATE)
            return adjusted
        
        return 0.5
    
    def _get_pattern_weight(self, pattern_type):
        """Get reliability weight for pattern type."""
        weights = {
            'overall_alternation': 1.3,
            'home_alternation': 1.2,
            'overall_streak': 1.0,
            'home_streak': 0.9,
            'h2h_streak': 0.9,
            'away_streak': 0.5,
            'h2h_alternation': 0.8,
            'away_alternation': 0.6,
        }
        return weights.get(pattern_type, 1.0)
    
    def _estimate_break_prob(self, score, league='NHL'):
        """Оценить вероятность прерывания по Score
        
        Примечание: Эти вероятности основаны на анализе NHL данных.
        Для европейских лиг это приблизительная оценка, которая требует
        дополнительной калибровки на исторических данных каждой лиги.
        """
        prob_map = {
            3: 0.41,
            4: 0.50,
            5: 0.60,
            6: 0.70,
        }
        return prob_map.get(min(score, 6), 0.35)
    
    def print_summary(self, league_name):
        """Вывести сводку по лиге"""
        if league_name not in self.team_patterns:
            self.analyze_team_patterns(league_name)
        
        patterns = self.team_patterns[league_name]
        
        print(f"\n📊 Сводка по {league_name}")
        print("=" * 60)
        
        critical_teams = [(t, p) for t, p in patterns.items() 
                         if p.get('overall_critical') or p.get('alt_critical')]
        
        if critical_teams:
            print(f"\n🔥 Команды с критическими паттернами ({len(critical_teams)}):")
            for team, pat in sorted(critical_teams, key=lambda x: abs(x[1].get('overall_streak', 0)), reverse=True)[:10]:
                streak = pat['overall_streak']
                streak_str = f"+{streak}" if streak > 0 else str(streak)
                print(f"  {team}: серия {streak_str}, alt={pat.get('overall_alt', 0)}")
        else:
            print("  Нет критических паттернов")
        
        return patterns


def main():
    """Тест системы"""
    engine = MultiLeaguePatternEngine(critical_length=5)
    
    leagues = ['KHL', 'SHL', 'Liiga', 'DEL']
    engine.load_leagues(leagues, n_seasons=4)
    
    for league in leagues:
        engine.print_summary(league)
    
    print("\n" + "=" * 60)
    print("📅 Предстоящие матчи с сильными сигналами")
    print("=" * 60)
    
    upcoming = engine.get_all_upcoming_with_analysis(leagues)
    
    strong = [m for m in upcoming if m['max_score'] >= 3]
    print(f"\n🎯 Найдено {len(strong)} матчей с Score ≥ 3:")
    
    for m in strong[:10]:
        print(f"\n{m['league']}: {m['away_team']} @ {m['home_team']}")
        print(f"  Score: {m['max_score']} (home={m['home_score']}, away={m['away_score']})")
        print(f"  Home streak: {m['home_pattern'].get('overall_streak', 0)}")
        print(f"  Away streak: {m['away_pattern'].get('overall_streak', 0)}")
        print(f"  📌 {m['recommendation']}")


if __name__ == '__main__':
    main()
