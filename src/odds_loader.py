"""
Historical Odds Loader
Загрузчик исторических коэффициентов из Kaggle dataset
"""

import pandas as pd
import numpy as np
from pathlib import Path


class OddsLoader:
    def __init__(self, odds_dir='data/odds'):
        self.odds_dir = Path(odds_dir)
        self.odds_df = None
        
    def load_all_odds(self):
        """Загрузить все файлы с коэффициентами"""
        all_odds = []
        
        for csv_file in self.odds_dir.glob('sportsbook-nhl-*.csv'):
            df = pd.read_csv(csv_file)
            season = csv_file.stem.split('-')[-2] + csv_file.stem.split('-')[-1]
            df['season'] = season
            all_odds.append(df)
            print(f"  Загружено {len(df)} матчей из {csv_file.name}")
            
        if all_odds:
            self.odds_df = pd.concat(all_odds, ignore_index=True)
            self._normalize_data()
            print(f"✅ Всего загружено {len(self.odds_df)} матчей с коэффициентами")
            return self.odds_df
        else:
            print("⚠️ Файлы с коэффициентами не найдены")
            return pd.DataFrame()
    
    def _normalize_data(self):
        """Нормализация данных"""
        self.odds_df['date'] = pd.to_datetime(self.odds_df['date'])
        
        self.odds_df['away_team'] = self.odds_df['a__team'].str.upper()
        self.odds_df['home_team'] = self.odds_df['h__team'].str.upper()
        
        self.odds_df['home_goals'] = self.odds_df['h__goals_total']
        self.odds_df['away_goals'] = self.odds_df['a__goals_total']
        self.odds_df['home_win'] = (self.odds_df['home_goals'] > self.odds_df['away_goals']).astype(int)
        
        self.odds_df['home_odds'], self.odds_df['away_odds'] = zip(*self.odds_df.apply(
            lambda row: self._convert_moneyline(row['moneyline'], row['fav']), axis=1
        ))
        
        self.odds_df['home_implied_prob'] = 1 / self.odds_df['home_odds']
        self.odds_df['away_implied_prob'] = 1 / self.odds_df['away_odds']
        
    def _convert_moneyline(self, moneyline, fav):
        """
        Конвертация American moneyline в decimal odds
        
        Negative moneyline (favorite): -280 means bet $280 to win $100
            Decimal = 1 + (100 / abs(moneyline))
            
        Positive moneyline (underdog): +200 means bet $100 to win $200
            Decimal = 1 + (moneyline / 100)
            
        Returns: (home_odds, away_odds)
        """
        if moneyline == 0 or fav == 'Even':
            return 1.91, 1.91
            
        if fav == 'Home':
            home_odds = 1 + (100 / abs(moneyline))
            away_odds = self._calculate_underdog_odds(home_odds)
        else:
            away_odds = 1 + (100 / abs(moneyline))
            home_odds = self._calculate_underdog_odds(away_odds)
            
        return round(home_odds, 3), round(away_odds, 3)
    
    def _calculate_underdog_odds(self, favorite_odds, margin=0.05):
        """
        Рассчитать коэффициент андердога по коэффициенту фаворита
        Используем стандартную маржу букмекера ~5%
        """
        fav_prob = 1 / favorite_odds
        underdog_prob = 1 - fav_prob + margin
        underdog_prob = max(0.05, min(0.95, underdog_prob))
        return round(1 / underdog_prob, 3)
    
    def merge_with_games(self, games_df):
        """
        Объединить коэффициенты с историческими матчами
        """
        if self.odds_df is None:
            self.load_all_odds()
            
        if self.odds_df is None or len(self.odds_df) == 0:
            return games_df
            
        games_df = games_df.copy()
        games_df['date'] = pd.to_datetime(games_df['date'])
        
        team_mapping = {
            'TB': 'TBL', 'NJ': 'NJD', 'LA': 'LAK', 'SJ': 'SJS',
            'VGK': 'VGK', 'SEA': 'SEA', 'ANA': 'ANA', 'ARI': 'ARI',
            'BOS': 'BOS', 'BUF': 'BUF', 'CGY': 'CGY', 'CAR': 'CAR',
            'CHI': 'CHI', 'COL': 'COL', 'CBJ': 'CBJ', 'DAL': 'DAL',
            'DET': 'DET', 'EDM': 'EDM', 'FLA': 'FLA', 'MIN': 'MIN',
            'MTL': 'MTL', 'NSH': 'NSH', 'NYI': 'NYI', 'NYR': 'NYR',
            'OTT': 'OTT', 'PHI': 'PHI', 'PIT': 'PIT', 'STL': 'STL',
            'TOR': 'TOR', 'VAN': 'VAN', 'WAS': 'WSH', 'WPG': 'WPG',
            'UTA': 'UTA'
        }
        
        odds_copy = self.odds_df.copy()
        odds_copy['home_team_mapped'] = odds_copy['home_team'].map(team_mapping).fillna(odds_copy['home_team'])
        odds_copy['away_team_mapped'] = odds_copy['away_team'].map(team_mapping).fillna(odds_copy['away_team'])
        
        merged = games_df.merge(
            odds_copy[['date', 'home_team_mapped', 'away_team_mapped', 'home_odds', 'away_odds', 'over_under', 'moneyline', 'fav']],
            left_on=['date', 'home_team', 'away_team'],
            right_on=['date', 'home_team_mapped', 'away_team_mapped'],
            how='left'
        )
        
        merged.drop(columns=['home_team_mapped', 'away_team_mapped'], errors='ignore', inplace=True)
        
        matched = merged['home_odds'].notna().sum()
        print(f"📊 Сматчено {matched}/{len(games_df)} матчей с коэффициентами ({100*matched/len(games_df):.1f}%)")
        
        return merged
    
    def calculate_ev(self, probability, odds):
        """
        Расчёт Expected Value
        EV = (probability * (odds - 1)) - (1 - probability)
        
        EV > 0 означает +EV ставку
        """
        return probability * (odds - 1) - (1 - probability)
    
    def backtest_strategy(self, games_with_odds, min_synergy=2, min_ev=0.05):
        """
        Бэктест CPP стратегии на исторических данных
        
        Returns:
            dict с метриками: total_bets, wins, roi, profit
        """
        games = games_with_odds.dropna(subset=['home_odds', 'away_odds', 'synergy_home', 'synergy_away'])
        
        if len(games) == 0:
            return {'error': 'No games with odds and synergy data'}
            
        results = {
            'total_bets': 0,
            'wins': 0,
            'total_staked': 0,
            'total_return': 0,
            'bets': []
        }
        
        for _, game in games.iterrows():
            bet = None
            
            if game.get('synergy_home', 0) >= min_synergy:
                ev = self.calculate_ev(0.55, game['home_odds'])
                if ev >= min_ev:
                    bet = {
                        'date': game['date'],
                        'match': f"{game['away_team']} @ {game['home_team']}",
                        'bet_on': 'home',
                        'odds': game['home_odds'],
                        'ev': ev,
                        'result': game['home_win']
                    }
                    
            elif game.get('synergy_away', 0) >= min_synergy:
                ev = self.calculate_ev(0.55, game['away_odds'])
                if ev >= min_ev:
                    bet = {
                        'date': game['date'],
                        'match': f"{game['away_team']} @ {game['home_team']}",
                        'bet_on': 'away',
                        'odds': game['away_odds'],
                        'ev': ev,
                        'result': 1 - game['home_win']
                    }
                    
            if bet:
                results['total_bets'] += 1
                results['total_staked'] += 1
                
                if bet['result'] == 1:
                    results['wins'] += 1
                    results['total_return'] += bet['odds']
                    
                results['bets'].append(bet)
                
        if results['total_bets'] > 0:
            results['win_rate'] = results['wins'] / results['total_bets']
            results['roi'] = (results['total_return'] - results['total_staked']) / results['total_staked']
            results['profit'] = results['total_return'] - results['total_staked']
        else:
            results['win_rate'] = 0
            results['roi'] = 0
            results['profit'] = 0
            
        return results


if __name__ == '__main__':
    loader = OddsLoader()
    odds = loader.load_all_odds()
    
    print("\nПример данных:")
    print(odds[['date', 'home_team', 'away_team', 'moneyline', 'fav', 'home_odds', 'away_odds', 'home_win']].head(10))
    
    print("\nСтатистика:")
    print(f"  Home win rate: {odds['home_win'].mean():.1%}")
    print(f"  Avg home odds: {odds['home_odds'].mean():.2f}")
    print(f"  Avg away odds: {odds['away_odds'].mean():.2f}")
