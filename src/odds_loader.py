"""
Historical Odds Loader
Загрузчик исторических коэффициентов из разных источников
"""

import pandas as pd
import numpy as np
from pathlib import Path


class OddsLoader:
    def __init__(self, odds_dir='data/odds'):
        self.odds_dir = Path(odds_dir)
        self.odds_df = None
        
    def load_all_odds(self):
        """Загрузить все файлы с коэффициентами из разных источников"""
        all_odds = []
        
        for csv_file in self.odds_dir.glob('sbro-*.csv'):
            df = pd.read_csv(csv_file)
            all_odds.append(df)
            print(f"  Загружено {len(df)} матчей из {csv_file.name}")
        
        for csv_file in self.odds_dir.glob('sportsbook-nhl-*.csv'):
            df = pd.read_csv(csv_file)
            df = self._normalize_kaggle_data(df)
            all_odds.append(df)
            print(f"  Загружено {len(df)} матчей из {csv_file.name}")
            
        if all_odds:
            self.odds_df = pd.concat(all_odds, ignore_index=True)
            self.odds_df = self.odds_df.dropna(subset=['date', 'home_team', 'away_team'])
            self.odds_df = self.odds_df.drop_duplicates(subset=['date', 'home_team', 'away_team'])
            self.odds_df['date'] = pd.to_datetime(self.odds_df['date'])
            self.odds_df = self.odds_df.sort_values('date').reset_index(drop=True)
            
            self._add_regulation_result()
            
            print(f"✅ Всего {len(self.odds_df)} матчей с коэффициентами")
            return self.odds_df
        else:
            print("⚠️ Файлы с коэффициентами не найдены")
            return pd.DataFrame()
    
    def _normalize_kaggle_data(self, df):
        """Нормализация данных из Kaggle формата"""
        result = pd.DataFrame()
        result['date'] = df['date']
        result['away_team'] = df['a__team'].str.upper()
        result['home_team'] = df['h__team'].str.upper()
        result['away_score'] = df['a__goals_total']
        result['home_score'] = df['h__goals_total']
        result['home_win'] = (df['h__goals_total'] > df['a__goals_total']).astype(int)
        
        if 'a__goals_ot' in df.columns and 'h__goals_ot' in df.columns:
            result['overtime'] = ((df['a__goals_ot'] > 0) | (df['h__goals_ot'] > 0)).astype(int)
        else:
            result['overtime'] = 0
        
        result['home_odds'], result['away_odds'] = zip(*df.apply(
            lambda row: self._convert_moneyline(row['moneyline'], row['fav']), axis=1
        ))
        
        return result
        
    def _convert_moneyline(self, moneyline, fav):
        """
        Конвертация American moneyline в decimal odds
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
        """Рассчитать коэффициент андердога"""
        fav_prob = 1 / favorite_odds
        underdog_prob = 1 - fav_prob + margin
        underdog_prob = max(0.05, min(0.95, underdog_prob))
        return round(1 / underdog_prob, 3)
    
    def _add_regulation_result(self):
        """
        Добавить regulation_result к данным
        regulation_result: 0=home, 1=away, 2=draw (overtime)
        """
        if 'overtime' not in self.odds_df.columns:
            self.odds_df['overtime'] = 0
        
        self.odds_df['overtime'] = self.odds_df['overtime'].fillna(0).astype(int)
        
        def calc_regulation(row):
            if row.get('overtime', 0) == 1:
                return 2
            elif row['home_win'] == 1:
                return 0
            else:
                return 1
        
        self.odds_df['regulation_result'] = self.odds_df.apply(calc_regulation, axis=1)
        
        ot_count = (self.odds_df['overtime'] == 1).sum()
        print(f"  📊 Матчи с овертаймом: {ot_count} ({ot_count/len(self.odds_df):.1%})")
    
    def calculate_ev(self, probability, odds):
        """Расчёт Expected Value"""
        return probability * (odds - 1) - (1 - probability)


if __name__ == '__main__':
    loader = OddsLoader()
    odds = loader.load_all_odds()
    
    print("\nПример данных:")
    print(odds[['date', 'home_team', 'away_team', 'home_odds', 'away_odds', 'home_win']].head(10))
    
    print("\nСтатистика:")
    print(f"  Home win rate: {odds['home_win'].mean():.1%}")
    print(f"  Date range: {odds['date'].min()} to {odds['date'].max()}")
