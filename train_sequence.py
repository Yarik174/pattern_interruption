#!/usr/bin/env python3
"""
Train Sequence Model for Hockey Match Prediction

Usage:
    python train_sequence.py [--epochs 50] [--seq-length 10] [--hidden 64]
    python train_sequence.py --epochs 50 --seasons 7 --with-odds
"""

import argparse
import logging
import sys
import os

sys.path.insert(0, 'src')

from data_loader import NHLDataLoader
from odds_loader import OddsLoader
from sequence_model import (
    train_sequence_model, 
    save_sequence_model,
    SequenceDataPreparer,
    HockeySequenceDataset,
    SequenceModelTrainer
)
import torch
import numpy as np
from sklearn.model_selection import train_test_split

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_roi_backtest(model, preparer, df, trainer):
    """Run ROI backtest on validation data"""
    print("\n" + "=" * 60)
    print("📊 ROI Backtest on Validation Data")
    print("=" * 60)
    
    if 'home_odds' not in df.columns:
        print("⚠️ No odds data available for backtest")
        return None
    
    home_seq, away_seq, labels_winner, labels_periods = preparer.prepare_sequences(df)
    
    if len(labels_winner) == 0:
        print("⚠️ No sequences available for backtest")
        return None
    
    home_seq, away_seq = preparer.normalize_sequences(home_seq, away_seq, fit=False)
    
    indices = np.arange(len(labels_winner))
    _, val_idx = train_test_split(indices, test_size=0.2, random_state=42)
    
    df_sorted = df.sort_values('date').reset_index(drop=True)
    valid_indices = []
    current_match_idx = {}
    
    for idx, row in df_sorted.iterrows():
        home = row['home_team']
        away = row['away_team']
        
        home_idx = current_match_idx.get(home, 0)
        away_idx = current_match_idx.get(away, 0)
        
        if home_idx >= preparer.sequence_length and away_idx >= preparer.sequence_length:
            valid_indices.append(idx)
        
        current_match_idx[home] = home_idx + 1
        current_match_idx[away] = away_idx + 1
    
    valid_df_indices = [valid_indices[i] for i in val_idx if i < len(valid_indices)]
    
    total_bets = 0
    wins = 0
    total_profit = 0.0
    stake = 1.0
    
    confidence_threshold = 0.55
    
    model.eval()
    with torch.no_grad():
        for i, seq_idx in enumerate(val_idx):
            if seq_idx >= len(valid_indices):
                continue
                
            df_idx = valid_indices[seq_idx]
            row = df_sorted.iloc[df_idx]
            
            home_odds = row.get('home_odds', 1.9)
            away_odds = row.get('away_odds', 1.9)
            
            if home_odds == SequenceDataPreparer.DEFAULT_HOME_ODDS:
                continue
            
            home_tensor = torch.tensor(home_seq[seq_idx:seq_idx+1], dtype=torch.float32)
            away_tensor = torch.tensor(away_seq[seq_idx:seq_idx+1], dtype=torch.float32)
            
            winner_logits, _ = model(home_tensor, away_tensor)
            probs = torch.softmax(winner_logits, dim=1).numpy()[0]
            
            home_prob = probs[0]
            away_prob = probs[1]
            
            actual_winner = labels_winner[seq_idx]
            
            bet_placed = False
            
            if home_prob > confidence_threshold:
                total_bets += 1
                bet_placed = True
                if actual_winner == 0:
                    wins += 1
                    total_profit += stake * (home_odds - 1)
                else:
                    total_profit -= stake
            
            elif away_prob > confidence_threshold:
                total_bets += 1
                bet_placed = True
                if actual_winner == 1:
                    wins += 1
                    total_profit += stake * (away_odds - 1)
                else:
                    total_profit -= stake
    
    if total_bets > 0:
        win_rate = wins / total_bets
        roi = (total_profit / (total_bets * stake)) * 100
        
        print(f"\n📈 Backtest Results (confidence > {confidence_threshold*100:.0f}%):")
        print(f"   Total bets: {total_bets}")
        print(f"   Wins: {wins}")
        print(f"   Win rate: {win_rate:.1%}")
        print(f"   ROI: {roi:+.2f}%")
        print(f"   Profit: {total_profit:+.2f} units")
        
        return {
            'total_bets': total_bets,
            'wins': wins,
            'win_rate': win_rate,
            'roi': roi,
            'profit': total_profit
        }
    else:
        print("⚠️ No bets placed (no matches with odds above confidence threshold)")
        return None


def main():
    parser = argparse.ArgumentParser(description='Train LSTM Sequence Model')
    parser.add_argument('--epochs', type=int, default=50, help='Number of epochs')
    parser.add_argument('--seq-length', type=int, default=10, help='Sequence length')
    parser.add_argument('--hidden', type=int, default=64, help='LSTM hidden dimension')
    parser.add_argument('--batch-size', type=int, default=32, help='Batch size')
    parser.add_argument('--seasons', type=int, default=5, help='Number of seasons')
    parser.add_argument('--load-periods', action='store_true', help='Load period data from API')
    parser.add_argument('--max-period-games', type=int, default=1000, help='Max games for period data')
    parser.add_argument('--with-odds', action='store_true', help='Include odds features in training')
    args = parser.parse_args()
    
    print("=" * 60)
    print("🏒 Hockey Sequence Model Training")
    print("=" * 60)
    print(f"  Epochs: {args.epochs}")
    print(f"  Sequence Length: {args.seq_length}")
    print(f"  Hidden Dim: {args.hidden}")
    print(f"  Batch Size: {args.batch_size}")
    print(f"  Seasons: {args.seasons}")
    print(f"  With Odds: {args.with_odds}")
    print("=" * 60)
    
    loader = NHLDataLoader()
    seasons = loader.get_default_seasons(n_seasons=args.seasons)
    df = loader.load_all_data(seasons=seasons)
    
    if df.empty:
        logger.error("No data loaded!")
        return
    
    print(f"\n📊 Loaded {len(df)} matches from {args.seasons} seasons")
    
    odds_df = None
    if args.with_odds:
        print("\n🎲 Loading odds data...")
        odds_loader = OddsLoader()
        odds_df = odds_loader.load_all_odds()
        
        if odds_df is not None and not odds_df.empty:
            preparer = SequenceDataPreparer(with_odds=True)
            df = preparer.merge_with_odds(df, odds_df)
            print(f"  Merged odds with {len(df)} matches")
        else:
            print("⚠️ No odds data found, training without odds")
            args.with_odds = False
    
    period_data = None
    if args.load_periods:
        print(f"\n📥 Loading period data (max {args.max_period_games} games)...")
        preparer = SequenceDataPreparer()
        game_ids = df['game_id'].tolist()
        period_data = preparer.load_period_data(game_ids, max_games=args.max_period_games)
        print(f"  Loaded period data for {len(period_data)} games")
    
    model, preparer, trainer, history = train_sequence_model(
        df,
        period_data=period_data,
        sequence_length=args.seq_length,
        hidden_dim=args.hidden,
        epochs=args.epochs,
        batch_size=args.batch_size,
        with_odds=args.with_odds
    )
    
    save_sequence_model(model, preparer)
    
    if args.with_odds:
        run_roi_backtest(model, preparer, df, trainer)
    
    print("\n" + "=" * 60)
    print("✅ Training Complete!")
    print("=" * 60)
    print(f"  Final Validation Accuracy: {history['val_acc'][-1]:.2%}")
    print(f"  Final Validation Loss: {history['val_loss'][-1]:.4f}")
    print(f"  Features: {preparer.feature_columns}")
    print(f"  Model saved to: artifacts/sequence_model/")
    print("=" * 60)


if __name__ == '__main__':
    main()
