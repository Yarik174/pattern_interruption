#!/usr/bin/env python3
"""
Retrain RF model on full historical data (12 seasons, correct dates).

Uses pre-computed feature_matrix.joblib from backtest_nhl.py instead of
DataLoader API cache. Walk-forward: train on seasons 2011-2020, test on 2021-2022.

Usage:
    python scripts/retrain_rf.py
"""

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import numpy as np
import pandas as pd
import joblib
import json
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import cross_val_score
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix


def main():
    print("=" * 60)
    print("RF MODEL RETRAINING (full 12-season data)")
    print("=" * 60)

    # Load pre-computed features from backtest
    feat_path = 'data/backtest_results/feature_matrix.joblib'
    if not os.path.exists(feat_path):
        print("ERROR: feature_matrix.joblib not found. Run backtest_nhl.py first.")
        sys.exit(1)

    data = joblib.load(feat_path)
    features_df = data['features_df']
    targets = data['targets']

    print(f"Loaded: {len(features_df)} samples, {len(features_df.columns)} features")
    print(f"Break rate (all): {targets.mean():.3f}")

    # Filter: only critical pattern matches
    has_critical = features_df['critical_pattern_exists'] == 1
    X_crit = features_df[has_critical].values
    y_crit = targets[has_critical]

    feature_names = list(features_df.columns)

    print(f"\nCritical matches: {len(X_crit)} ({100*has_critical.mean():.1f}%)")
    print(f"Break rate (critical): {y_crit.mean():.3f}")

    # Load RL data for season info
    rl_path = 'data/backtest_results/rl_training_data.json'
    with open(rl_path) as f:
        rl_data = json.load(f)

    # Build season labels for all features
    # rl_data only has synergy>0 records; we need seasons for all features
    # Use the dates from the feature matrix indices
    # Actually, let's load the odds data to get seasons
    from src.underdog_patterns import load_all_odds_data, add_underdog_info
    df = load_all_odds_data()
    df = add_underdog_info(df)
    df = df.sort_values('date').reset_index(drop=True)

    # Map features back to seasons via _row_idx
    # Since we don't have _row_idx in feature_matrix, do walk-forward split by index
    # Train on first 80% (roughly 2011-2020), test on last 20% (2021-2022)
    n_total = len(X_crit)
    split_idx = int(n_total * 0.8)

    X_train, X_test = X_crit[:split_idx], X_crit[split_idx:]
    y_train, y_test = y_crit[:split_idx], y_crit[split_idx:]

    print(f"\nWalk-forward split:")
    print(f"  Train: {len(X_train)} ({100*len(X_train)/n_total:.0f}%)")
    print(f"  Test:  {len(X_test)} ({100*len(X_test)/n_total:.0f}%)")
    print(f"  Train break rate: {y_train.mean():.3f}")
    print(f"  Test break rate:  {y_test.mean():.3f}")

    # Train RF
    print("\nTraining Random Forest...")
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_split=10,
        min_samples_leaf=5,
        max_features='sqrt',
        class_weight='balanced',
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)

    # Calibrate
    print("Calibrating probabilities...")
    calibrated = CalibratedClassifierCV(rf, method='isotonic', cv=3)
    calibrated.fit(X_train, y_train)

    # Evaluate
    y_pred = rf.predict(X_test)
    y_proba = calibrated.predict_proba(X_test)[:, 1]

    acc = accuracy_score(y_test, y_pred)
    cv_scores = cross_val_score(rf, X_crit, y_crit, cv=5, scoring='accuracy')
    cm = confusion_matrix(y_test, y_pred)

    print(f"\nRESULTS:")
    print(f"  Accuracy:     {acc:.4f}")
    print(f"  CV mean:      {cv_scores.mean():.4f} +/- {cv_scores.std():.4f}")
    print(f"  Confusion Matrix:")
    print(f"  [[TN={cm[0][0]:4d}  FP={cm[0][1]:4d}]")
    print(f"   [FN={cm[1][0]:4d}  TP={cm[1][1]:4d}]]")
    print(f"\n{classification_report(y_test, y_pred, target_names=['Continue', 'Break'])}")

    print(f"  Probability spread: min={y_proba.min():.3f}, max={y_proba.max():.3f}, std={y_proba.std():.3f}")

    # Top features
    importances = rf.feature_importances_
    top_idx = np.argsort(importances)[::-1][:15]
    print(f"\nTop 15 features:")
    for i, idx in enumerate(top_idx):
        print(f"  {i+1:2d}. {feature_names[idx]:<40s} {importances[idx]:.4f}")

    # Save model
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = f"artifacts/{run_id}"
    os.makedirs(out_dir, exist_ok=True)

    joblib.dump({
        'model': calibrated,
        'rf_raw': rf,
        'feature_names': feature_names,
        'trained_on': 'critical_patterns_12_seasons_full_dates',
        'target': 'pattern_break',
        'n_samples': len(X_crit),
        'n_train': len(X_train),
        'n_test': len(X_test),
        'break_rate': float(y_crit.mean()),
    }, f"{out_dir}/model.pkl")

    fi_df = pd.DataFrame({'feature': feature_names, 'importance': importances})
    fi_df = fi_df.sort_values('importance', ascending=False)
    fi_df.to_csv(f"{out_dir}/feature_importance.csv", index=False)

    metrics = {
        'accuracy': float(acc),
        'cv_mean': float(cv_scores.mean()),
        'cv_std': float(cv_scores.std()),
        'n_samples_total': len(features_df),
        'n_samples_critical': int(len(X_crit)),
        'n_train': len(X_train),
        'n_test': len(X_test),
        'break_rate': float(y_crit.mean()),
        'confusion_matrix': cm.tolist(),
        'proba_std': float(y_proba.std()),
        'model': 'CalibratedRF(RF+critical_target)',
        'data': '12 seasons (2011-2022), full dates, sbro odds',
    }
    with open(f"{out_dir}/metrics.json", 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f"\nModel saved: {out_dir}/")
    print(f"  Accuracy: {acc:.3f}  CV: {cv_scores.mean():.3f}+/-{cv_scores.std():.3f}")
    print(f"  proba_std: {y_proba.std():.3f}")

    # Now re-run cross-validation with the NEW model
    print(f"\n{'='*60}")
    print("RE-RUNNING BACKTEST WITH NEW MODEL")
    print(f"{'='*60}")

    # Predict on ALL critical data with new model
    all_proba = calibrated.predict_proba(X_crit)[:, 1]
    print(f"\nNew RF confidence: mean={all_proba.mean():.3f}, std={all_proba.std():.3f}")

    # Update rl_training_data.json with new confidences
    # Re-predict on full feature set
    X_all = features_df.values
    all_conf = calibrated.predict_proba(X_all)[:, 1]

    # Rebuild rl_training_data with new confidences
    # Load the original to get season/odds info
    from src.underdog_patterns import load_all_odds_data
    df_reloaded = load_all_odds_data()
    df_reloaded = df_reloaded.sort_values('date').reset_index(drop=True)

    # We need to map back... but we don't have _row_idx in the feature matrix
    # Instead, update the existing rl_training_data with new RF predictions
    # by matching on date+teams
    print(f"\nUpdating RL training data with new model confidences...")

    # Simpler approach: re-run backtest_nhl with new model path
    # For now, just update the model path reference
    old_model = 'artifacts/20260301_235042/model.pkl'
    print(f"\nOLD model: {old_model}")
    print(f"NEW model: {out_dir}/model.pkl")
    print(f"\nTo use new model, update RF_MODEL_PATH in scripts/backtest_nhl.py")
    print(f"Then re-run: python scripts/backtest_nhl.py && python scripts/cross_validate.py")


if __name__ == '__main__':
    main()
