"""
Скрипт для обучения RL-агента на исторических данных NHL.

Загружает данные из кэша и обучает DQN-агента для meta-стратегии ставок.
"""

import json
import os
import logging
from typing import List, Dict
from datetime import datetime

from src.rl_agent import RLBettingAgent, prepare_training_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_nhl_historical_data() -> List[Dict]:
    """Загрузка исторических данных NHL из кэша"""
    all_matches = []
    cache_dir = 'data/cache'
    
    # Загружаем все сезоны
    for filename in sorted(os.listdir(cache_dir)):
        if filename.startswith('season_') and filename.endswith('.json'):
            filepath = os.path.join(cache_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    season_data = json.load(f)
                    
                # Преобразуем в нужный формат
                for match in season_data:
                    if isinstance(match, dict):
                        processed = {
                            'date': match.get('gameDate', match.get('date', '')),
                            'home_team': match.get('homeTeam', {}).get('name', '') if isinstance(match.get('homeTeam'), dict) else match.get('home_team', ''),
                            'away_team': match.get('awayTeam', {}).get('name', '') if isinstance(match.get('awayTeam'), dict) else match.get('away_team', ''),
                            'home_score': match.get('homeTeam', {}).get('score', 0) if isinstance(match.get('homeTeam'), dict) else match.get('home_score', 0),
                            'away_score': match.get('awayTeam', {}).get('score', 0) if isinstance(match.get('awayTeam'), dict) else match.get('away_score', 0),
                            'home_odds': match.get('home_odds', 2.0),
                            'away_odds': match.get('away_odds', 2.0),
                            'home_streak': match.get('home_streak', 0),
                            'away_streak': match.get('away_streak', 0),
                        }
                        all_matches.append(processed)
                        
                logger.info(f"Loaded {len(season_data)} matches from {filename}")
            except Exception as e:
                logger.error(f"Error loading {filename}: {e}")
    
    logger.info(f"Total NHL matches loaded: {len(all_matches)}")
    return all_matches


def load_european_leagues_data() -> List[Dict]:
    """Загрузка данных европейских лиг"""
    all_matches = []
    leagues_dir = 'data/cache/leagues'
    
    if not os.path.exists(leagues_dir):
        return all_matches
    
    league_names = {
        '16': 'KHL',
        '19': 'SHL', 
        '35': 'Liiga',
        '47': 'DEL'
    }
    
    for filename in sorted(os.listdir(leagues_dir)):
        if filename.startswith('games_') and filename.endswith('.json'):
            filepath = os.path.join(leagues_dir, filename)
            try:
                # Извлекаем ID лиги
                parts = filename.replace('games_', '').replace('.json', '').split('_')
                league_id = parts[0]
                league_name = league_names.get(league_id, 'Unknown')
                
                with open(filepath, 'r') as f:
                    games = json.load(f)
                
                for match in games:
                    if isinstance(match, dict):
                        # Формат API-Sports
                        home_team = match.get('teams', {}).get('home', {})
                        away_team = match.get('teams', {}).get('away', {})
                        scores = match.get('scores', {})
                        
                        processed = {
                            'date': match.get('date', ''),
                            'league': league_name,
                            'home_team': home_team.get('name', ''),
                            'away_team': away_team.get('name', ''),
                            'home_score': scores.get('home', 0) or 0,
                            'away_score': scores.get('away', 0) or 0,
                            'home_odds': 2.0,  # API-Sports не включает odds в основной запрос
                            'away_odds': 2.0,
                            'home_streak': 0,
                            'away_streak': 0,
                        }
                        all_matches.append(processed)
                
                logger.info(f"Loaded {len(games)} {league_name} matches from {filename}")
            except Exception as e:
                logger.error(f"Error loading {filename}: {e}")
    
    logger.info(f"Total European league matches loaded: {len(all_matches)}")
    return all_matches


def add_synthetic_features(matches: List[Dict]) -> List[Dict]:
    """
    Добавление синтетических признаков для обучения.
    
    В реальном pipeline эти признаки генерируются моделью RF/LSTM.
    Здесь мы симулируем их для обучения RL.
    """
    import random
    
    enhanced = []
    team_streaks = {}  # отслеживаем серии команд
    
    # Сортируем по дате
    sorted_matches = sorted(matches, key=lambda x: x.get('date', ''))
    
    for match in sorted_matches:
        home_team = match.get('home_team', '')
        away_team = match.get('away_team', '')
        home_score = match.get('home_score', 0) or 0
        away_score = match.get('away_score', 0) or 0
        
        # Получаем текущие серии
        home_streak = team_streaks.get(home_team, 0)
        away_streak = team_streaks.get(away_team, 0)
        
        # Симуляция коэффициентов на основе серий
        base_home_odds = 2.0
        base_away_odds = 2.0
        
        # Корректировка на основе серий (более длинная победная серия = меньший коэффициент)
        home_odds = max(1.3, base_home_odds - home_streak * 0.1 + away_streak * 0.1)
        away_odds = max(1.3, base_away_odds - away_streak * 0.1 + home_streak * 0.1)
        
        # Симуляция уверенности модели
        streak_diff = home_streak - away_streak
        base_confidence = 0.5 + abs(streak_diff) * 0.05
        model_confidence = min(0.9, max(0.3, base_confidence + random.uniform(-0.1, 0.1)))
        
        # Предсказание модели (на основе серий + случайность)
        home_advantage = 0.03  # домашнее преимущество
        predicted_home_prob = 0.5 + streak_diff * 0.05 + home_advantage + random.uniform(-0.1, 0.1)
        predicted_home_prob = min(0.8, max(0.2, predicted_home_prob))
        
        # Предсказываем победу той команды, у которой выше вероятность
        predict_home = predicted_home_prob > 0.5
        
        # Фактический результат
        if home_score > 0 or away_score > 0:  # есть результат
            home_won = home_score > away_score
            actual_win = (predict_home and home_won) or (not predict_home and not home_won)
            
            # Обновляем серии
            if home_won:
                team_streaks[home_team] = max(0, team_streaks.get(home_team, 0)) + 1
                team_streaks[away_team] = min(0, team_streaks.get(away_team, 0)) - 1
            else:
                team_streaks[away_team] = max(0, team_streaks.get(away_team, 0)) + 1
                team_streaks[home_team] = min(0, team_streaks.get(home_team, 0)) - 1
        else:
            actual_win = random.choice([True, False])
        
        enhanced.append({
            'date': match.get('date', ''),
            'home_team': home_team,
            'away_team': away_team,
            'model_confidence': model_confidence,
            'predicted_probability': predicted_home_prob if predict_home else (1 - predicted_home_prob),
            'odds': home_odds if predict_home else away_odds,
            'home_series': home_streak,
            'away_series': away_streak,
            'h2h_advantage': 0.0,  # neutral when no real H2H data available
            'actual_win': actual_win
        })
    
    return enhanced


def train_rl_agent(episodes: int = 100, save_path: str = 'models/rl_agent.pth') -> Dict:
    """
    Основная функция обучения RL-агента.
    
    Загружает данные, добавляет признаки, обучает агента.
    """
    logger.info("=" * 50)
    logger.info("Starting RL Agent Training")
    logger.info("=" * 50)
    
    # Загружаем данные
    nhl_matches = load_nhl_historical_data()
    euro_matches = load_european_leagues_data()
    
    all_matches = nhl_matches + euro_matches
    logger.info(f"Total matches: {len(all_matches)}")
    
    if len(all_matches) < 100:
        logger.error("Not enough data for training!")
        return {'error': 'Insufficient data'}
    
    # Добавляем признаки
    logger.info("Adding synthetic features...")
    training_data = add_synthetic_features(all_matches)
    
    # Фильтруем только матчи с результатами
    training_data = [m for m in training_data if m.get('actual_win') is not None]
    logger.info(f"Training samples with results: {len(training_data)}")
    
    # Создаём и обучаем агента
    agent = RLBettingAgent(
        epsilon_start=1.0,
        epsilon_end=0.05,
        epsilon_decay=0.995,
        batch_size=64,
        learning_rate=0.0005
    )
    
    logger.info(f"Training for {episodes} episodes...")
    results = agent.train_on_history(training_data, episodes=episodes)
    
    # Сохраняем
    agent.save(save_path)
    
    results['training_samples'] = len(training_data)
    results['timestamp'] = datetime.now().isoformat()
    
    logger.info("=" * 50)
    logger.info(f"Training Complete!")
    logger.info(f"Final ROI: {results['final_roi']:.2f}%")
    logger.info(f"Final Win Rate: {results['final_win_rate']:.2%}")
    logger.info(f"Best ROI achieved: {results['best_roi']:.2f}%")
    logger.info("=" * 50)
    
    return results


if __name__ == '__main__':
    train_rl_agent(episodes=50)
