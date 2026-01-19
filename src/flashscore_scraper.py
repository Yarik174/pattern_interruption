"""
FlashScore Scraper - универсальный скрейпер для всех видов спорта
Парсит исторические матчи с коэффициентами
"""
import asyncio
import json
import random
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class MatchData:
    """Универсальная структура матча"""
    match_id: str
    date: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    home_odds: Optional[float] = None
    draw_odds: Optional[float] = None
    away_odds: Optional[float] = None
    sport: str = ""
    league: str = ""
    match_url: Optional[str] = None
    home_score_ht: Optional[int] = None
    away_score_ht: Optional[int] = None
    home_sets: Optional[int] = None
    away_sets: Optional[int] = None
    set_scores: Optional[List[str]] = None
    periods: Optional[List[Dict]] = None


LEAGUE_URLS = {
    'hockey': {
        # NHL данные уже есть через NHL API (13,000+ матчей)
        'KHL': '/hockey/russia/khl/',
        'SHL': '/hockey/sweden/shl/',
        'Liiga': '/hockey/finland/liiga/',
        'DEL': '/hockey/germany/del/',
    },
    'football': {
        'EPL': '/football/england/premier-league/',
        'LaLiga': '/football/spain/laliga/',
        'Bundesliga': '/football/germany/bundesliga/',
        'SerieA': '/football/italy/serie-a/',
        'Ligue1': '/football/france/ligue-1/',
    },
    'basketball': {
        'NBA': '/basketball/usa/nba/',
        'EuroLeague': '/basketball/europe/euroleague/',
        'VTB': '/basketball/russia/vtb-united-league/',
        'ACB': '/basketball/spain/acb/',
        'BBL': '/basketball/germany/bbl/',
    },
    'volleyball': {
        'Superliga': '/volleyball/russia/superleague/',
        'SerieA': '/volleyball/italy/superlega/',
        'PlusLiga': '/volleyball/poland/plusliga/',
        'Bundesliga': '/volleyball/germany/bundesliga/',
        'CEV': '/volleyball/europe/champions-league/',
    }
}


class FlashScoreScraper:
    """Скрейпер для flashscore.com"""
    
    BASE_URL = "https://www.flashscore.com"
    
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        
    async def init_browser(self):
        """Инициализация браузера"""
        from playwright.async_api import async_playwright
        
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        self.page = await self.context.new_page()
        
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        
        logger.info("Browser initialized")
        
    async def close(self):
        """Закрыть браузер"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
            
    async def _random_delay(self, min_sec: float = 2.0, max_sec: float = 5.0):
        """Случайная задержка для имитации человека"""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)
        
    async def get_season_results(self, sport: str, league: str, season: str) -> List[MatchData]:
        """
        Получить результаты сезона
        
        Args:
            sport: hockey/football/basketball/volleyball
            league: название лиги (NHL, EPL, etc)
            season: сезон в формате "2023-2024"
        """
        if sport not in LEAGUE_URLS:
            raise ValueError(f"Unknown sport: {sport}")
        if league not in LEAGUE_URLS[sport]:
            raise ValueError(f"Unknown league: {league} for {sport}")
            
        base_path = LEAGUE_URLS[sport][league]
        url = f"{self.BASE_URL}{base_path}results/"
        
        logger.info(f"Fetching {sport}/{league} season {season} from {url}")
        
        try:
            await self.page.goto(url, wait_until='networkidle', timeout=60000)
            await self._random_delay(2, 4)
            
            await self._accept_cookies()
            
            matches = await self._parse_results_page(sport)
            
            for m in matches:
                m.sport = sport
                m.league = league
                
            logger.info(f"Found {len(matches)} matches for {sport}/{league}")
            return matches
            
        except Exception as e:
            logger.error(f"Error fetching {sport}/{league}: {e}")
            return []
            
    async def _accept_cookies(self):
        """Принять куки если есть попап"""
        try:
            cookie_btn = self.page.locator('#onetrust-accept-btn-handler')
            if await cookie_btn.is_visible(timeout=2000):
                await cookie_btn.click()
                await self._random_delay(0.5, 1)
        except:
            pass
            
    async def _parse_results_page(self, sport: str) -> List[MatchData]:
        """Парсинг страницы результатов"""
        matches = []
        
        await self.page.wait_for_selector('.event__match', timeout=10000)
        
        match_elements = await self.page.query_selector_all('.event__match')
        
        for el in match_elements:
            try:
                match_data = await self._parse_match_element(el, sport)
                if match_data:
                    matches.append(match_data)
            except Exception as e:
                logger.warning(f"Error parsing match: {e}")
                continue
                
        return matches
        
    async def _parse_match_element(self, el, sport: str) -> Optional[MatchData]:
        """Парсинг одного матча"""
        try:
            match_id = await el.get_attribute('id')
            match_url = None
            
            link = await el.query_selector('a.eventRowLink')
            if link:
                href = await link.get_attribute('href')
                if href:
                    # Убираем параметры ?mid= для чистого URL
                    match_url = href.split('?')[0] if '?' in href else href
                    if not match_id:
                        match_id = href.split('?mid=')[-1] if '?mid=' in href else href.split('/')[-2]
            
            if not match_id:
                return None
            match_id = match_id.replace('g_1_', '')
            
            home_team_el = await el.query_selector('.event__participant--home')
            away_team_el = await el.query_selector('.event__participant--away')
            
            if not home_team_el or not away_team_el:
                home_team_el = await el.query_selector('.event__homeParticipant .wcl-name_jjfMf')
                away_team_el = await el.query_selector('.event__awayParticipant .wcl-name_jjfMf')
            
            if not home_team_el or not away_team_el:
                home_team_el = await el.query_selector('.event__homeParticipant')
                away_team_el = await el.query_selector('.event__awayParticipant')
            
            if not home_team_el or not away_team_el:
                return None
                
            home_team = await home_team_el.inner_text()
            away_team = await away_team_el.inner_text()
            
            home_score = 0
            away_score = 0
            
            home_score_el = await el.query_selector('.event__score--home')
            away_score_el = await el.query_selector('.event__score--away')
            
            if home_score_el and away_score_el:
                home_score_text = await home_score_el.inner_text()
                away_score_text = await away_score_el.inner_text()
                try:
                    home_score = int(home_score_text.strip())
                    away_score = int(away_score_text.strip())
                except:
                    pass
                    
            date_el = await el.query_selector('.event__time')
            date_str = ""
            if date_el:
                date_str = await date_el.inner_text()
                
            match = MatchData(
                match_id=match_id,
                date=date_str,
                home_team=home_team.strip(),
                away_team=away_team.strip(),
                home_score=home_score,
                away_score=away_score,
                sport=sport,
                match_url=match_url
            )
            
            if sport == 'football':
                match = await self._parse_football_details(el, match)
            elif sport == 'volleyball':
                match = await self._parse_volleyball_details(el, match)
                
            return match
            
        except Exception as e:
            logger.warning(f"Parse error: {e}")
            return None
            
    async def _parse_football_details(self, el, match: MatchData) -> MatchData:
        """Дополнительные данные для футбола (голы по таймам)"""
        try:
            ht_home_el = await el.query_selector('.event__part--home')
            ht_away_el = await el.query_selector('.event__part--away')
            
            if ht_home_el and ht_away_el:
                ht_home = await ht_home_el.inner_text()
                ht_away = await ht_away_el.inner_text()
                ht_home = ht_home.replace('(', '').replace(')', '').strip()
                ht_away = ht_away.replace('(', '').replace(')', '').strip()
                try:
                    match.home_score_ht = int(ht_home)
                    match.away_score_ht = int(ht_away)
                except:
                    pass
        except:
            pass
        return match
        
    async def _parse_volleyball_details(self, el, match: MatchData) -> MatchData:
        """Дополнительные данные для волейбола (сеты)"""
        try:
            sets = await el.query_selector_all('.event__part')
            if sets:
                set_scores = []
                for s in sets:
                    score = await s.inner_text()
                    set_scores.append(score.strip())
                match.set_scores = set_scores
                
            if match.home_score is not None and match.away_score is not None:
                match.home_sets = match.home_score
                match.away_sets = match.away_score
        except:
            pass
        return match
        
    async def get_match_odds(self, match_url: str) -> Dict[str, float]:
        """Получить коэффициенты для матча"""
        if not match_url:
            return {'home': None, 'draw': None, 'away': None}
        
        # Добавляем путь к коэффициентам
        url = f"{match_url}#/odds-comparison/1x2-odds/full-time"
        
        try:
            await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await self._random_delay(2, 3)
            
            odds = {'home': None, 'draw': None, 'away': None}
            
            # Ждём появления коэффициентов
            try:
                await self.page.wait_for_selector('[class*="oddsCell"], .wclOddsContent', timeout=10000)
            except:
                pass
            
            # Новый селектор — ищем контейнер с коэффициентами
            odds_container = await self.page.query_selector('.wclOddsContent, .odds')
            if odds_container:
                text = await odds_container.inner_text()
                # Текст в формате "1.60\n4.00\n5.50"
                parts = [p.strip() for p in text.split('\n') if p.strip()]
                if len(parts) >= 3:
                    try:
                        odds['home'] = float(parts[0])
                        odds['draw'] = float(parts[1])
                        odds['away'] = float(parts[2])
                    except:
                        pass
            
            # Fallback — ищем отдельные ячейки
            if odds['home'] is None:
                cells = await self.page.query_selector_all('.wcl-oddsInfo_CqWpN, [class*="oddsCell"]')
                if len(cells) >= 3:
                    try:
                        odds['home'] = float(await cells[0].inner_text())
                        odds['draw'] = float(await cells[1].inner_text())
                        odds['away'] = float(await cells[2].inner_text())
                    except:
                        pass
                        
            return odds
            
        except Exception as e:
            logger.warning(f"Error fetching odds for {match_id}: {e}")
            return {'home': None, 'draw': None, 'away': None}
            
    async def scrape_league_history(
        self, 
        sport: str, 
        league: str, 
        num_pages: int = 10,
        with_odds: bool = True
    ) -> List[MatchData]:
        """
        Скрейпить историю лиги с пагинацией
        
        Args:
            sport: вид спорта
            league: лига
            num_pages: количество страниц (каждая ~40 матчей)
            with_odds: загружать ли коэффициенты (медленнее)
        """
        all_matches = []
        
        base_path = LEAGUE_URLS[sport][league]
        url = f"{self.BASE_URL}{base_path}results/"
        
        logger.info(f"Starting scrape for {sport}/{league}, {num_pages} pages")
        
        try:
            await self.page.goto(url, wait_until='domcontentloaded', timeout=45000)
            await self._random_delay(3, 5)  # Даём время на загрузку JS
            await self._accept_cookies()
            
            # Сначала раскрываем все страницы кликами на Show more
            for page_num in range(num_pages - 1):
                try:
                    show_more = self.page.locator('a[class*="event__more"], a:has-text("Show more")')
                    if await show_more.count() > 0 and await show_more.first.is_visible():
                        await show_more.first.scroll_into_view_if_needed()
                        await self._random_delay(0.5, 1)
                        await show_more.first.click()
                        logger.info(f"Clicked Show more ({page_num + 1}/{num_pages - 1})")
                        await self._random_delay(3, 5)
                    else:
                        logger.info("No more pages available")
                        break
                except Exception as e:
                    logger.warning(f"Pagination error: {e}")
                    break
            
            # Теперь парсим все матчи на странице
            logger.info("Parsing all matches...")
            all_matches = await self._parse_results_page(sport)
            
            for m in all_matches:
                m.sport = sport
                m.league = league
                
            if with_odds and all_matches:
                # Ограничиваем до 50 матчей с коэффициентами для скорости
                odds_limit = min(50, len(all_matches))
                logger.info(f"Fetching odds for {odds_limit} of {len(all_matches)} matches...")
                for i, m in enumerate(all_matches[:odds_limit]):
                    if i % 10 == 0:
                        logger.info(f"Fetching odds: {i}/{odds_limit}")
                    odds = await self.get_match_odds(m.match_url)
                    m.home_odds = odds['home']
                    m.draw_odds = odds['draw']
                    m.away_odds = odds['away']
                    await self._random_delay(0.3, 0.8)  # Сокращаем задержку
                    
        except Exception as e:
            logger.error(f"Error scraping {sport}/{league}: {e}")
            
        logger.info(f"Total matches scraped: {len(all_matches)}")
        return all_matches
        
    def save_to_cache(self, matches: List[MatchData], sport: str, league: str):
        """Сохранить в кэш"""
        cache_dir = f"data/cache/{sport}"
        os.makedirs(cache_dir, exist_ok=True)
        
        filepath = f"{cache_dir}/{league}_matches.json"
        
        data = [asdict(m) for m in matches]
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"Saved {len(matches)} matches to {filepath}")
        
    @staticmethod
    def load_from_cache(sport: str, league: str) -> List[Dict]:
        """Загрузить из кэша"""
        filepath = f"data/cache/{sport}/{league}_matches.json"
        
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []


async def main():
    """Тестовый запуск"""
    logging.basicConfig(level=logging.INFO)
    
    scraper = FlashScoreScraper()
    await scraper.init_browser()
    
    try:
        matches = await scraper.scrape_league_history(
            sport='hockey',
            league='KHL',
            num_pages=2,
            with_odds=False
        )
        
        print(f"Scraped {len(matches)} matches")
        for m in matches[:3]:
            print(f"  {m.home_team} vs {m.away_team}: {m.home_score}-{m.away_score}")
            
        scraper.save_to_cache(matches, 'hockey', 'KHL')
        
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
