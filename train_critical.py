#!/usr/bin/env python3
"""
Переобучение RF только на критических паттернах.

Ключевые отличия от старого обучения:
1. Target = прерывание критического паттерна (_calculate_target_combined),
   а не home_win
2. Обучающая выборка = только матчи где есть хоть один критический паттерн
3. Фичи те же 96, но модель видит осмысленные примеры
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
import joblib
import json
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from src.data_loader import DataLoader
from src.pattern_engine import PatternEngine
from src.feature_builder import FeatureBuilder
from src.config import CRITICAL_THRESHOLDS

print("=" * 60)
print("🎯 Переобучение на критических паттернах")
print("=" * 60)

# ─── 1. Данные ────────────────────────────────────────────────
print("\n📥 Загрузка данных (5 сезонов)...")
dl = DataLoader()
seasons = DataLoader.get_default_seasons(n_seasons=5)
games_df = dl.load_all_data(seasons=seasons)
print(f"   Матчей: {len(games_df)}")

# ─── 2. Строим фичи с правильным target ──────────────────────
print("\n🔧 Формирование признаков...")
fb = FeatureBuilder()
pe = fb.pattern_engine

games_sorted = games_df.sort_values('date').reset_index(drop=True)
MIN_HISTORY = 20

features_list = []
targets_break = []   # прерывание паттерна (наш новый target)
targets_home = []    # победа хозяев (старый target — для сравнения)
has_critical = []    # есть ли критический паттерн

print(f"   Обработка {len(games_sorted) - MIN_HISTORY} матчей...")

for idx in range(MIN_HISTORY, len(games_sorted)):
    row = games_sorted.iloc[idx]
    history = games_sorted.iloc[:idx]

    home_team = row['home_team']
    away_team = row['away_team']
    game_date = row['date']

    home_f = pe.get_pattern_features(home_team, away_team, history, game_date)
    away_f = pe.get_pattern_features(away_team, home_team, history, game_date)

    if home_f is None or away_f is None:
        continue

    # Combined features (то же что в FeatureBuilder.build_features)
    cf = {}
    for k, v in home_f.items():
        cf[f'home_{k}'] = v
    for k, v in away_f.items():
        cf[f'away_{k}'] = v

    cf['streak_diff'] = home_f.get('overall_win_streak', 0) - away_f.get('overall_win_streak', 0)
    cf['h2h_advantage'] = home_f.get('h2h_last_5_wins', 0) - away_f.get('h2h_last_5_wins', 0)

    cf['home_any_critical'] = max(
        home_f.get('home_streak_critical', 0), home_f.get('h2h_streak_critical', 0),
        home_f.get('overall_streak_critical', 0), home_f.get('home_alt_critical', 0),
        home_f.get('h2h_alt_critical', 0), home_f.get('overall_alt_critical', 0)
    )
    cf['away_any_critical'] = max(
        away_f.get('away_streak_critical', 0), away_f.get('h2h_streak_critical', 0),
        away_f.get('overall_streak_critical', 0), away_f.get('away_alt_critical', 0),
        away_f.get('h2h_alt_critical', 0), away_f.get('overall_alt_critical', 0)
    )

    cf['home_total_critical'] = home_f.get('total_critical_patterns', 0)
    cf['away_total_critical'] = away_f.get('total_critical_patterns', 0)
    cf['max_streak_len'] = max(home_f.get('max_streak_len', 0), away_f.get('max_streak_len', 0))
    cf['max_alternation_len'] = max(home_f.get('max_alternation_len', 0), away_f.get('max_alternation_len', 0))

    home_syn, home_aligned = fb._calculate_critical_synergy(home_f, 'home')
    away_syn, away_aligned = fb._calculate_critical_synergy(away_f, 'away')
    cf['synergy_home'] = fb._calculate_synergy(home_f, 'home')
    cf['synergy_away'] = fb._calculate_synergy(away_f, 'away')
    cf['critical_synergy_home'] = home_syn
    cf['critical_synergy_away'] = away_syn
    cf['aligned_patterns_home'] = home_aligned
    cf['aligned_patterns_away'] = away_aligned
    cf['total_aligned'] = abs(home_aligned) + abs(away_aligned)
    cf['pattern_agreement'] = 1 if fb._predict_from_pattern(home_f) == (1 - fb._predict_from_pattern(away_f)) else 0
    cf['critical_pattern_exists'] = 1 if (cf['home_total_critical'] > 0 or cf['away_total_critical'] > 0) else 0

    home_og = fb._calculate_overgrowth(home_f)
    away_og = fb._calculate_overgrowth(away_f)
    cf['home_streak_overgrowth'] = home_og
    cf['away_streak_overgrowth'] = away_og
    cf['max_overgrowth'] = max(home_og, away_og)

    home_ac = fb._calculate_alternation_combo(home_f)
    away_ac = fb._calculate_alternation_combo(away_f)
    cf['home_alternation_combo'] = home_ac
    cf['away_alternation_combo'] = away_ac
    cf['max_alternation_combo'] = max(home_ac, away_ac)

    cf['home_strong_signal'] = fb._calculate_strong_signal(home_f, home_syn, home_ac, home_og)
    cf['away_strong_signal'] = fb._calculate_strong_signal(away_f, away_syn, away_ac, away_og)
    cf['any_strong_signal'] = max(cf['home_strong_signal'], cf['away_strong_signal'])

    home_bp = fb._calculate_predicted_break_outcome(home_f, 'home')
    away_bp = fb._calculate_predicted_break_outcome(away_f, 'away')
    cf['home_predicted_break'] = len(home_bp)
    cf['away_predicted_break'] = len(away_bp)

    cf['home_independent_patterns'] = fb._calculate_independent_patterns(home_f)
    cf['away_independent_patterns'] = fb._calculate_independent_patterns(away_f)

    cf['home_weighted_break_prob'] = fb._calculate_weighted_break_probability(home_f, 'home')
    cf['away_weighted_break_prob'] = fb._calculate_weighted_break_probability(away_f, 'away')

    actual_result = int(row['home_win'])

    # ← ГЛАВНОЕ ОТЛИЧИЕ: правильный target
    target_break = fb._calculate_target_combined(home_f, away_f, actual_result)

    features_list.append(cf)
    targets_break.append(target_break)
    targets_home.append(actual_result)
    has_critical.append(int(cf['critical_pattern_exists']))

    if idx % 1000 == 0:
        print(f"   {idx}/{len(games_sorted)}...")

features_df = pd.DataFrame(features_list)
targets_break = np.array(targets_break)
targets_home = np.array(targets_home)
has_critical = np.array(has_critical)

feature_names = list(features_df.columns)

print(f"\n📊 Итого:")
print(f"   Всего образцов:       {len(features_df)}")
print(f"   С критич. паттерном:  {has_critical.sum()} ({100*has_critical.mean():.1f}%)")
print(f"   Break rate (все):     {targets_break.mean():.3f}")
print(f"   Break rate (крит.):   {targets_break[has_critical==1].mean():.3f}")
print(f"   Home win rate:        {targets_home.mean():.3f}")

# ─── 3. Фильтруем — только критические ────────────────────────
mask = has_critical == 1
X_crit = features_df[mask].values
y_crit = targets_break[mask]

print(f"\n🎯 Обучаем на {len(X_crit)} критических матчах")
print(f"   Break: {y_crit.sum()} ({100*y_crit.mean():.1f}%)")
print(f"   Continue: {len(y_crit)-y_crit.sum()} ({100*(1-y_crit.mean()):.1f}%)")

# ─── 4. Обучение RF ───────────────────────────────────────────
print("\n🤖 Обучение Random Forest...")
X_train, X_test, y_train, y_test = train_test_split(
    X_crit, y_crit, test_size=0.2, random_state=42, stratify=y_crit
)

rf = RandomForestClassifier(
    n_estimators=200,
    max_depth=8,
    min_samples_split=10,
    min_samples_leaf=5,
    max_features='sqrt',
    class_weight='balanced',
    random_state=42,
    n_jobs=-1
)
rf.fit(X_train, y_train)

# Калибровка
print("📊 Калибровка вероятностей...")
calibrated = CalibratedClassifierCV(rf, method='isotonic', cv=3)
calibrated.fit(X_train, y_train)

# ─── 5. Оценка ────────────────────────────────────────────────
y_pred = rf.predict(X_test)
y_proba = calibrated.predict_proba(X_test)[:, 1]

acc = accuracy_score(y_test, y_pred)
cv_scores = cross_val_score(rf, X_crit, y_crit, cv=5, scoring='accuracy')

print(f"\n📈 РЕЗУЛЬТАТЫ:")
print(f"   Accuracy:    {acc:.4f}")
print(f"   CV mean:     {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
print(f"\n   Confusion Matrix:")
cm = confusion_matrix(y_test, y_pred)
print(f"   [[TN={cm[0][0]:4d}  FP={cm[0][1]:4d}]")
print(f"    [FN={cm[1][0]:4d}  TP={cm[1][1]:4d}]]")

print(f"\n   Classification Report:")
print(classification_report(y_test, y_pred, target_names=['Continue', 'Break']))

# Разброс вероятностей
print(f"\n   Разброс predict_proba:")
print(f"   min={y_proba.min():.3f}  max={y_proba.max():.3f}  std={y_proba.std():.3f}")
print(f"   (старая модель: std≈0.027 — почти ноль)")

# Топ фич
importances = rf.feature_importances_
top_idx = np.argsort(importances)[::-1][:15]
print(f"\n📊 Топ-15 признаков:")
for i, idx in enumerate(top_idx):
    print(f"   {i+1:2d}. {feature_names[idx]:<35s} {importances[idx]:.4f}")

# ─── 6. Проверка чувствительности ─────────────────────────────
print("\n🔍 Проверка чувствительности модели:")
fn = feature_names

def make_X(overrides):
    row = {n: 0 for n in fn}
    row.update(overrides)
    return np.array([[row[n] for n in fn]])

# Нулевые фичи
p0 = calibrated.predict_proba(make_X({}))[0]
print(f"   Нулевые фичи:          break={p0[1]:.3f}")

# Серия +10 побед дома
p1 = calibrated.predict_proba(make_X({
    'home_home_win_streak': 10, 'home_overall_win_streak': 10,
    'streak_diff': 10, 'home_home_win_streak': 10,
    'home_any_critical': 1, 'home_total_critical': 2,
    'critical_pattern_exists': 1, 'home_streak_overgrowth': 3,
    'home_strong_signal': 5, 'any_strong_signal': 5
}))[0]
print(f"   Серия +10 дома:        break={p1[1]:.3f}")

# Серия поражений
p2 = calibrated.predict_proba(make_X({
    'home_home_win_streak': -7, 'home_overall_win_streak': -7,
    'streak_diff': -7, 'home_any_critical': 1, 'home_total_critical': 1,
    'critical_pattern_exists': 1
}))[0]
print(f"   Серия -7 дома:         break={p2[1]:.3f}")

# Чередование
p3 = calibrated.predict_proba(make_X({
    'home_alternation_combo': 3, 'home_strong_signal': 4,
    'critical_pattern_exists': 1, 'home_any_critical': 1,
    'any_strong_signal': 4
}))[0]
print(f"   Критич. чередование:   break={p3[1]:.3f}")

# ─── 7. Сохранение ────────────────────────────────────────────
run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir = f"artifacts/{run_id}"
os.makedirs(out_dir, exist_ok=True)

# Сохраняем модель — нужен calibrated (он поверх rf)
# В app.py грузится как: model_data.get('model')
# Поэтому кладём calibrated в 'model' чтобы работало
joblib.dump({
    'model': calibrated,           # calibrated RF → дифференцированные вероятности
    'rf_raw': rf,                  # сырой RF для feature importance
    'feature_names': feature_names,
    'trained_on': 'critical_patterns_only',
    'target': 'pattern_break',
    'n_samples': len(X_crit),
    'break_rate': float(y_crit.mean()),
}, f"{out_dir}/model.pkl")

# feature_importance.csv
fi_df = pd.DataFrame({'feature': feature_names, 'importance': importances})
fi_df = fi_df.sort_values('importance', ascending=False)
fi_df.to_csv(f"{out_dir}/feature_importance.csv", index=False)

# metrics.json
metrics = {
    'accuracy': float(acc),
    'cv_mean': float(cv_scores.mean()),
    'cv_std': float(cv_scores.std()),
    'n_samples_total': len(features_df),
    'n_samples_critical': int(len(X_crit)),
    'break_rate': float(y_crit.mean()),
    'confusion_matrix': cm.tolist(),
    'proba_std': float(y_proba.std()),
    'model': 'CalibratedRF(RF+critical_target)',
    'trained_on': 'critical_patterns_only',
}
with open(f"{out_dir}/metrics.json", 'w') as f:
    json.dump(metrics, f, indent=2)

print(f"\n✅ Модель сохранена: {out_dir}/")
print(f"   Accuracy: {acc:.3f}  CV: {cv_scores.mean():.3f}±{cv_scores.std():.3f}")
print(f"   proba_std: {y_proba.std():.3f}  (было 0.027 — чем выше, тем лучше)")
print(f"\n🚀 Теперь запусти тест: RAPIDAPI_KEY=... venv/bin/python /tmp/pi_test3.py")
