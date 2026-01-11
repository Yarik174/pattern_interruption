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
    
    def analyze_match(self, league_name, home_team, away_team):
        """Анализ конкретного матча"""
        if league_name not in self.team_patterns:
            self.analyze_team_patterns(league_name)
        
        patterns = self.team_patterns.get(league_name, {})
        home_pattern = patterns.get(home_team, {})
        away_pattern = patterns.get(away_team, {})
        
        home_score = self.calc_strong_signal(home_pattern)
        away_score = self.calc_strong_signal(away_pattern)
        
        return {
            'league': league_name,
            'home_team': home_team,
            'away_team': away_team,
            'home_pattern': home_pattern,
            'away_pattern': away_pattern,
            'home_score': home_score,
            'away_score': away_score,
            'max_score': max(home_score, away_score),
            'recommendation': self._get_recommendation(home_pattern, away_pattern, home_score, away_score)
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
        """Рассчитать Expected Value
        
        Примечание: EV расчёт использует вероятности, калиброванные на NHL данных.
        Для европейских лиг (SHL, Liiga) это приблизительная оценка.
        """
        home_pattern = analysis.get('home_pattern', {})
        away_pattern = analysis.get('away_pattern', {})
        home_score = analysis.get('home_score', 0)
        away_score = analysis.get('away_score', 0)
        league = analysis.get('league', 'NHL')
        
        ev_result = {
            'bet_on': None,
            'odds': 0,
            'break_prob': 0,
            'ev': 0,
            'ev_percent': 0,
            'calibrated': league == 'NHL',
            'note': 'Калибровано на NHL' if league == 'NHL' else 'Приблизительная оценка (на основе NHL)'
        }
        
        if home_score >= away_score and home_score >= 3:
            streak = home_pattern.get('overall_streak', 0)
            if streak > 0:
                odds = odds_data.get('away_odds', 0)
                bet_on = 'away'
            elif streak < 0:
                odds = odds_data.get('home_odds', 0)
                bet_on = 'home'
            else:
                return ev_result
        elif away_score >= 3:
            streak = away_pattern.get('overall_streak', 0)
            if streak > 0:
                odds = odds_data.get('home_odds', 0)
                bet_on = 'home'
            elif streak < 0:
                odds = odds_data.get('away_odds', 0)
                bet_on = 'away'
            else:
                return ev_result
        else:
            return ev_result
        
        score = max(home_score, away_score)
        break_prob = self._estimate_break_prob(score)
        
        if odds > 0:
            ev = (break_prob * (odds - 1)) - (1 - break_prob)
            ev_percent = ev * 100
            
            ev_result = {
                'bet_on': bet_on,
                'odds': odds,
                'break_prob': break_prob,
                'ev': ev,
                'ev_percent': ev_percent
            }
        
        return ev_result
    
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
    engine.load_leagues(leagues, n_seasons=3)
    
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
