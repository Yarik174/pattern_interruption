"""
Скрипт для массового скрейпинга всех лиг с flashscore.com
Запуск: python scripts/scrape_all_leagues.py [sport] [--with-odds]
"""
import asyncio
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.flashscore_scraper import FlashScoreScraper, LEAGUE_URLS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PAGES_PER_LEAGUE = 20


async def scrape_sport(sport: str, with_odds: bool = False):
    """Скрейпить все лиги одного вида спорта"""
    if sport not in LEAGUE_URLS:
        logger.error(f"Unknown sport: {sport}")
        return
        
    leagues = LEAGUE_URLS[sport]
    logger.info(f"Starting scrape for {sport}: {list(leagues.keys())}")
    
    scraper = FlashScoreScraper()
    await scraper.init_browser()
    
    try:
        for league_name in leagues:
            logger.info(f"\n{'='*50}")
            logger.info(f"Scraping {sport}/{league_name}")
            logger.info(f"{'='*50}")
            
            try:
                matches = await scraper.scrape_league_history(
                    sport=sport,
                    league=league_name,
                    num_pages=PAGES_PER_LEAGUE,
                    with_odds=with_odds
                )
                
                if matches:
                    scraper.save_to_cache(matches, sport, league_name)
                    logger.info(f"Saved {len(matches)} matches for {sport}/{league_name}")
                else:
                    logger.warning(f"No matches found for {sport}/{league_name}")
                    
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error scraping {sport}/{league_name}: {e}")
                continue
                
    finally:
        await scraper.close()


async def scrape_all(with_odds: bool = False):
    """Скрейпить все виды спорта"""
    sports = ['hockey', 'football', 'basketball', 'volleyball']
    
    for sport in sports:
        await scrape_sport(sport, with_odds)
        logger.info(f"\nCompleted {sport}, waiting before next sport...")
        await asyncio.sleep(10)


async def quick_test():
    """Быстрый тест - 1 страница для каждой лиги без коэффов"""
    logger.info("Quick test mode - 1 page per league, no odds")
    
    scraper = FlashScoreScraper()
    await scraper.init_browser()
    
    results = {}
    
    try:
        for sport, leagues in LEAGUE_URLS.items():
            results[sport] = {}
            for league_name in leagues:
                try:
                    matches = await scraper.scrape_league_history(
                        sport=sport,
                        league=league_name,
                        num_pages=1,
                        with_odds=False
                    )
                    results[sport][league_name] = len(matches)
                    logger.info(f"{sport}/{league_name}: {len(matches)} matches")
                    
                    if matches:
                        scraper.save_to_cache(matches, sport, f"{league_name}_test")
                        
                    await asyncio.sleep(3)
                    
                except Exception as e:
                    logger.error(f"Error: {sport}/{league_name}: {e}")
                    results[sport][league_name] = 0
                    
    finally:
        await scraper.close()
        
    logger.info("\n\nSUMMARY:")
    total = 0
    for sport, leagues in results.items():
        sport_total = sum(leagues.values())
        total += sport_total
        logger.info(f"{sport}: {sport_total} matches")
        for league, count in leagues.items():
            logger.info(f"  {league}: {count}")
    logger.info(f"\nTOTAL: {total} matches")


def main():
    parser = argparse.ArgumentParser(description='Scrape flashscore.com for match data')
    parser.add_argument('sport', nargs='?', default='all', 
                       choices=['all', 'hockey', 'football', 'basketball', 'volleyball', 'test'],
                       help='Sport to scrape (default: all)')
    parser.add_argument('--with-odds', action='store_true',
                       help='Also fetch betting odds (much slower)')
    parser.add_argument('--pages', type=int, default=20,
                       help='Number of pages per league (default: 20, ~40 matches/page)')
    
    args = parser.parse_args()
    
    global PAGES_PER_LEAGUE
    PAGES_PER_LEAGUE = args.pages
    
    if args.sport == 'test':
        asyncio.run(quick_test())
    elif args.sport == 'all':
        asyncio.run(scrape_all(args.with_odds))
    else:
        asyncio.run(scrape_sport(args.sport, args.with_odds))


if __name__ == "__main__":
    main()
