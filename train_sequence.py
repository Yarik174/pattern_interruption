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
    """Run ROI backtest on validation data for both regulation and final predictions"""
    print("\n" + "=" * 60)
    print("📊 ROI Backtest on Validation Data")
    print("=" * 60)
    
    if 'home_odds' not in df.columns:
        print("⚠️ No odds data available for backtest")
        return None
    
    home_seq, away_seq, labels_regulation, labels_final, labels_periods = preparer.prepare_sequences(df)
    
    if len(labels_final) == 0:
        print("⚠️ No sequences available for backtest")
        return None
    
    home_seq, away_seq = preparer.normalize_sequences(home_seq, away_seq, fit=False)
    
    indices = np.arange(len(labels_final))
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
    
    ml_total_bets = 0
    ml_wins = 0
    ml_total_profit = 0.0
    stake = 1.0
    confidence_threshold = 0.55
    
    reg_total_bets = 0
    reg_wins = 0
    reg_total_profit = 0.0
    
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
            
            reg_logits, final_logits, _ = model(home_tensor, away_tensor)
            
            reg_probs = torch.softmax(reg_logits, dim=1).numpy()[0]
            final_probs = torch.softmax(final_logits, dim=1).numpy()[0]
            
            final_home = final_probs[0] + final_probs[2] * 0.5
            final_away = final_probs[1] + final_probs[2] * 0.5
            
            actual_regulation = labels_regulation[seq_idx]
            actual_final = labels_final[seq_idx]
            
            if final_home > confidence_threshold:
                ml_total_bets += 1
                if actual_final == 0:
                    ml_wins += 1
                    ml_total_profit += stake * (home_odds - 1)
                else:
                    ml_total_profit -= stake
            elif final_away > confidence_threshold:
                ml_total_bets += 1
                if actual_final == 1:
                    ml_wins += 1
                    ml_total_profit += stake * (away_odds - 1)
                else:
                    ml_total_profit -= stake
            
            reg_home_prob = reg_probs[0]
            reg_away_prob = reg_probs[1]
            reg_draw_prob = reg_probs[2]
            
            reg_home_odds = home_odds * 0.85
            reg_away_odds = away_odds * 0.85
            reg_draw_odds = 4.5
            
            if reg_home_prob > confidence_threshold:
                reg_total_bets += 1
                if actual_regulation == 0:
                    reg_wins += 1
                    reg_total_profit += stake * (reg_home_odds - 1)
                else:
                    reg_total_profit -= stake
            elif reg_away_prob > confidence_threshold:
                reg_total_bets += 1
                if actual_regulation == 1:
                    reg_wins += 1
                    reg_total_profit += stake * (reg_away_odds - 1)
                else:
                    reg_total_profit -= stake
    
    results = {}
    
    print(f"\n📈 MONEY LINE (Final Result) Backtest (confidence > {confidence_threshold*100:.0f}%):")
    if ml_total_bets > 0:
        ml_win_rate = ml_wins / ml_total_bets
        ml_roi = (ml_total_profit / (ml_total_bets * stake)) * 100
        
        print(f"   Total bets: {ml_total_bets}")
        print(f"   Wins: {ml_wins}")
        print(f"   Win rate: {ml_win_rate:.1%}")
        print(f"   ROI: {ml_roi:+.2f}%")
        print(f"   Profit: {ml_total_profit:+.2f} units")
        
        results['money_line'] = {
            'total_bets': ml_total_bets,
            'wins': ml_wins,
            'win_rate': ml_win_rate,
            'roi': ml_roi,
            'profit': ml_total_profit
        }
    else:
        print("   ⚠️ No bets placed")
    
    print(f"\n📈 1X2 (Regulation Result) Backtest (confidence > {confidence_threshold*100:.0f}%):")
    if reg_total_bets > 0:
        reg_win_rate = reg_wins / reg_total_bets
        reg_roi = (reg_total_profit / (reg_total_bets * stake)) * 100
        
        print(f"   Total bets: {reg_total_bets}")
        print(f"   Wins: {reg_wins}")
        print(f"   Win rate: {reg_win_rate:.1%}")
        print(f"   ROI: {reg_roi:+.2f}%")
        print(f"   Profit: {reg_total_profit:+.2f} units")
        
        results['regulation'] = {
            'total_bets': reg_total_bets,
            'wins': reg_wins,
            'win_rate': reg_win_rate,
            'roi': reg_roi,
            'profit': reg_total_profit
        }
    else:
        print("   ⚠️ No bets placed")
    
    return results if results else None


def main():
    parser = argparse.ArgumentParser(description='Train LSTM Sequence Model')
    parser.add_argument('--epochs', type=int, default=50, help='Number of epochs')
    parser.add_argument('--seq-length', type=int, default=10, help='Sequence length')
    parser.add_argument('--hidden', type=int, default=64, help='LSTM hidden dimension')
    parser.add_argument('--batch-size', type=int, default=32, help='Batch size')
    parser.add_argument('--seasons', type=int, default=0, help='Number of seasons (0 = all cached seasons)')
    parser.add_argument('--load-periods', action='store_true', help='Load period data from API')
    parser.add_argument('--max-period-games', type=int, default=1000, help='Max games for period data')
    parser.add_argument('--with-odds', action='store_true', help='Include odds features in training')
    args = parser.parse_args()
    
    print("=" * 60)
    print("🏒 Hockey Sequence Model Training (Dual Prediction)")
    print("=" * 60)
    print(f"  Epochs: {args.epochs}")
    print(f"  Sequence Length: {args.seq_length}")
    print(f"  Hidden Dim: {args.hidden}")
    print(f"  Batch Size: {args.batch_size}")
    print(f"  Seasons: {'all cached' if args.seasons == 0 else args.seasons}")
    print(f"  With Odds: {args.with_odds}")
    print("  Prediction Heads: Regulation (1X2) + Final (Money Line)")
    print("=" * 60)
    
    loader = NHLDataLoader()
    if args.seasons == 0:
        seasons = loader.get_cached_seasons() or loader.get_default_seasons(n_seasons=10)
    else:
        seasons = loader.get_default_seasons(n_seasons=args.seasons)
    df = loader.load_all_data(seasons=seasons)
    
    if df.empty:
        logger.error("No data loaded!")
        return
    
    print(f"\n📊 Loaded {len(df)} matches from {len(seasons)} seasons")
    
    overtime_pct = df['overtime'].mean() * 100
    print(f"   Overtime games: {overtime_pct:.1f}%")
    
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
    print(f"  Final Validation Accuracy (Regulation): {history['val_acc_regulation'][-1]:.2%}")
    print(f"  Final Validation Accuracy (Final): {history['val_acc_final'][-1]:.2%}")
    print(f"  Final Validation Loss: {history['val_loss'][-1]:.4f}")
    print(f"  Features ({len(preparer.feature_columns)}): {preparer.feature_columns}")
    print(f"  Model saved to: artifacts/sequence_model/")
    print("=" * 60)


if __name__ == '__main__':
    main()
