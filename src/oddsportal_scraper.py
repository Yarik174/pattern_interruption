import os
import json
import time
import re
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

LEAGUES = {
    'khl': {'country': 'russia', 'name': 'khl'},
    'shl': {'country': 'sweden', 'name': 'shl'},
    'liiga': {'country': 'finland', 'name': 'liiga'},
    'del': {'country': 'germany', 'name': 'del'},
}

SEASONS = ['2023-2024', '2022-2023', '2021-2022', '2020-2021', '2019-2020']

class OddsPortalScraper:
    def __init__(self, headless=True):
        self.headless = headless
        self.data_dir = Path('data/odds/european')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
    def scrape_league_season(self, league: str, season: str) -> list:
        config = LEAGUES.get(league)
        if not config:
            print(f"Unknown league: {league}")
            return []
            
        country = config['country']
        name = config['name']
        
        if season == '2025-2026':
            url = f"https://www.oddsportal.com/hockey/{country}/{name}/results/"
        else:
            url = f"https://www.oddsportal.com/hockey/{country}/{name}-{season}/results/"
        
        print(f"\n📥 Scraping {league.upper()} {season}: {url}")
        
        matches = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            try:
                page.goto(url, timeout=30000)
                time.sleep(3)
                
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)
                
                match_rows = page.query_selector_all('div.eventRow, div[class*="eventRow"]')
                
                if not match_rows:
                    match_rows = page.query_selector_all('div.group.flex')
                
                print(f"  Found {len(match_rows)} match elements")
                
                for row in match_rows:
                    try:
                        match_data = self._parse_match_row(row, league, season)
                        if match_data:
                            matches.append(match_data)
                    except Exception as e:
                        continue
                        
                page_num = 1
                while page_num < 10:
                    next_btn = page.query_selector('a[data-page="next"], a.pagination-next')
                    if not next_btn:
                        break
                    
                    next_btn.click()
                    time.sleep(2)
                    page_num += 1
                    
                    new_rows = page.query_selector_all('div.eventRow, div[class*="eventRow"], div.group.flex')
                    for row in new_rows:
                        try:
                            match_data = self._parse_match_row(row, league, season)
                            if match_data:
                                matches.append(match_data)
                        except:
                            continue
                    
                    print(f"    Page {page_num}: total {len(matches)} matches")
                    
            except Exception as e:
                print(f"  Error: {e}")
            finally:
                browser.close()
        
        print(f"  ✅ Scraped {len(matches)} matches for {league.upper()} {season}")
        return matches
    
    def _parse_match_row(self, row, league: str, season: str) -> dict:
        text = row.inner_text()
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        
        if len(lines) < 4:
            return None
            
        date_str = None
        home_team = None
        away_team = None
        score = None
        home_odds = None
        away_odds = None
        
        for i, line in enumerate(lines):
            if re.match(r'\d{1,2}\s+\w{3}\s+\d{4}', line) or re.match(r'\d{2}:\d{2}', line):
                date_str = line
                continue
            
            if ' - ' in line and not re.match(r'^\d', line):
                parts = line.split(' - ')
                if len(parts) == 2:
                    home_team = parts[0].strip()
                    away_team = parts[1].strip()
                continue
            
            score_match = re.match(r'^(\d+):(\d+)(?:\s*OT)?$', line)
            if score_match:
                score = line
                continue
            
            odds_match = re.match(r'^(\d+\.\d+)$', line)
            if odds_match:
                if home_odds is None:
                    home_odds = float(line)
                elif away_odds is None:
                    away_odds = float(line)
        
        if home_team and away_team and home_odds and away_odds:
            overtime = 'OT' in (score or '')
            score_clean = (score or '').replace('OT', '').strip()
            
            home_goals = None
            away_goals = None
            if score_clean and ':' in score_clean:
                parts = score_clean.split(':')
                home_goals = int(parts[0])
                away_goals = int(parts[1])
            
            return {
                'date': date_str,
                'home_team': home_team,
                'away_team': away_team,
                'home_goals': home_goals,
                'away_goals': away_goals,
                'overtime': overtime,
                'home_odds': home_odds,
                'away_odds': away_odds,
                'league': league.upper(),
                'season': season
            }
        
        return None
    
    def scrape_all_leagues(self, seasons: list = None):
        if seasons is None:
            seasons = SEASONS[:3]
        
        all_data = {}
        
        for league in LEAGUES.keys():
            all_data[league] = []
            
            for season in seasons:
                matches = self.scrape_league_season(league, season)
                all_data[league].extend(matches)
                time.sleep(2)
            
            output_file = self.data_dir / f"{league}_odds.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_data[league], f, ensure_ascii=False, indent=2)
            
            print(f"\n💾 Saved {len(all_data[league])} matches to {output_file}")
        
        return all_data
    
    def load_scraped_data(self, league: str) -> list:
        file_path = self.data_dir / f"{league}_odds.json"
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []


def main():
    scraper = OddsPortalScraper(headless=True)
    
    print("🏒 OddsPortal European Hockey Leagues Scraper")
    print("=" * 50)
    print(f"Leagues: {', '.join(LEAGUES.keys())}")
    print(f"Seasons: {SEASONS[:3]}")
    print()
    
    data = scraper.scrape_all_leagues(seasons=SEASONS[:3])
    
    print("\n" + "=" * 50)
    print("📊 Summary:")
    for league, matches in data.items():
        print(f"  {league.upper()}: {len(matches)} matches")


if __name__ == '__main__':
    main()
