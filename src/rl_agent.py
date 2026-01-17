"""
Reinforcement Learning Agent for Betting Meta-Strategy

Гибридный подход:
1. RF + LSTM генерируют прогноз (вероятность, confidence)
2. RL-агент решает: принять эту ставку или пропустить

State Space (8 features):
- model_confidence (0-1): уверенность модели в прогнозе
- predicted_probability (0-1): вероятность исхода
- odds_value (1.5-3.0): коэффициент ставки
- home_series (-5 to +5): серия домашней команды
- away_series (-5 to +5): серия гостевой команды
- h2h_advantage (-1 to +1): преимущество в личных встречах
- bankroll_ratio (0-2): текущий банкролл / начальный
- recent_winrate (0-1): процент побед за последние 10 ставок

Action Space:
- 0: SKIP (пропустить ставку)
- 1: BET (сделать ставку)

Reward:
- BET + WIN: (odds - 1) * stake
- BET + LOSE: -stake
- SKIP: 0 (небольшой штраф за бездействие при хорошем прогнозе)
"""

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque
import random
import json
import os
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Experience:
    """Опыт для replay buffer"""
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


class ReplayBuffer:
    """Experience Replay Buffer для стабильного обучения"""
    
    def __init__(self, capacity: int = 10000):
        self.buffer = deque(maxlen=capacity)
    
    def push(self, experience: Experience):
        self.buffer.append(experience)
    
    def sample(self, batch_size: int) -> List[Experience]:
        return random.sample(self.buffer, min(batch_size, len(self.buffer)))
    
    def __len__(self):
        return len(self.buffer)


class DQNetwork(nn.Module):
    """Deep Q-Network для оценки действий"""
    
    def __init__(self, state_dim: int = 8, action_dim: int = 2, hidden_dim: int = 64):
        super(DQNetwork, self).__init__()
        
        self.network = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim, action_dim)
        )
    
    def forward(self, x):
        return self.network(x)


class BettingEnvironment:
    """
    Симулятор среды для обучения RL-агента на исторических данных.
    
    Каждый эпизод = прохождение через сезон матчей.
    """
    
    def __init__(self, matches: List[Dict], initial_bankroll: float = 1000.0):
        self.matches = matches
        self.initial_bankroll = initial_bankroll
        self.reset()
    
    def reset(self) -> np.ndarray:
        """Сброс среды в начальное состояние"""
        self.current_idx = 0
        self.bankroll = self.initial_bankroll
        self.recent_results = deque(maxlen=10)  # последние 10 результатов
        self.total_bets = 0
        self.wins = 0
        self.losses = 0
        
        return self._get_state()
    
    def _get_state(self) -> np.ndarray:
        """Получить текущее состояние для агента"""
        if self.current_idx >= len(self.matches):
            return np.zeros(8)
        
        match = self.matches[self.current_idx]
        
        # Извлекаем признаки из матча
        state = np.array([
            match.get('model_confidence', 0.5),
            match.get('predicted_probability', 0.5),
            min(match.get('odds', 2.0), 5.0) / 5.0,  # нормализация
            (match.get('home_series', 0) + 5) / 10.0,  # -5..+5 -> 0..1
            (match.get('away_series', 0) + 5) / 10.0,
            (match.get('h2h_advantage', 0) + 1) / 2.0,  # -1..+1 -> 0..1
            min(self.bankroll / self.initial_bankroll, 2.0) / 2.0,
            sum(self.recent_results) / max(len(self.recent_results), 1) if self.recent_results else 0.5
        ], dtype=np.float32)
        
        return state
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict]:
        """
        Выполнить действие и получить награду.
        
        action: 0 = SKIP, 1 = BET
        """
        if self.current_idx >= len(self.matches):
            return self._get_state(), 0.0, True, {}
        
        match = self.matches[self.current_idx]
        actual_result = match.get('actual_win', False)  # True если прогноз был верным
        odds = match.get('odds', 2.0)
        stake = min(self.bankroll * 0.05, 50.0)  # 5% банкролла, макс 50
        
        reward = 0.0
        info = {'action': 'skip', 'result': None}
        
        if action == 1:  # BET
            self.total_bets += 1
            info['action'] = 'bet'
            info['stake'] = stake
            
            if actual_result:  # WIN
                profit = stake * (odds - 1)
                self.bankroll += profit
                reward = profit / self.initial_bankroll  # нормализованная награда
                self.wins += 1
                self.recent_results.append(1)
                info['result'] = 'win'
                info['profit'] = profit
            else:  # LOSE
                self.bankroll -= stake
                reward = -stake / self.initial_bankroll
                self.losses += 1
                self.recent_results.append(0)
                info['result'] = 'lose'
                info['profit'] = -stake
        else:  # SKIP
            # Небольшой штраф за пропуск хороших возможностей
            if match.get('model_confidence', 0) > 0.7 and actual_result:
                reward = -0.01  # упущенная выгода
        
        self.current_idx += 1
        done = self.current_idx >= len(self.matches) or self.bankroll <= 0
        
        next_state = self._get_state()
        
        return next_state, reward, done, info
    
    def get_episode_stats(self) -> Dict:
        """Статистика за эпизод"""
        return {
            'total_bets': self.total_bets,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': self.wins / max(self.total_bets, 1),
            'final_bankroll': self.bankroll,
            'roi': (self.bankroll - self.initial_bankroll) / self.initial_bankroll * 100
        }


class RLBettingAgent:
    """
    DQN Agent для meta-стратегии ставок.
    
    Решает принимать или пропускать ставку на основе:
    - Уверенности модели
    - Исторической эффективности
    - Текущего состояния банкролла
    """
    
    def __init__(
        self,
        state_dim: int = 8,
        action_dim: int = 2,
        learning_rate: float = 0.001,
        gamma: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.1,
        epsilon_decay: float = 0.995,
        batch_size: int = 64,
        target_update: int = 100
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.target_update = target_update
        
        # Сети
        self.policy_net = DQNetwork(state_dim, action_dim)
        self.target_net = DQNetwork(state_dim, action_dim)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()
        
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=learning_rate)
        self.memory = ReplayBuffer(capacity=50000)
        
        self.steps_done = 0
        self.training_history = []
    
    def select_action(self, state: np.ndarray, training: bool = True) -> int:
        """Выбор действия с epsilon-greedy стратегией"""
        if training and random.random() < self.epsilon:
            return random.randint(0, self.action_dim - 1)
        
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            q_values = self.policy_net(state_tensor)
            return q_values.argmax(dim=1).item()
    
    def get_recommendation(self, state: np.ndarray) -> Dict:
        """Получить рекомендацию для production использования"""
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            q_values = self.policy_net(state_tensor)
            
            action = q_values.argmax(dim=1).item()
            q_skip = q_values[0, 0].item()
            q_bet = q_values[0, 1].item()
            
            # Confidence как разница между Q-значениями
            confidence = abs(q_bet - q_skip) / (abs(q_bet) + abs(q_skip) + 1e-6)
            
            # Генерируем комментарий на основе состояния
            comment = self._generate_comment(state, action, confidence)
            
            return {
                'action': 'BET' if action == 1 else 'SKIP',
                'action_id': action,
                'confidence': min(confidence, 1.0),
                'q_bet': q_bet,
                'q_skip': q_skip,
                'recommendation': 'Рекомендуется ставка' if action == 1 else 'Рекомендуется пропустить',
                'comment': comment
            }
    
    def _generate_comment(self, state: np.ndarray, action: int, confidence: float) -> str:
        """Генерация текстового комментария на основе анализа состояния"""
        model_conf = state[0]  # model_confidence
        odds_norm = state[2]   # normalized odds
        home_series = (state[3] * 10) - 5  # denormalize
        away_series = (state[4] * 10) - 5
        bankroll = state[6] * 2  # denormalize
        recent_wr = state[7]
        
        reasons = []
        
        if action == 1:  # BET
            if model_conf > 0.7:
                reasons.append("высокая уверенность модели")
            if odds_norm > 0.4:  # odds > 2.0
                reasons.append("привлекательный коэффициент")
            if home_series > 2 or away_series > 2:
                reasons.append("сильная серия команды")
            if recent_wr > 0.6:
                reasons.append("хорошая недавняя статистика")
            if bankroll > 1.0:
                reasons.append("банкролл в плюсе")
            
            if not reasons:
                reasons.append("совокупность факторов")
            
            return f"Ставка рекомендуется: {', '.join(reasons)}"
        else:  # SKIP
            if model_conf < 0.5:
                reasons.append("низкая уверенность модели")
            if odds_norm < 0.3:  # odds < 1.5
                reasons.append("низкий коэффициент")
            if recent_wr < 0.4:
                reasons.append("плохая недавняя статистика")
            if bankroll < 0.7:
                reasons.append("банкролл под давлением")
            if abs(home_series) < 2 and abs(away_series) < 2:
                reasons.append("неопределённая ситуация")
            
            if not reasons:
                reasons.append("риск превышает потенциальную выгоду")
            
            return f"Пропустить: {', '.join(reasons)}"
    
    def train_step(self) -> Optional[float]:
        """Один шаг обучения"""
        if len(self.memory) < self.batch_size:
            return None
        
        batch = self.memory.sample(self.batch_size)
        
        states = torch.FloatTensor(np.array([e.state for e in batch]))
        actions = torch.LongTensor([e.action for e in batch])
        rewards = torch.FloatTensor([e.reward for e in batch])
        next_states = torch.FloatTensor(np.array([e.next_state for e in batch]))
        dones = torch.FloatTensor([e.done for e in batch])
        
        # Текущие Q-значения
        current_q = self.policy_net(states).gather(1, actions.unsqueeze(1))
        
        # Целевые Q-значения (Double DQN)
        with torch.no_grad():
            next_actions = self.policy_net(next_states).argmax(dim=1)
            next_q = self.target_net(next_states).gather(1, next_actions.unsqueeze(1)).squeeze()
            target_q = rewards + self.gamma * next_q * (1 - dones)
        
        # Loss и оптимизация
        loss = nn.SmoothL1Loss()(current_q.squeeze(), target_q)
        
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.policy_net.parameters(), 1.0)
        self.optimizer.step()
        
        # Обновление epsilon
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        
        # Обновление target network
        self.steps_done += 1
        if self.steps_done % self.target_update == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())
        
        return loss.item()
    
    def train_on_history(self, matches: List[Dict], episodes: int = 100) -> Dict:
        """
        Обучение агента на исторических данных.
        
        matches: список матчей с признаками и результатами
        episodes: количество проходов через данные
        """
        env = BettingEnvironment(matches)
        
        all_rewards = []
        all_rois = []
        
        for episode in range(episodes):
            state = env.reset()
            episode_reward = 0
            
            while True:
                action = self.select_action(state, training=True)
                next_state, reward, done, info = env.step(action)
                
                self.memory.push(Experience(state, action, reward, next_state, done))
                
                loss = self.train_step()
                
                episode_reward += reward
                state = next_state
                
                if done:
                    break
            
            stats = env.get_episode_stats()
            all_rewards.append(episode_reward)
            all_rois.append(stats['roi'])
            
            self.training_history.append({
                'episode': episode,
                'reward': episode_reward,
                'roi': stats['roi'],
                'win_rate': stats['win_rate'],
                'total_bets': stats['total_bets'],
                'epsilon': self.epsilon
            })
            
            if (episode + 1) % 10 == 0:
                avg_roi = np.mean(all_rois[-10:])
                avg_wr = np.mean([h['win_rate'] for h in self.training_history[-10:]])
                logger.info(f"Episode {episode + 1}/{episodes}: "
                           f"Avg ROI: {avg_roi:.2f}%, Avg WinRate: {avg_wr:.2%}, "
                           f"Epsilon: {self.epsilon:.3f}")
        
        return {
            'final_roi': np.mean(all_rois[-10:]),
            'final_win_rate': np.mean([h['win_rate'] for h in self.training_history[-10:]]),
            'best_roi': max(all_rois),
            'episodes_trained': episodes,
            'total_experiences': len(self.memory)
        }
    
    def save(self, path: str = 'models/rl_agent.pth'):
        """Сохранить модель"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save({
            'policy_net': self.policy_net.state_dict(),
            'target_net': self.target_net.state_dict(),
            'optimizer': self.optimizer.state_dict(),
            'epsilon': self.epsilon,
            'steps_done': self.steps_done,
            'training_history': self.training_history[-100:]  # последние 100 эпизодов
        }, path)
        logger.info(f"Model saved to {path}")
    
    def load(self, path: str = 'models/rl_agent.pth') -> bool:
        """Загрузить модель"""
        if not os.path.exists(path):
            logger.warning(f"Model file not found: {path}")
            return False
        
        checkpoint = torch.load(path, map_location='cpu')
        self.policy_net.load_state_dict(checkpoint['policy_net'])
        self.target_net.load_state_dict(checkpoint['target_net'])
        self.optimizer.load_state_dict(checkpoint['optimizer'])
        self.epsilon = checkpoint.get('epsilon', 0.1)
        self.steps_done = checkpoint.get('steps_done', 0)
        self.training_history = checkpoint.get('training_history', [])
        
        logger.info(f"Model loaded from {path}")
        return True


def prepare_training_data(historical_matches: List[Dict]) -> List[Dict]:
    """
    Подготовка исторических данных для обучения RL.
    
    Преобразует сырые данные матчей в формат для BettingEnvironment.
    """
    training_data = []
    
    for match in historical_matches:
        # Определяем результат
        home_score = match.get('home_score', 0)
        away_score = match.get('away_score', 0)
        
        # Простая логика: предсказываем победу фаворита (более низкий коэффициент)
        home_odds = match.get('home_odds', 2.0)
        away_odds = match.get('away_odds', 2.0)
        
        # Определяем, кого бы предсказала модель (фаворита)
        if home_odds < away_odds:
            predicted_home = True
            odds = home_odds
        else:
            predicted_home = False
            odds = away_odds
        
        # Верен ли был бы прогноз
        actual_win = (predicted_home and home_score > away_score) or \
                     (not predicted_home and away_score > home_score)
        
        # Синтетические признаки (в реальности берутся из pattern_engine)
        training_data.append({
            'model_confidence': random.uniform(0.4, 0.9),  # TODO: использовать реальную модель
            'predicted_probability': 1 / odds if odds > 0 else 0.5,
            'odds': odds,
            'home_series': match.get('home_streak', 0),
            'away_series': match.get('away_streak', 0),
            'h2h_advantage': random.uniform(-0.5, 0.5),
            'actual_win': actual_win,
            'date': match.get('date', ''),
            'home_team': match.get('home_team', ''),
            'away_team': match.get('away_team', '')
        })
    
    return training_data


# Singleton для использования в приложении
_rl_agent: Optional[RLBettingAgent] = None


def get_rl_agent() -> RLBettingAgent:
    """Получить singleton экземпляр RL-агента"""
    global _rl_agent
    if _rl_agent is None:
        _rl_agent = RLBettingAgent()
        _rl_agent.load()  # попытка загрузить сохранённую модель
    return _rl_agent


def get_rl_recommendation(
    model_confidence: float,
    predicted_probability: float,
    odds: float,
    home_series: int = 0,
    away_series: int = 0,
    h2h_advantage: float = 0,
    bankroll_ratio: float = 1.0,
    recent_winrate: float = 0.5
) -> Dict:
    """
    Получить рекомендацию RL-агента для конкретного прогноза.
    
    Используется в prediction pipeline после генерации прогноза.
    """
    agent = get_rl_agent()
    
    state = np.array([
        model_confidence,
        predicted_probability,
        min(odds, 5.0) / 5.0,
        (home_series + 5) / 10.0,
        (away_series + 5) / 10.0,
        (h2h_advantage + 1) / 2.0,
        min(bankroll_ratio, 2.0) / 2.0,
        recent_winrate
    ], dtype=np.float32)
    
    return agent.get_recommendation(state)
