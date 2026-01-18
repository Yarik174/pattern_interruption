"""
Football Pattern Engine - анализ голов по таймам
Специализированный движок для прогнозирования тоталов в футболе
"""
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class FootballPatternEngine:
    """
    Анализатор паттернов для футбольных тоталов по таймам
    
    Типы ставок:
    - FH_O0.5 / FH_U0.5 - Первый тайм больше/меньше 0.5 голов
    - FH_O1.5 / FH_U1.5 - Первый тайм больше/меньше 1.5 голов
    - SH_O0.5 / SH_U0.5 - Второй тайм больше/меньше 0.5 голов
    - SH_O1.5 / SH_U1.5 - Второй тайм больше/меньше 1.5 голов
    """
    
    def __init__(self):
        self.team_stats = defaultdict(lambda: {
            'home': {'fh_goals': [], 'sh_goals': [], 'total_goals': []},
            'away': {'fh_goals': [], 'sh_goals': [], 'total_goals': []}
        })
        self.h2h_stats = defaultdict(lambda: {
            'fh_goals': [],
            'sh_goals': [],
            'total_goals': []
        })
        self.matches_loaded = 0
    
    def load_matches(self, matches: List[Dict]):
        """
        Загрузить исторические матчи для анализа
        
        Формат матча:
        {
            'home_team': str,
            'away_team': str,
            'home_score_fh': int,  # Голы хозяев в 1-м тайме
            'away_score_fh': int,  # Голы гостей в 1-м тайме  
            'home_score': int,     # Итоговый счёт хозяев
            'away_score': int      # Итоговый счёт гостей
        }
        """
        for match in matches:
            try:
                home = match.get('home_team', '')
                away = match.get('away_team', '')
                
                home_fh = match.get('home_score_fh', 0) or 0
                away_fh = match.get('away_score_fh', 0) or 0
                home_total = match.get('home_score', 0) or 0
                away_total = match.get('away_score', 0) or 0
                
                home_sh = home_total - home_fh
                away_sh = away_total - away_fh
                
                fh_total = home_fh + away_fh
                sh_total = home_sh + away_sh
                total = home_total + away_total
                
                self.team_stats[home]['home']['fh_goals'].append(fh_total)
                self.team_stats[home]['home']['sh_goals'].append(sh_total)
                self.team_stats[home]['home']['total_goals'].append(total)
                
                self.team_stats[away]['away']['fh_goals'].append(fh_total)
                self.team_stats[away]['away']['sh_goals'].append(sh_total)
                self.team_stats[away]['away']['total_goals'].append(total)
                
                h2h_key = tuple(sorted([home, away]))
                self.h2h_stats[h2h_key]['fh_goals'].append(fh_total)
                self.h2h_stats[h2h_key]['sh_goals'].append(sh_total)
                self.h2h_stats[h2h_key]['total_goals'].append(total)
                
                self.matches_loaded += 1
                
            except Exception as e:
                logger.warning(f"Error loading match: {e}")
                continue
        
        logger.info(f"FootballPatternEngine: загружено {self.matches_loaded} матчей")
    
    def analyze_match(self, home_team: str, away_team: str) -> Dict:
        """
        Анализировать предстоящий матч и найти паттерны для тоталов
        
        Returns:
            Dict с рекомендациями по тоталам
        """
        patterns = []
        recommendations = {}
        
        home_stats = self.team_stats.get(home_team, {}).get('home', {})
        away_stats = self.team_stats.get(away_team, {}).get('away', {})
        
        h2h_key = tuple(sorted([home_team, away_team]))
        h2h = self.h2h_stats.get(h2h_key, {})
        
        # Анализ первого тайма
        fh_analysis = self._analyze_half(home_stats, away_stats, h2h, 'fh')
        sh_analysis = self._analyze_half(home_stats, away_stats, h2h, 'sh')
        
        # Рекомендации по первому тайму
        if fh_analysis['avg'] is not None:
            if fh_analysis['over_0_5_pct'] >= 0.75:
                patterns.append({
                    'type': 'FH_O0.5',
                    'description': f"Первый тайм с голами в {fh_analysis['over_0_5_pct']*100:.0f}% матчей",
                    'confidence': fh_analysis['over_0_5_pct']
                })
                recommendations['FH_O0.5'] = fh_analysis['over_0_5_pct']
            elif fh_analysis['over_0_5_pct'] <= 0.35:
                patterns.append({
                    'type': 'FH_U0.5',
                    'description': f"Сухой первый тайм в {(1-fh_analysis['over_0_5_pct'])*100:.0f}% матчей",
                    'confidence': 1 - fh_analysis['over_0_5_pct']
                })
                recommendations['FH_U0.5'] = 1 - fh_analysis['over_0_5_pct']
            
            if fh_analysis['over_1_5_pct'] >= 0.60:
                patterns.append({
                    'type': 'FH_O1.5',
                    'description': f"2+ голов в первом тайме в {fh_analysis['over_1_5_pct']*100:.0f}% матчей",
                    'confidence': fh_analysis['over_1_5_pct']
                })
                recommendations['FH_O1.5'] = fh_analysis['over_1_5_pct']
            elif fh_analysis['over_1_5_pct'] <= 0.25:
                patterns.append({
                    'type': 'FH_U1.5',
                    'description': f"До 2 голов в первом тайме в {(1-fh_analysis['over_1_5_pct'])*100:.0f}% матчей",
                    'confidence': 1 - fh_analysis['over_1_5_pct']
                })
                recommendations['FH_U1.5'] = 1 - fh_analysis['over_1_5_pct']
        
        # Рекомендации по второму тайму
        if sh_analysis['avg'] is not None:
            if sh_analysis['over_0_5_pct'] >= 0.80:
                patterns.append({
                    'type': 'SH_O0.5',
                    'description': f"Второй тайм с голами в {sh_analysis['over_0_5_pct']*100:.0f}% матчей",
                    'confidence': sh_analysis['over_0_5_pct']
                })
                recommendations['SH_O0.5'] = sh_analysis['over_0_5_pct']
            elif sh_analysis['over_0_5_pct'] <= 0.30:
                patterns.append({
                    'type': 'SH_U0.5',
                    'description': f"Сухой второй тайм в {(1-sh_analysis['over_0_5_pct'])*100:.0f}% матчей",
                    'confidence': 1 - sh_analysis['over_0_5_pct']
                })
                recommendations['SH_U0.5'] = 1 - sh_analysis['over_0_5_pct']
            
            if sh_analysis['over_1_5_pct'] >= 0.55:
                patterns.append({
                    'type': 'SH_O1.5',
                    'description': f"2+ голов во втором тайме в {sh_analysis['over_1_5_pct']*100:.0f}% матчей",
                    'confidence': sh_analysis['over_1_5_pct']
                })
                recommendations['SH_O1.5'] = sh_analysis['over_1_5_pct']
        
        # Специальные паттерны
        if h2h.get('fh_goals'):
            h2h_fh_avg = sum(h2h['fh_goals']) / len(h2h['fh_goals'])
            if h2h_fh_avg >= 1.5:
                patterns.append({
                    'type': 'H2H_FH_HIGH',
                    'description': f"В очных встречах среднее {h2h_fh_avg:.1f} голов в 1-м тайме",
                    'confidence': min(0.9, h2h_fh_avg / 2)
                })
        
        # Определить лучшую ставку
        best_bet = None
        if recommendations:
            best_bet = max(recommendations.items(), key=lambda x: x[1])
        
        return {
            'patterns': patterns,
            'recommendations': recommendations,
            'best_bet': best_bet[0] if best_bet else None,
            'best_confidence': best_bet[1] if best_bet else 0,
            'fh_analysis': fh_analysis,
            'sh_analysis': sh_analysis,
            'h2h_matches': len(h2h.get('fh_goals', []))
        }
    
    def _analyze_half(self, home_stats: Dict, away_stats: Dict, h2h: Dict, half: str) -> Dict:
        """Анализ статистики для одного тайма"""
        key = f'{half}_goals'
        
        all_goals = []
        
        if home_stats.get(key):
            all_goals.extend(home_stats[key][-10:])
        if away_stats.get(key):
            all_goals.extend(away_stats[key][-10:])
        
        if not all_goals:
            return {'avg': None, 'over_0_5_pct': 0.5, 'over_1_5_pct': 0.3}
        
        avg = sum(all_goals) / len(all_goals)
        over_0_5 = sum(1 for g in all_goals if g > 0) / len(all_goals)
        over_1_5 = sum(1 for g in all_goals if g > 1) / len(all_goals)
        
        return {
            'avg': avg,
            'over_0_5_pct': over_0_5,
            'over_1_5_pct': over_1_5,
            'sample_size': len(all_goals)
        }
    
    def get_team_stats(self, team: str) -> Dict:
        """Получить статистику команды"""
        stats = self.team_stats.get(team, {})
        
        result = {'home': {}, 'away': {}}
        
        for location in ['home', 'away']:
            loc_stats = stats.get(location, {})
            
            fh = loc_stats.get('fh_goals', [])
            sh = loc_stats.get('sh_goals', [])
            total = loc_stats.get('total_goals', [])
            
            if fh:
                result[location] = {
                    'matches': len(fh),
                    'avg_fh_goals': sum(fh) / len(fh),
                    'avg_sh_goals': sum(sh) / len(sh) if sh else 0,
                    'avg_total_goals': sum(total) / len(total) if total else 0,
                    'fh_over_0_5_pct': sum(1 for g in fh if g > 0) / len(fh),
                    'fh_over_1_5_pct': sum(1 for g in fh if g > 1) / len(fh)
                }
        
        return result


class BasketballPatternEngine:
    """
    Анализатор паттернов для баскетбола (победитель матча)
    Учитывает back-to-back игры, домашние/выездные серии
    """
    
    def __init__(self):
        self.team_stats = defaultdict(lambda: {
            'home': {'wins': 0, 'losses': 0, 'points_for': [], 'points_against': []},
            'away': {'wins': 0, 'losses': 0, 'points_for': [], 'points_against': []}
        })
        self.recent_form = defaultdict(list)
        self.h2h = defaultdict(list)
        self.matches_loaded = 0
    
    def load_matches(self, matches: List[Dict]):
        """Загрузить исторические матчи"""
        for match in matches:
            try:
                home = match.get('home_team', '')
                away = match.get('away_team', '')
                home_score = match.get('home_score', 0) or 0
                away_score = match.get('away_score', 0) or 0
                
                if home_score > away_score:
                    self.team_stats[home]['home']['wins'] += 1
                    self.team_stats[away]['away']['losses'] += 1
                    self.recent_form[home].append('W')
                    self.recent_form[away].append('L')
                else:
                    self.team_stats[home]['home']['losses'] += 1
                    self.team_stats[away]['away']['wins'] += 1
                    self.recent_form[home].append('L')
                    self.recent_form[away].append('W')
                
                self.team_stats[home]['home']['points_for'].append(home_score)
                self.team_stats[home]['home']['points_against'].append(away_score)
                self.team_stats[away]['away']['points_for'].append(away_score)
                self.team_stats[away]['away']['points_against'].append(home_score)
                
                h2h_key = tuple(sorted([home, away]))
                self.h2h[h2h_key].append({
                    'home': home,
                    'away': away,
                    'home_score': home_score,
                    'away_score': away_score,
                    'winner': home if home_score > away_score else away
                })
                
                self.matches_loaded += 1
                
            except Exception as e:
                logger.warning(f"Error loading basketball match: {e}")
                continue
        
        logger.info(f"BasketballPatternEngine: загружено {self.matches_loaded} матчей")
    
    def analyze_match(self, home_team: str, away_team: str) -> Dict:
        """Анализировать предстоящий матч"""
        patterns = []
        
        home_stats = self.team_stats.get(home_team, {})
        away_stats = self.team_stats.get(away_team, {})
        
        home_home = home_stats.get('home', {})
        away_away = away_stats.get('away', {})
        
        home_win_pct = 0.5
        if home_home.get('wins', 0) + home_home.get('losses', 0) > 0:
            home_win_pct = home_home['wins'] / (home_home['wins'] + home_home['losses'])
        
        away_win_pct = 0.5
        if away_away.get('wins', 0) + away_away.get('losses', 0) > 0:
            away_win_pct = away_away['wins'] / (away_away['wins'] + away_away['losses'])
        
        home_form = self.recent_form.get(home_team, [])[-5:]
        away_form = self.recent_form.get(away_team, [])[-5:]
        
        home_streak = self._get_streak(home_form)
        away_streak = self._get_streak(away_form)
        
        bet_on = 'home'
        confidence = 0.5
        
        if home_win_pct >= 0.65 and home_streak >= 3:
            bet_on = 'home'
            confidence = min(0.85, home_win_pct + 0.1)
            patterns.append({
                'type': 'HOME_DOMINANT',
                'description': f"{home_team} выигрывает {home_win_pct*100:.0f}% дома, серия {home_streak}W",
                'confidence': confidence
            })
        elif away_win_pct >= 0.55 and away_streak >= 4:
            bet_on = 'away'
            confidence = min(0.80, away_win_pct + 0.1)
            patterns.append({
                'type': 'AWAY_HOT',
                'description': f"{away_team} в ударе, серия {away_streak}W",
                'confidence': confidence
            })
        elif home_win_pct < 0.35 and away_win_pct > 0.60:
            bet_on = 'away'
            confidence = 0.65
            patterns.append({
                'type': 'MISMATCH',
                'description': f"Явное преимущество {away_team}",
                'confidence': confidence
            })
        else:
            confidence = max(home_win_pct, 1 - away_win_pct) * 0.8
            bet_on = 'home' if home_win_pct > (1 - away_win_pct) else 'away'
        
        h2h_key = tuple(sorted([home_team, away_team]))
        h2h_matches = self.h2h.get(h2h_key, [])
        if len(h2h_matches) >= 3:
            recent_h2h = h2h_matches[-5:]
            home_h2h_wins = sum(1 for m in recent_h2h if m['winner'] == home_team)
            if home_h2h_wins >= 4:
                bet_on = 'home'
                confidence = min(confidence + 0.1, 0.90)
                patterns.append({
                    'type': 'H2H_DOMINANT',
                    'description': f"{home_team} доминирует в очных: {home_h2h_wins}/5",
                    'confidence': confidence
                })
            elif home_h2h_wins <= 1:
                bet_on = 'away'
                confidence = min(confidence + 0.1, 0.90)
                patterns.append({
                    'type': 'H2H_UNDERDOG',
                    'description': f"{away_team} доминирует в очных: {5-home_h2h_wins}/5",
                    'confidence': confidence
                })
        
        return {
            'patterns': patterns,
            'bet_on': bet_on,
            'predicted_team': home_team if bet_on == 'home' else away_team,
            'confidence': confidence,
            'home_win_pct': home_win_pct,
            'away_win_pct': away_win_pct,
            'home_streak': home_streak,
            'away_streak': away_streak,
            'h2h_matches': len(h2h_matches)
        }
    
    def _get_streak(self, form: List[str]) -> int:
        """Получить текущую серию побед/поражений"""
        if not form:
            return 0
        
        current = form[-1]
        streak = 0
        for result in reversed(form):
            if result == current:
                streak += 1
            else:
                break
        
        return streak if current == 'W' else -streak


class VolleyballPatternEngine:
    """
    Анализатор паттернов для волейбола
    Учитывает сеты, тай-брейки, камбэки
    """
    
    def __init__(self):
        self.team_stats = defaultdict(lambda: {
            'home': {'wins': 0, 'losses': 0, 'sets_won': 0, 'sets_lost': 0},
            'away': {'wins': 0, 'losses': 0, 'sets_won': 0, 'sets_lost': 0}
        })
        self.tiebreak_stats = defaultdict(lambda: {'wins': 0, 'total': 0})
        self.recent_form = defaultdict(list)
        self.matches_loaded = 0
    
    def load_matches(self, matches: List[Dict]):
        """Загрузить исторические матчи"""
        for match in matches:
            try:
                home = match.get('home_team', '')
                away = match.get('away_team', '')
                home_sets = match.get('home_sets', 0) or 0
                away_sets = match.get('away_sets', 0) or 0
                
                is_tiebreak = (home_sets + away_sets) == 5
                
                if home_sets > away_sets:
                    self.team_stats[home]['home']['wins'] += 1
                    self.team_stats[away]['away']['losses'] += 1
                    self.recent_form[home].append('W')
                    self.recent_form[away].append('L')
                    if is_tiebreak:
                        self.tiebreak_stats[home]['wins'] += 1
                else:
                    self.team_stats[home]['home']['losses'] += 1
                    self.team_stats[away]['away']['wins'] += 1
                    self.recent_form[home].append('L')
                    self.recent_form[away].append('W')
                    if is_tiebreak:
                        self.tiebreak_stats[away]['wins'] += 1
                
                if is_tiebreak:
                    self.tiebreak_stats[home]['total'] += 1
                    self.tiebreak_stats[away]['total'] += 1
                
                self.team_stats[home]['home']['sets_won'] += home_sets
                self.team_stats[home]['home']['sets_lost'] += away_sets
                self.team_stats[away]['away']['sets_won'] += away_sets
                self.team_stats[away]['away']['sets_lost'] += home_sets
                
                self.matches_loaded += 1
                
            except Exception as e:
                logger.warning(f"Error loading volleyball match: {e}")
                continue
        
        logger.info(f"VolleyballPatternEngine: загружено {self.matches_loaded} матчей")
    
    def analyze_match(self, home_team: str, away_team: str) -> Dict:
        """Анализировать предстоящий матч"""
        patterns = []
        
        home_stats = self.team_stats.get(home_team, {}).get('home', {})
        away_stats = self.team_stats.get(away_team, {}).get('away', {})
        
        home_win_pct = 0.5
        total_home = home_stats.get('wins', 0) + home_stats.get('losses', 0)
        if total_home > 0:
            home_win_pct = home_stats['wins'] / total_home
        
        away_win_pct = 0.5
        total_away = away_stats.get('wins', 0) + away_stats.get('losses', 0)
        if total_away > 0:
            away_win_pct = away_stats['wins'] / total_away
        
        home_form = self.recent_form.get(home_team, [])[-5:]
        away_form = self.recent_form.get(away_team, [])[-5:]
        
        home_form_pct = sum(1 for r in home_form if r == 'W') / len(home_form) if home_form else 0.5
        away_form_pct = sum(1 for r in away_form if r == 'W') / len(away_form) if away_form else 0.5
        
        bet_on = 'home'
        confidence = 0.5
        
        combined_home = home_win_pct * 0.6 + home_form_pct * 0.4
        combined_away = away_win_pct * 0.6 + away_form_pct * 0.4
        
        home_tiebreak = self.tiebreak_stats.get(home_team, {})
        away_tiebreak = self.tiebreak_stats.get(away_team, {})
        
        if combined_home > combined_away + 0.15:
            bet_on = 'home'
            confidence = min(0.80, combined_home)
            patterns.append({
                'type': 'HOME_FAVORITE',
                'description': f"{home_team} явный фаворит дома ({home_win_pct*100:.0f}%)",
                'confidence': confidence
            })
        elif combined_away > combined_home + 0.10:
            bet_on = 'away'
            confidence = min(0.75, combined_away)
            patterns.append({
                'type': 'AWAY_STRONG',
                'description': f"{away_team} сильная выездная команда ({away_win_pct*100:.0f}%)",
                'confidence': confidence
            })
        else:
            if home_tiebreak.get('total', 0) >= 3 and home_tiebreak.get('wins', 0) / home_tiebreak.get('total', 1) > 0.6:
                bet_on = 'home'
                confidence = 0.60
                patterns.append({
                    'type': 'TIEBREAK_MASTER',
                    'description': f"{home_team} выигрывает тай-брейки",
                    'confidence': confidence
                })
            else:
                bet_on = 'home' if combined_home >= combined_away else 'away'
                confidence = max(combined_home, combined_away) * 0.9
        
        return {
            'patterns': patterns,
            'bet_on': bet_on,
            'predicted_team': home_team if bet_on == 'home' else away_team,
            'confidence': confidence,
            'home_win_pct': home_win_pct,
            'away_win_pct': away_win_pct,
            'home_form_pct': home_form_pct,
            'away_form_pct': away_form_pct
        }
