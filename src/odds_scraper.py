"""
Scraper for historical NHL betting odds from sportsbookreviewsonline.com
"""
import requests
import pandas as pd
from io import StringIO
import os
from pathlib import Path
import time

TEAM_MAPPING = {
    'Montreal': 'MTL', 'Toronto': 'TOR', 'Boston': 'BOS', 'Washington': 'WSH',
    'Calgary': 'CGY', 'Vancouver': 'VAN', 'Anaheim': 'ANA', 'SanJose': 'SJS',
    'Pittsburgh': 'PIT', 'NYIslanders': 'NYI', 'Carolina': 'CAR', 'Buffalo': 'BUF',
    'Columbus': 'CBJ', 'Detroit': 'DET', 'Chicago': 'CHI', 'Ottawa': 'OTT',
    'Nashville': 'NSH', 'NYRangers': 'NYR', 'Winnipeg': 'WPG', 'St.Louis': 'STL',
    'Arizona': 'ARI', 'Dallas': 'DAL', 'Minnesota': 'MIN', 'Colorado': 'COL',
    'Philadelphia': 'PHI', 'Vegas': 'VGK', 'Edmonton': 'EDM', 'NewJersey': 'NJD',
    'Florida': 'FLA', 'TampaBay': 'TBL', 'LosAngeles': 'LAK', 'Seattle': 'SEA'
}

SEASONS = [
    ('2023-24', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2023-24'),
    ('2022-23', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2022-23'),
    ('2021-22', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2021-22'),
    ('2020-21', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2021'),
    ('2019-20', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2019-20'),
    ('2018-19', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2018-19'),
    ('2017-18', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2017-18'),
    ('2016-17', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2016-17'),
]


def moneyline_to_decimal(ml: int) -> float:
    """Convert American moneyline to decimal odds"""
    try:
        ml = int(ml)
        if ml > 0:
            return round(1 + ml / 100, 3)
        elif ml < 0:
            return round(1 + 100 / abs(ml), 3)
    except (ValueError, TypeError):
        pass
    return None


def parse_html_table(html: str, season: str) -> pd.DataFrame:
    """Parse HTML table into structured DataFrame"""
    try:
        dfs = pd.read_html(StringIO(html))
        if not dfs:
            return pd.DataFrame()
        
        df = dfs[0]
        df.columns = ['Date', 'Rot', 'VH', 'Team', '1st', '2nd', '3rd', 'Final', 
                      'Open', 'Close', 'PuckLine', 'PL_Odds', 'OpenOU', 'OU_Open_Odds', 
                      'CloseOU', 'OU_Close_Odds'][:len(df.columns)]
        
        df = df[df['VH'].isin(['V', 'H'])].copy()
        
        games = []
        visitor = None
        
        for idx, row in df.iterrows():
            if row['VH'] == 'V':
                visitor = row
            elif row['VH'] == 'H' and visitor is not None:
                try:
                    date_str = str(visitor['Date'])
                    if len(date_str) == 4:
                        month = int(date_str[:2])
                        day = int(date_str[2:])
                        year = int(season.split('-')[0]) if month >= 10 else int('20' + season.split('-')[1])
                        date = f"{year}-{month:02d}-{day:02d}"
                    else:
                        date = None
                    
                    away_team = TEAM_MAPPING.get(str(visitor['Team']).strip(), str(visitor['Team']).strip())
                    home_team = TEAM_MAPPING.get(str(row['Team']).strip(), str(row['Team']).strip())
                    
                    away_score = int(visitor['Final']) if pd.notna(visitor['Final']) else 0
                    home_score = int(row['Final']) if pd.notna(row['Final']) else 0
                    
                    away_ml = int(visitor['Close']) if pd.notna(visitor['Close']) else None
                    home_ml = int(row['Close']) if pd.notna(row['Close']) else None
                    
                    games.append({
                        'date': date,
                        'season': season,
                        'away_team': away_team,
                        'home_team': home_team,
                        'away_score': away_score,
                        'home_score': home_score,
                        'away_moneyline': away_ml,
                        'home_moneyline': home_ml,
                        'away_odds': moneyline_to_decimal(away_ml) if away_ml else None,
                        'home_odds': moneyline_to_decimal(home_ml) if home_ml else None,
                        'home_win': 1 if home_score > away_score else 0
                    })
                except (ValueError, TypeError):
                    pass
                visitor = None
        
        return pd.DataFrame(games)
        
    except Exception as e:
        print(f"  Parse error: {e}")
        return pd.DataFrame()


def scrape_season(season: str, url: str, cache_dir: Path) -> pd.DataFrame:
    """Scrape a single season"""
    cache_file = cache_dir / f"sbro-{season}.csv"
    
    if cache_file.exists():
        print(f"  [CACHE] {season}: ", end='')
        df = pd.read_csv(cache_file)
        print(f"{len(df)} games")
        return df
    
    print(f"  [FETCH] {season}...")
    
    try:
        resp = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        if resp.status_code != 200:
            print(f"    ERROR: HTTP {resp.status_code}")
            return pd.DataFrame()
        
        df = parse_html_table(resp.text, season)
        
        if len(df) > 0:
            df.to_csv(cache_file, index=False)
            print(f"    Saved {len(df)} games")
        else:
            print(f"    No games parsed")
        
        time.sleep(2)
        return df
        
    except Exception as e:
        print(f"    ERROR: {e}")
        return pd.DataFrame()


def load_all_historical_odds(n_seasons: int = 8) -> pd.DataFrame:
    """Load historical odds from all sources"""
    cache_dir = Path("data/odds")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    all_dfs = []
    
    print("Loading scraped seasons...")
    for season, url in SEASONS[:n_seasons]:
        df = scrape_season(season, url, cache_dir)
        if len(df) > 0:
            all_dfs.append(df)
    
    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        combined = combined.dropna(subset=['date', 'home_team', 'away_team'])
        combined = combined.drop_duplicates(subset=['date', 'home_team', 'away_team'])
        combined = combined.sort_values('date').reset_index(drop=True)
        print(f"\nTotal: {len(combined)} games with odds")
        print(f"Date range: {combined['date'].min()} to {combined['date'].max()}")
        return combined
    
    return pd.DataFrame()


if __name__ == "__main__":
    df = load_all_historical_odds(8)
    if len(df) > 0:
        print(f"\nSample data:")
        print(df[['date', 'home_team', 'away_team', 'home_odds', 'away_odds', 'home_win']].head(10))
