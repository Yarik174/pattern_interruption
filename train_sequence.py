#!/usr/bin/env python3
"""
Train Sequence Model for Hockey Match Prediction

Usage:
    python train_sequence.py [--epochs 50] [--seq-length 10] [--hidden 64]
"""

import argparse
import logging
import sys
import os

sys.path.insert(0, 'src')

from data_loader import NHLDataLoader
from sequence_model import (
    train_sequence_model, 
    save_sequence_model,
    SequenceDataPreparer
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Train LSTM Sequence Model')
    parser.add_argument('--epochs', type=int, default=50, help='Number of epochs')
    parser.add_argument('--seq-length', type=int, default=10, help='Sequence length')
    parser.add_argument('--hidden', type=int, default=64, help='LSTM hidden dimension')
    parser.add_argument('--batch-size', type=int, default=32, help='Batch size')
    parser.add_argument('--seasons', type=int, default=5, help='Number of seasons')
    parser.add_argument('--load-periods', action='store_true', help='Load period data from API')
    parser.add_argument('--max-period-games', type=int, default=1000, help='Max games for period data')
    args = parser.parse_args()
    
    print("=" * 60)
    print("🏒 Hockey Sequence Model Training")
    print("=" * 60)
    print(f"  Epochs: {args.epochs}")
    print(f"  Sequence Length: {args.seq_length}")
    print(f"  Hidden Dim: {args.hidden}")
    print(f"  Batch Size: {args.batch_size}")
    print(f"  Seasons: {args.seasons}")
    print("=" * 60)
    
    loader = NHLDataLoader()
    seasons = loader.get_default_seasons(n_seasons=args.seasons)
    df = loader.load_all_data(seasons=seasons)
    
    if df.empty:
        logger.error("No data loaded!")
        return
    
    print(f"\n📊 Loaded {len(df)} matches from {args.seasons} seasons")
    
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
        batch_size=args.batch_size
    )
    
    save_sequence_model(model, preparer)
    
    print("\n" + "=" * 60)
    print("✅ Training Complete!")
    print("=" * 60)
    print(f"  Final Validation Accuracy: {history['val_acc'][-1]:.2%}")
    print(f"  Final Validation Loss: {history['val_loss'][-1]:.4f}")
    print(f"  Model saved to: artifacts/sequence_model/")
    print("=" * 60)


if __name__ == '__main__':
    main()
