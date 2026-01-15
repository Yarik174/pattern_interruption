"""
Sequence Model for Hockey Match Prediction
LSTM-based model predicting:
1. Regulation result (home/away/draw) - result in regulation time
2. Final result (home/away) - including overtime
3. Goals per period (regression for 3 periods)

Uses last N matches of each team as input sequence.
"""

import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
import joblib
import os
import json
import logging
import requests
import time

logger = logging.getLogger(__name__)


class HockeySequenceDataset(torch.utils.data.Dataset):
    """Dataset for hockey match sequences with regulation and final labels"""
    
    def __init__(self, home_sequences, away_sequences, labels_regulation, labels_final, labels_periods):
        self.home_sequences = torch.tensor(home_sequences, dtype=torch.float32)
        self.away_sequences = torch.tensor(away_sequences, dtype=torch.float32)
        self.labels_regulation = torch.tensor(labels_regulation, dtype=torch.long)
        self.labels_final = torch.tensor(labels_final, dtype=torch.long)
        self.labels_periods = torch.tensor(labels_periods, dtype=torch.float32)
    
    def __len__(self):
        return len(self.labels_final)
    
    def __getitem__(self, idx):
        return (
            self.home_sequences[idx],
            self.away_sequences[idx],
            self.labels_regulation[idx],
            self.labels_final[idx],
            self.labels_periods[idx]
        )


class HockeyLSTM(nn.Module):
    """
    LSTM model for hockey match prediction
    
    Architecture:
    - Two parallel LSTMs for home and away team sequences
    - Concatenated hidden states
    - Three output heads:
      - fc_regulation: 3 classes (Home/Away/Draw) for regulation time
      - fc_final: 3 classes (Home/Away/Draw) for final result (Draw ~0%)
      - fc_periods: regression for period goals
    """
    
    def __init__(self, input_dim, hidden_dim=64, num_layers=2, dropout=0.3):
        super(HockeyLSTM, self).__init__()
        
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        
        self.home_lstm = nn.LSTM(
            input_dim, hidden_dim, num_layers, 
            batch_first=True, dropout=dropout if num_layers > 1 else 0
        )
        
        self.away_lstm = nn.LSTM(
            input_dim, hidden_dim, num_layers,
            batch_first=True, dropout=dropout if num_layers > 1 else 0
        )
        
        combined_dim = hidden_dim * 2
        
        self.fc_shared = nn.Sequential(
            nn.Linear(combined_dim, 128),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(dropout)
        )
        
        self.fc_regulation = nn.Linear(64, 3)
        
        self.fc_final = nn.Linear(64, 3)
        
        self.fc_periods = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 6)
        )
    
    def forward(self, home_seq, away_seq):
        home_out, _ = self.home_lstm(home_seq)
        away_out, _ = self.away_lstm(away_seq)
        
        home_last = home_out[:, -1, :]
        away_last = away_out[:, -1, :]
        
        combined = torch.cat([home_last, away_last], dim=1)
        
        shared = self.fc_shared(combined)
        
        regulation_logits = self.fc_regulation(shared)
        final_logits = self.fc_final(shared)
        period_goals = self.fc_periods(shared)
        
        return regulation_logits, final_logits, period_goals
    
    def predict_match(self, home_seq, away_seq):
        """Direct prediction without trainer wrapper"""
        self.eval()
        
        with torch.no_grad():
            if not isinstance(home_seq, torch.Tensor):
                home_seq = torch.tensor(home_seq, dtype=torch.float32)
            if not isinstance(away_seq, torch.Tensor):
                away_seq = torch.tensor(away_seq, dtype=torch.float32)
            
            if home_seq.dim() == 2:
                home_seq = home_seq.unsqueeze(0)
                away_seq = away_seq.unsqueeze(0)
            
            regulation_logits, final_logits, period_pred = self.forward(home_seq, away_seq)
            
            regulation_probs = torch.softmax(regulation_logits, dim=1).numpy()[0]
            final_probs = torch.softmax(final_logits, dim=1).numpy()[0]
            period_pred = period_pred.numpy()[0]
        
        final_home = final_probs[0] + final_probs[2] * 0.5
        final_away = final_probs[1] + final_probs[2] * 0.5
        
        return {
            'regulation_probs': {
                'home': float(regulation_probs[0]),
                'away': float(regulation_probs[1]),
                'draw': float(regulation_probs[2])
            },
            'final_probs': {
                'home': float(final_home),
                'away': float(final_away)
            },
            'winner_probs': {
                'home': float(final_probs[0]),
                'away': float(final_probs[1]),
                'draw': float(final_probs[2])
            },
            'period_goals': {
                'home': [float(round(max(0, float(g)), 1)) for g in period_pred[:3]],
                'away': [float(round(max(0, float(g)), 1)) for g in period_pred[3:]]
            },
            'predicted_regulation': ['home', 'away', 'draw'][int(np.argmax(regulation_probs))],
            'predicted_final': 'home' if final_home > final_away else 'away',
            'predicted_winner': ['home', 'away', 'draw'][int(np.argmax(final_probs))],
            'predicted_total': float(round(sum(max(0, float(g)) for g in period_pred), 1))
        }


class SequenceDataPreparer:
    """Prepares sequence data for LSTM model"""
    
    DEFAULT_HOME_ODDS = 1.9
    DEFAULT_AWAY_ODDS = 1.9
    DEFAULT_IMPLIED_PROB = 0.52
    
    def __init__(self, sequence_length=10, cache_dir='data/cache', with_odds=False):
        self.sequence_length = sequence_length
        self.cache_dir = cache_dir
        self.scaler = StandardScaler()
        self.feature_columns = []
        self.with_odds = with_odds
    
    def merge_with_odds(self, df, odds_df):
        """Merge match data with odds data"""
        if odds_df is None or odds_df.empty:
            logger.warning("No odds data provided, using defaults")
            df['home_odds'] = self.DEFAULT_HOME_ODDS
            df['away_odds'] = self.DEFAULT_AWAY_ODDS
            df['implied_prob'] = self.DEFAULT_IMPLIED_PROB
            return df
        
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        odds_df = odds_df.copy()
        odds_df['date'] = pd.to_datetime(odds_df['date'])
        
        df['home_team_upper'] = df['home_team'].str.upper()
        df['away_team_upper'] = df['away_team'].str.upper()
        odds_df['home_team_upper'] = odds_df['home_team'].str.upper()
        odds_df['away_team_upper'] = odds_df['away_team'].str.upper()
        
        merged = pd.merge(
            df,
            odds_df[['date', 'home_team_upper', 'away_team_upper', 'home_odds', 'away_odds']],
            on=['date', 'home_team_upper', 'away_team_upper'],
            how='left'
        )
        
        merged['home_odds'] = merged['home_odds'].fillna(self.DEFAULT_HOME_ODDS)
        merged['away_odds'] = merged['away_odds'].fillna(self.DEFAULT_AWAY_ODDS)
        merged['implied_prob'] = 1 / merged['home_odds']
        merged['implied_prob'] = merged['implied_prob'].fillna(self.DEFAULT_IMPLIED_PROB)
        
        merged = merged.drop(columns=['home_team_upper', 'away_team_upper'])
        
        matched = merged['home_odds'] != self.DEFAULT_HOME_ODDS
        logger.info(f"Matched {matched.sum()} / {len(merged)} games with odds ({matched.mean()*100:.1f}%)")
        
        return merged
        
    def load_period_data(self, game_ids, max_games=None):
        """Load period scoring data for games"""
        period_cache_path = os.path.join(self.cache_dir, 'period_data.json')
        
        period_data = {}
        if os.path.exists(period_cache_path):
            with open(period_cache_path, 'r') as f:
                period_data = json.load(f)
            logger.info(f"Loaded {len(period_data)} games with period data from cache")
        
        games_to_load = game_ids[:max_games] if max_games else game_ids
        games_to_fetch = [g for g in games_to_load if str(g) not in period_data]
        
        if not games_to_fetch:
            logger.info(f"All {len(games_to_load)} games already in cache")
            return period_data
        
        logger.info(f"Fetching period data for {len(games_to_fetch)} new games...")
        
        for i, game_id in enumerate(games_to_fetch):
            if i % 100 == 0:
                logger.info(f"  Progress: {i}/{len(games_to_fetch)}")
                if i > 0:
                    with open(period_cache_path, 'w') as f:
                        json.dump(period_data, f)
                    logger.info(f"  Saved checkpoint: {len(period_data)} games")
            
            try:
                url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/landing"
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    scoring = data.get('summary', {}).get('scoring', [])
                    
                    home_periods = [0, 0, 0]
                    away_periods = [0, 0, 0]
                    
                    for period_info in scoring:
                        period_num = period_info.get('periodDescriptor', {}).get('number', 0)
                        if period_num > 0 and period_num <= 3:
                            for goal in period_info.get('goals', []):
                                is_home = goal.get('isHome', False)
                                if is_home:
                                    home_periods[period_num - 1] += 1
                                else:
                                    away_periods[period_num - 1] += 1
                    
                    period_data[str(game_id)] = {
                        'home_p1': home_periods[0],
                        'home_p2': home_periods[1],
                        'home_p3': home_periods[2],
                        'away_p1': away_periods[0],
                        'away_p2': away_periods[1],
                        'away_p3': away_periods[2]
                    }
                
                time.sleep(0.05)
                
            except Exception as e:
                logger.warning(f"Error loading game {game_id}: {e}")
                continue
        
        with open(period_cache_path, 'w') as f:
            json.dump(period_data, f)
        
        logger.info(f"Saved period data for {len(period_data)} games to cache")
        return period_data
    
    def build_team_history(self, df):
        """Build match history for each team with regulation features"""
        team_history = {}
        
        df_sorted = df.sort_values('date').reset_index(drop=True)
        
        for _, row in df_sorted.iterrows():
            home = row['home_team']
            away = row['away_team']
            overtime = row.get('overtime', 0)
            
            if overtime == 1:
                regulation_result = 2
            else:
                if row['home_score'] > row['away_score']:
                    regulation_result = 0
                else:
                    regulation_result = 1
            
            home_won_final = 1 if row['home_win'] == 1 else 0
            home_won_regulation = 1 if (regulation_result == 0) else 0
            home_won_overtime = 1 if (home_won_final == 1 and overtime == 1) else 0
            home_draw_regulation = 1 if (regulation_result == 2) else 0
            
            match_features = {
                'goals_scored': row['home_score'],
                'goals_conceded': row['away_score'],
                'won': home_won_final,
                'home_game': 1,
                'overtime': overtime,
                'goal_diff': row['home_score'] - row['away_score'],
                'total_goals': row['home_score'] + row['away_score'],
                'won_regulation': home_won_regulation,
                'won_overtime': home_won_overtime,
                'draw_regulation': home_draw_regulation
            }
            
            if self.with_odds:
                home_odds = row.get('home_odds', self.DEFAULT_HOME_ODDS)
                away_odds = row.get('away_odds', self.DEFAULT_AWAY_ODDS)
                match_features['home_odds'] = home_odds
                match_features['away_odds'] = away_odds
                match_features['implied_prob'] = row.get('implied_prob', self.DEFAULT_IMPLIED_PROB)
                match_features['is_underdog'] = 1 if home_odds > away_odds else 0
                match_features['won_as_underdog'] = 1 if (home_odds > away_odds and home_won_final == 1) else 0
                match_features['odds_diff'] = (home_odds - away_odds) / max(home_odds, away_odds)
            
            if home not in team_history:
                team_history[home] = []
            team_history[home].append(match_features.copy())
            
            away_won_final = 1 if row['home_win'] == 0 else 0
            away_won_regulation = 1 if (regulation_result == 1) else 0
            away_won_overtime = 1 if (away_won_final == 1 and overtime == 1) else 0
            away_draw_regulation = 1 if (regulation_result == 2) else 0
            
            away_features = {
                'goals_scored': row['away_score'],
                'goals_conceded': row['home_score'],
                'won': away_won_final,
                'home_game': 0,
                'overtime': overtime,
                'goal_diff': row['away_score'] - row['home_score'],
                'total_goals': row['home_score'] + row['away_score'],
                'won_regulation': away_won_regulation,
                'won_overtime': away_won_overtime,
                'draw_regulation': away_draw_regulation
            }
            
            if self.with_odds:
                home_odds = row.get('home_odds', self.DEFAULT_HOME_ODDS)
                away_odds = row.get('away_odds', self.DEFAULT_AWAY_ODDS)
                away_features['home_odds'] = home_odds
                away_features['away_odds'] = away_odds
                away_features['implied_prob'] = 1 - row.get('implied_prob', self.DEFAULT_IMPLIED_PROB)
                away_features['is_underdog'] = 1 if away_odds > home_odds else 0
                away_features['won_as_underdog'] = 1 if (away_odds > home_odds and away_won_final == 1) else 0
                away_features['odds_diff'] = (away_odds - home_odds) / max(home_odds, away_odds)
            
            if away not in team_history:
                team_history[away] = []
            team_history[away].append(away_features)
        
        return team_history
    
    def prepare_sequences(self, df, period_data=None):
        """Prepare training sequences from match data"""
        
        if self.feature_columns == []:
            self.feature_columns = [
                'goals_scored', 'goals_conceded', 'won', 
                'home_game', 'overtime', 'goal_diff', 'total_goals',
                'won_regulation', 'won_overtime', 'draw_regulation'
            ]
            if self.with_odds:
                self.feature_columns.extend([
                    'home_odds', 'away_odds', 'implied_prob',
                    'is_underdog', 'won_as_underdog', 'odds_diff'
                ])
        
        team_history = self.build_team_history(df)
        
        df_sorted = df.sort_values('date').reset_index(drop=True)
        
        home_sequences = []
        away_sequences = []
        labels_regulation = []
        labels_final = []
        labels_periods = []
        
        current_match_idx = {team: 0 for team in team_history}
        
        for idx, row in df_sorted.iterrows():
            home = row['home_team']
            away = row['away_team']
            
            home_idx = current_match_idx.get(home, 0)
            away_idx = current_match_idx.get(away, 0)
            
            if home_idx >= self.sequence_length and away_idx >= self.sequence_length:
                home_hist = team_history[home][home_idx - self.sequence_length:home_idx]
                away_hist = team_history[away][away_idx - self.sequence_length:away_idx]
                
                home_seq = [[m[col] for col in self.feature_columns] for m in home_hist]
                away_seq = [[m[col] for col in self.feature_columns] for m in away_hist]
                
                home_sequences.append(home_seq)
                away_sequences.append(away_seq)
                
                overtime = row.get('overtime', 0)
                if overtime == 1:
                    regulation_result = 2
                else:
                    if row['home_score'] > row['away_score']:
                        regulation_result = 0
                    else:
                        regulation_result = 1
                labels_regulation.append(regulation_result)
                
                if row['home_score'] > row['away_score']:
                    final_result = 0
                elif row['home_score'] < row['away_score']:
                    final_result = 1
                else:
                    final_result = 2
                labels_final.append(final_result)
                
                game_id = str(row['game_id'])
                if period_data and game_id in period_data:
                    pd_info = period_data[game_id]
                    periods = [
                        pd_info['home_p1'], pd_info['home_p2'], pd_info['home_p3'],
                        pd_info['away_p1'], pd_info['away_p2'], pd_info['away_p3']
                    ]
                else:
                    periods = [0, 0, 0, 0, 0, 0]
                labels_periods.append(periods)
            
            if home in current_match_idx:
                current_match_idx[home] += 1
            if away in current_match_idx:
                current_match_idx[away] += 1
        
        return (
            np.array(home_sequences),
            np.array(away_sequences),
            np.array(labels_regulation),
            np.array(labels_final),
            np.array(labels_periods)
        )
    
    def normalize_sequences(self, home_seq, away_seq, fit=True):
        """Normalize sequence features"""
        n_samples, seq_len, n_features = home_seq.shape
        
        all_data = np.concatenate([
            home_seq.reshape(-1, n_features),
            away_seq.reshape(-1, n_features)
        ], axis=0)
        
        if fit:
            self.scaler.fit(all_data)
        
        home_normalized = self.scaler.transform(
            home_seq.reshape(-1, n_features)
        ).reshape(n_samples, seq_len, n_features)
        
        away_normalized = self.scaler.transform(
            away_seq.reshape(-1, n_features)
        ).reshape(n_samples, seq_len, n_features)
        
        return home_normalized, away_normalized


class SequenceModelTrainer:
    """Trainer for LSTM model with dual prediction heads"""
    
    def __init__(self, model, device='cpu'):
        self.model = model.to(device)
        self.device = device
        self.history = {
            'train_loss': [], 
            'val_loss': [], 
            'val_acc_regulation': [],
            'val_acc_final': [],
            'val_acc': []
        }
    
    def train(self, train_loader, val_loader, epochs=50, lr=0.001, 
              weight_regulation=1.0, weight_final=1.0, weight_periods=0.5):
        """Train the model"""
        
        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        criterion_regulation = nn.CrossEntropyLoss()
        criterion_final = nn.CrossEntropyLoss()
        criterion_periods = nn.MSELoss()
        
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode='min', patience=5, factor=0.5
        )
        
        best_val_loss = float('inf')
        patience_counter = 0
        best_model_state = None
        
        for epoch in range(epochs):
            self.model.train()
            train_loss = 0.0
            
            for home_seq, away_seq, reg_label, final_label, periods in train_loader:
                home_seq = home_seq.to(self.device)
                away_seq = away_seq.to(self.device)
                reg_label = reg_label.to(self.device)
                final_label = final_label.to(self.device)
                periods = periods.to(self.device)
                
                optimizer.zero_grad()
                
                reg_pred, final_pred, periods_pred = self.model(home_seq, away_seq)
                
                loss_regulation = criterion_regulation(reg_pred, reg_label)
                loss_final = criterion_final(final_pred, final_label)
                loss_periods = criterion_periods(periods_pred, periods)
                loss = weight_regulation * loss_regulation + weight_final * loss_final + weight_periods * loss_periods
                
                loss.backward()
                optimizer.step()
                
                train_loss += loss.item()
            
            train_loss /= len(train_loader)
            self.history['train_loss'].append(train_loss)
            
            val_loss, val_acc_reg, val_acc_final = self.evaluate(val_loader)
            self.history['val_loss'].append(val_loss)
            self.history['val_acc_regulation'].append(val_acc_reg)
            self.history['val_acc_final'].append(val_acc_final)
            self.history['val_acc'].append(val_acc_final)
            
            scheduler.step(val_loss)
            
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                best_model_state = {k: v.clone() for k, v in self.model.state_dict().items()}
            else:
                patience_counter += 1
            
            if (epoch + 1) % 5 == 0:
                logger.info(
                    f"Epoch {epoch+1}/{epochs} - "
                    f"Train Loss: {train_loss:.4f}, "
                    f"Val Loss: {val_loss:.4f}, "
                    f"Reg Acc: {val_acc_reg:.2%}, "
                    f"Final Acc: {val_acc_final:.2%}"
                )
            
            if patience_counter >= 10:
                logger.info(f"Early stopping at epoch {epoch+1}")
                break
        
        if best_model_state is not None:
            self.model.load_state_dict(best_model_state)
            logger.info("Restored best model from checkpoint")
        
        return self.history
    
    def evaluate(self, loader):
        """Evaluate model on validation set"""
        self.model.eval()
        total_loss = 0.0
        correct_reg = 0
        correct_final = 0
        total = 0
        
        criterion_regulation = nn.CrossEntropyLoss()
        criterion_final = nn.CrossEntropyLoss()
        criterion_periods = nn.MSELoss()
        
        with torch.no_grad():
            for home_seq, away_seq, reg_label, final_label, periods in loader:
                home_seq = home_seq.to(self.device)
                away_seq = away_seq.to(self.device)
                reg_label = reg_label.to(self.device)
                final_label = final_label.to(self.device)
                periods = periods.to(self.device)
                
                reg_pred, final_pred, periods_pred = self.model(home_seq, away_seq)
                
                loss_regulation = criterion_regulation(reg_pred, reg_label)
                loss_final = criterion_final(final_pred, final_label)
                loss_periods = criterion_periods(periods_pred, periods)
                total_loss += (loss_regulation + loss_final + 0.5 * loss_periods).item()
                
                _, predicted_reg = torch.max(reg_pred, 1)
                _, predicted_final = torch.max(final_pred, 1)
                total += reg_label.size(0)
                correct_reg += (predicted_reg == reg_label).sum().item()
                correct_final += (predicted_final == final_label).sum().item()
        
        return total_loss / len(loader), correct_reg / total, correct_final / total
    
    def predict(self, home_seq, away_seq):
        """Make prediction for a single match"""
        self.model.eval()
        
        with torch.no_grad():
            home_tensor = torch.tensor(home_seq, dtype=torch.float32).unsqueeze(0).to(self.device)
            away_tensor = torch.tensor(away_seq, dtype=torch.float32).unsqueeze(0).to(self.device)
            
            regulation_logits, final_logits, period_goals = self.model(home_tensor, away_tensor)
            
            regulation_probs = torch.softmax(regulation_logits, dim=1).cpu().numpy()[0]
            final_probs = torch.softmax(final_logits, dim=1).cpu().numpy()[0]
            period_goals = period_goals.cpu().numpy()[0]
        
        final_home = final_probs[0] + final_probs[2] * 0.5
        final_away = final_probs[1] + final_probs[2] * 0.5
        
        return {
            'regulation_probs': {
                'home': float(regulation_probs[0]),
                'away': float(regulation_probs[1]),
                'draw': float(regulation_probs[2])
            },
            'final_probs': {
                'home': float(final_home),
                'away': float(final_away)
            },
            'winner_probs': {
                'home': float(final_probs[0]),
                'away': float(final_probs[1]),
                'draw': float(final_probs[2])
            },
            'period_goals': {
                'home': [float(round(max(0, float(g)), 1)) for g in period_goals[:3]],
                'away': [float(round(max(0, float(g)), 1)) for g in period_goals[3:]]
            },
            'predicted_regulation': ['home', 'away', 'draw'][int(np.argmax(regulation_probs))],
            'predicted_final': 'home' if final_home > final_away else 'away',
            'predicted_winner': ['home', 'away', 'draw'][int(np.argmax(final_probs))],
            'predicted_total': float(round(sum(max(0, float(g)) for g in period_goals), 1))
        }


def train_sequence_model(df, period_data=None, sequence_length=10, 
                         hidden_dim=64, epochs=50, batch_size=32, with_odds=False):
    """Main function to train the sequence model"""
    
    logger.info("=" * 50)
    logger.info("Training Sequence Model (LSTM) - Dual Prediction")
    logger.info("=" * 50)
    
    if period_data is None or len(period_data) == 0:
        logger.warning("⚠️ Period data not provided - period goals predictions will be zeros!")
        logger.warning("   Use --load-periods flag to enable period scoring prediction")
    
    if with_odds:
        logger.info("🎲 Training with odds features enabled")
    
    preparer = SequenceDataPreparer(sequence_length=sequence_length, with_odds=with_odds)
    
    logger.info(f"Preparing sequences (length={sequence_length})...")
    home_seq, away_seq, labels_regulation, labels_final, labels_periods = preparer.prepare_sequences(
        df, period_data
    )
    
    logger.info(f"Total samples: {len(labels_final)}")
    logger.info(f"Sequence shape: {home_seq.shape}")
    
    reg_dist = np.bincount(labels_regulation, minlength=3) / len(labels_regulation)
    final_dist = np.bincount(labels_final, minlength=3) / len(labels_final)
    logger.info(f"Regulation label distribution: Home={reg_dist[0]:.1%}, Away={reg_dist[1]:.1%}, Draw={reg_dist[2]:.1%}")
    logger.info(f"Final label distribution: Home={final_dist[0]:.1%}, Away={final_dist[1]:.1%}, Draw={final_dist[2]:.1%}")
    
    home_seq, away_seq = preparer.normalize_sequences(home_seq, away_seq, fit=True)
    
    indices = np.arange(len(labels_final))
    train_idx, val_idx = train_test_split(indices, test_size=0.2, random_state=42)
    
    train_dataset = HockeySequenceDataset(
        home_seq[train_idx], away_seq[train_idx],
        labels_regulation[train_idx], labels_final[train_idx], labels_periods[train_idx]
    )
    val_dataset = HockeySequenceDataset(
        home_seq[val_idx], away_seq[val_idx],
        labels_regulation[val_idx], labels_final[val_idx], labels_periods[val_idx]
    )
    
    train_loader = torch.utils.data.DataLoader(
        train_dataset, batch_size=batch_size, shuffle=True
    )
    val_loader = torch.utils.data.DataLoader(
        val_dataset, batch_size=batch_size, shuffle=False
    )
    
    input_dim = home_seq.shape[2]
    model = HockeyLSTM(input_dim=input_dim, hidden_dim=hidden_dim)
    
    logger.info(f"Model architecture:")
    logger.info(f"  Input dim: {input_dim}")
    logger.info(f"  Hidden dim: {hidden_dim}")
    logger.info(f"  Parameters: {sum(p.numel() for p in model.parameters()):,}")
    logger.info(f"  Output heads: Regulation (3 classes), Final (3 classes), Periods (6 values)")
    
    trainer = SequenceModelTrainer(model)
    
    logger.info(f"Training for {epochs} epochs...")
    history = trainer.train(train_loader, val_loader, epochs=epochs)
    
    final_loss, final_acc_reg, final_acc_final = trainer.evaluate(val_loader)
    logger.info(f"\nFinal Results:")
    logger.info(f"  Validation Loss: {final_loss:.4f}")
    logger.info(f"  Regulation Accuracy: {final_acc_reg:.2%}")
    logger.info(f"  Final Accuracy: {final_acc_final:.2%}")
    
    return model, preparer, trainer, history


def save_sequence_model(model, preparer, path='artifacts/sequence_model'):
    """Save trained model and preparer"""
    os.makedirs(path, exist_ok=True)
    
    torch.save(model.state_dict(), os.path.join(path, 'model.pth'))
    
    joblib.dump(preparer.scaler, os.path.join(path, 'scaler.pkl'))
    
    config = {
        'sequence_length': preparer.sequence_length,
        'feature_columns': preparer.feature_columns,
        'input_dim': len(preparer.feature_columns),
        'hidden_dim': model.hidden_dim,
        'num_layers': model.num_layers,
        'with_odds': preparer.with_odds,
        'model_version': 2,
        'dual_prediction': True
    }
    with open(os.path.join(path, 'config.json'), 'w') as f:
        json.dump(config, f, indent=2)
    
    logger.info(f"Model saved to {path}")


def load_sequence_model(path='artifacts/sequence_model'):
    """Load trained model"""
    with open(os.path.join(path, 'config.json'), 'r') as f:
        config = json.load(f)
    
    model = HockeyLSTM(
        input_dim=config['input_dim'],
        hidden_dim=config['hidden_dim'],
        num_layers=config.get('num_layers', 2)
    )
    model.load_state_dict(torch.load(os.path.join(path, 'model.pth'), weights_only=True))
    
    preparer = SequenceDataPreparer(
        sequence_length=config['sequence_length'],
        with_odds=config.get('with_odds', False)
    )
    preparer.feature_columns = config['feature_columns']
    preparer.scaler = joblib.load(os.path.join(path, 'scaler.pkl'))
    
    return model, preparer


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    from data_loader import NHLDataLoader
    
    loader = NHLDataLoader()
    seasons = loader.get_default_seasons(n_seasons=3)
    df = loader.load_all_data(seasons=seasons)
    
    model, preparer, trainer, history = train_sequence_model(
        df, 
        sequence_length=10,
        hidden_dim=64,
        epochs=30,
        batch_size=32
    )
    
    save_sequence_model(model, preparer)
    
    print("\nModel training complete!")
