import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.calibration import CalibratedClassifierCV
import joblib
import logging
import os

from src.config import PATTERN_BREAK_RATES, BASE_HOME_WIN_RATE, CRITICAL_THRESHOLDS

logger = logging.getLogger(__name__)

class PatternPredictionModel:
    def __init__(self, n_estimators=100, max_depth=10, min_samples_split=5,
                 min_samples_leaf=2, max_features='sqrt', class_weight='balanced',
                 random_state=42, calibrate=True):
        self.model_params = {
            'n_estimators': n_estimators,
            'max_depth': max_depth,
            'min_samples_split': min_samples_split,
            'min_samples_leaf': min_samples_leaf,
            'max_features': max_features,
            'class_weight': class_weight,
            'random_state': random_state,
            'n_jobs': -1
        }
        self.model = RandomForestClassifier(**self.model_params)
        self.calibrated_model = None
        self.calibrate = calibrate
        self.feature_names = []
        self.is_trained = False
        self.training_results = {}
        
    def train(self, X, y, feature_names=None, test_size=0.2, game_info=None, 
              use_grid_search=False, grid_params=None):
        print("\n🤖 Обучение модели Random Forest...")
        print("=" * 50)
        logger.info("Начало обучения модели")
        
        if feature_names:
            self.feature_names = feature_names
        
        indices = np.arange(len(y))
        X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
            X, y, indices, test_size=test_size, random_state=42, stratify=y
        )
        
        self.test_indices = idx_test
        self.game_info = game_info
        self.X_test = X_test
        self.X_train = X_train
        self.y_train = y_train
        
        print(f"  Размер обучающей выборки: {len(X_train)}")
        print(f"  Размер тестовой выборки: {len(X_test)}")
        logger.info(f"Train: {len(X_train)}, Test: {len(X_test)}")
        
        # Default calibration set; overridden below when a proper split is possible
        X_calib, y_calib = X_train, y_train

        if use_grid_search and grid_params:
            print("\n🔍 Grid Search для подбора гиперпараметров...")
            self.model, best_params = self._run_grid_search(X_train, y_train, grid_params)
            self.model_params.update(best_params)
        else:
            print("\n  Обучение модели...")
            if len(X_train) > 100 and self.calibrate:
                # Reserve 25% of training data for calibration to avoid overfitting
                X_train_fit, X_calib, y_train_fit, y_calib = train_test_split(
                    X_train, y_train, test_size=0.25, random_state=42, stratify=y_train
                )
                self.model.fit(X_train_fit, y_train_fit)
            else:
                self.model.fit(X_train, y_train)

        if self.calibrate:
            print("\n📊 Калибровка вероятностей...")
            self.calibrated_model = CalibratedClassifierCV(
                self.model, method='isotonic', cv='prefit'
            )
            self.calibrated_model.fit(X_calib, y_calib)
            logger.info("Калибровка вероятностей завершена")
        
        self.is_trained = True
        
        print("\n📊 Кросс-валидация (5-fold)...")
        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='accuracy')
        print(f"  Средняя точность: {cv_scores.mean():.4f} (+/- {cv_scores.std()*2:.4f})")
        
        y_pred = self.model.predict(X_test)
        y_proba = self._get_probabilities(X_test)
        
        accuracy = accuracy_score(y_test, y_pred)
        
        print("\n" + "=" * 50)
        print("📈 РЕЗУЛЬТАТЫ ОЦЕНКИ МОДЕЛИ")
        print("=" * 50)
        
        print(f"\n  Accuracy на тестовой выборке: {accuracy:.4f}")
        
        print("\n  Classification Report:")
        print("-" * 40)
        report = classification_report(y_test, y_pred, target_names=['Гости', 'Хозяева'])
        print(report)
        
        print("\n  Confusion Matrix:")
        print("-" * 40)
        cm = confusion_matrix(y_test, y_pred)
        print(f"  [[TN={cm[0][0]:4d}  FP={cm[0][1]:4d}]")
        print(f"   [FN={cm[1][0]:4d}  TP={cm[1][1]:4d}]]")
        
        self._print_feature_importance()
        
        self.training_results = {
            'accuracy': accuracy,
            'cv_scores': cv_scores,
            'y_test': y_test,
            'y_pred': y_pred,
            'y_proba': y_proba,
            'X_test': X_test,
            'test_indices': idx_test,
            'confusion_matrix': cm,
            'model_params': self.model_params
        }
        
        logger.info(f"Точность: {accuracy:.4f}, CV: {cv_scores.mean():.4f}")
        
        return self.training_results
    
    def _run_grid_search(self, X_train, y_train, grid_params):
        base_model = RandomForestClassifier(n_jobs=-1, random_state=42)
        
        grid_search = GridSearchCV(
            base_model,
            grid_params,
            cv=3,
            scoring='f1',
            n_jobs=-1,
            verbose=1
        )
        
        grid_search.fit(X_train, y_train)
        
        print(f"\n  Лучшие параметры: {grid_search.best_params_}")
        print(f"  Лучший F1 score: {grid_search.best_score_:.4f}")
        
        logger.info(f"Grid Search лучшие параметры: {grid_search.best_params_}")
        
        return grid_search.best_estimator_, grid_search.best_params_
    
    def _get_probabilities(self, X):
        if self.calibrate and self.calibrated_model:
            return self.calibrated_model.predict_proba(X)
        return self.model.predict_proba(X)
    
    def _print_feature_importance(self, top_n=15):
        if not self.is_trained or not self.feature_names:
            return
        
        print(f"\n📊 Важность признаков (Top {top_n}):")
        print("-" * 40)
        
        importances = self.model.feature_importances_
        indices = np.argsort(importances)[::-1]
        
        for i in range(min(top_n, len(self.feature_names))):
            idx = indices[i]
            print(f"  {i+1:2d}. {self.feature_names[idx]:30s} {importances[idx]:.4f}")
    
    def get_feature_importance_df(self):
        if not self.is_trained:
            return None
        
        importances = self.model.feature_importances_
        df = pd.DataFrame({
            'feature': self.feature_names,
            'importance': importances
        }).sort_values('importance', ascending=False)
        return df
    
    def predict(self, X):
        if not self.is_trained:
            raise ValueError("Модель не обучена!")
        return self.model.predict(X)
    
    def predict_proba(self, X):
        if not self.is_trained:
            raise ValueError("Модель не обучена!")
        return self._get_probabilities(X)
    
    def save_model(self, filepath='nhl_pattern_model.pkl'):
        if not self.is_trained:
            raise ValueError("Модель не обучена!")
        
        joblib.dump({
            'model': self.model,
            'calibrated_model': self.calibrated_model,
            'feature_names': self.feature_names,
            'model_params': self.model_params
        }, filepath)
        print(f"\n💾 Модель сохранена: {filepath}")
        logger.info(f"Модель сохранена: {filepath}")
    
    def load_model(self, filepath='nhl_pattern_model.pkl'):
        data = joblib.load(filepath)
        self.model = data['model']
        self.calibrated_model = data.get('calibrated_model')
        self.feature_names = data['feature_names']
        self.model_params = data.get('model_params', {})
        self.is_trained = True
        print(f"📂 Модель загружена: {filepath}")
        logger.info(f"Модель загружена: {filepath}")
    
    def show_prediction_examples(self, results, game_info, n_examples=10, show_features=True):
        print("\n" + "=" * 80)
        print("📋 ПРИМЕРЫ ПРЕДСКАЗАНИЙ НА ТЕСТОВОЙ ВЫБОРКЕ")
        print("=" * 80)
        
        test_indices = results['test_indices']
        y_test = results['y_test']
        y_pred = results['y_pred']
        y_proba = results['y_proba']
        X_test = results.get('X_test')
        
        correct_breaks = []
        correct_continues = []
        wrong_breaks = []
        wrong_continues = []
        
        for i, idx in enumerate(test_indices):
            actual = y_test[i]
            predicted = y_pred[i]
            proba = y_proba[i][1]
            
            info = game_info.iloc[idx]
            
            date_val = info.get('date', 'N/A')
            date_str = str(date_val)[:10] if date_val != 'N/A' else 'N/A'
            
            example = {
                'date': date_str,
                'home': info.get('home_team', 'N/A'),
                'away': info.get('away_team', 'N/A'),
                'actual': actual,
                'predicted': predicted,
                'confidence': proba if predicted == 1 else 1 - proba,
                'proba_break': proba,
                'idx': i
            }
            
            if actual == 1 and predicted == 1:
                correct_breaks.append(example)
            elif actual == 0 and predicted == 0:
                correct_continues.append(example)
            elif actual == 0 and predicted == 1:
                wrong_breaks.append(example)
            else:
                wrong_continues.append(example)
        
        def print_examples(examples, title, n, is_correct, is_home_win):
            print(f"\n{title}: {len(examples)}")
            print("-" * 70)
            for ex in examples[:n]:
                pred_text = "ХОЗЯЕВА" if is_home_win else "ГОСТИ"
                conf = ex['proba_break'] if is_home_win else (1 - ex['proba_break'])
                mark = "✓" if is_correct else "✗"
                suffix = "" if is_correct else (" (выиграли хозяева)" if not is_home_win else " (выиграли гости)")
                
                print(f"  {ex['date']}  {ex['home']:20s} vs {ex['away']:20s}  "
                      f"Прогноз: {pred_text} ({conf*100:.0f}%) {mark}{suffix}")
                
                if show_features and X_test is not None and len(examples) <= 3:
                    self._show_example_features(X_test[ex['idx']])
        
        print_examples(correct_breaks, "✅ ПРАВИЛЬНЫЕ ПРОГНОЗЫ ХОЗЯЕВ (TP)", min(5, n_examples//2), True, True)
        print_examples(correct_continues, "✅ ПРАВИЛЬНЫЕ ПРОГНОЗЫ ГОСТЕЙ (TN)", min(5, n_examples//2), True, False)
        print_examples(wrong_breaks, "❌ ЛОЖНЫЕ ПРОГНОЗЫ ХОЗЯЕВ (FP)", min(5, n_examples//2), False, True)
        print_examples(wrong_continues, "❌ ПРОПУЩЕННЫЕ ПОБЕДЫ ХОЗЯЕВ (FN)", min(5, n_examples//2), False, False)
        
        print("\n" + "=" * 80)
        
        return {
            'correct_breaks': correct_breaks,
            'correct_continues': correct_continues,
            'wrong_breaks': wrong_breaks,
            'wrong_continues': wrong_continues
        }
    
    def _show_example_features(self, x_row):
        if not self.feature_names:
            return
        
        importances = self.model.feature_importances_
        top_indices = np.argsort(importances)[::-1][:10]
        
        print("      Ключевые признаки:")
        for idx in top_indices:
            if idx < len(x_row):
                val = x_row[idx]
                if val != 0:
                    print(f"        • {self.feature_names[idx]}: {val:.2f}")
    
    def get_detailed_prediction(self, x_row, game_info_row=None):
        if not self.is_trained:
            raise ValueError("Модель не обучена!")
        
        x_reshaped = x_row.reshape(1, -1) if len(x_row.shape) == 1 else x_row
        
        prediction = self.predict(x_reshaped)[0]
        proba = self.predict_proba(x_reshaped)[0]
        
        importances = self.model.feature_importances_
        top_indices = np.argsort(importances)[::-1][:15]
        
        top_features = []
        for idx in top_indices:
            top_features.append({
                'name': self.feature_names[idx],
                'value': float(x_row[idx]) if idx < len(x_row) else 0,
                'importance': float(importances[idx])
            })
        
        critical_features = []
        for i, name in enumerate(self.feature_names):
            if 'critical' in name.lower() and x_row[i] > 0:
                critical_features.append({
                    'name': name,
                    'value': float(x_row[i])
                })
        
        result = {
            'prediction': int(prediction),
            'prediction_label': 'ХОЗЯЕВА' if prediction == 1 else 'ГОСТИ',
            'probability_home': float(proba[1]),
            'probability_away': float(proba[0]),
            'confidence': float(max(proba)),
            'top_features': top_features,
            'critical_features': critical_features
        }
        
        if game_info_row is not None:
            result['game_info'] = {
                'date': str(game_info_row.get('date', ''))[:10],
                'home_team': game_info_row.get('home_team', ''),
                'away_team': game_info_row.get('away_team', '')
            }
        
        return result
    
    def print_detailed_prediction(self, x_row, game_info_row=None):
        details = self.get_detailed_prediction(x_row, game_info_row)
        
        print("\n" + "=" * 60)
        print("🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ПРОГНОЗА")
        print("=" * 60)
        
        if 'game_info' in details:
            gi = details['game_info']
            print(f"\n📅 Матч: {gi['date']}  {gi['home_team']} vs {gi['away_team']}")
        
        print(f"\n🎯 Прогноз: {details['prediction_label']}")
        print(f"   Вероятность победы хозяев: {details['probability_home']*100:.1f}%")
        print(f"   Вероятность победы гостей: {details['probability_away']*100:.1f}%")
        print(f"   Уверенность: {details['confidence']*100:.1f}%")
        
        if details['critical_features']:
            print("\n⚠️  Критические паттерны:")
            for cf in details['critical_features']:
                print(f"      • {cf['name']}: {cf['value']:.0f}")
        
        print("\n📊 Топ признаков, повлиявших на решение:")
        for i, feat in enumerate(details['top_features'][:10]):
            if feat['value'] != 0:
                print(f"   {i+1:2d}. {feat['name']:35s} = {feat['value']:6.2f}  (важность: {feat['importance']:.3f})")
        
        print("\n" + "=" * 60)
        
        return details
    
    def predict_match(self, home_features, away_features, use_bayesian=False, patterns=None):
        if not self.is_trained:
            raise ValueError("Модель не обучена!")
        
        combined_features = {}
        
        for key, value in home_features.items():
            combined_features[f'home_{key}'] = value
        
        for key, value in away_features.items():
            combined_features[f'away_{key}'] = value
        
        combined_features['streak_diff'] = home_features.get('overall_win_streak', 0) - away_features.get('overall_win_streak', 0)
        combined_features['h2h_advantage'] = home_features.get('h2h_last_5_wins', 0) - away_features.get('h2h_last_5_wins', 0)
        
        combined_features['home_any_critical'] = max(
            home_features.get('home_streak_critical', 0),
            home_features.get('h2h_streak_critical', 0),
            home_features.get('overall_streak_critical', 0)
        )
        combined_features['away_any_critical'] = max(
            away_features.get('away_streak_critical', 0),
            away_features.get('h2h_streak_critical', 0),
            away_features.get('overall_streak_critical', 0)
        )
        
        combined_features['synergy_home'] = 0
        combined_features['synergy_away'] = 0
        combined_features['pattern_agreement'] = 0
        
        X = pd.DataFrame([combined_features])[self.feature_names]
        
        prediction = self.predict(X)[0]
        proba = self.predict_proba(X)[0]
        
        result = {
            'prediction': int(prediction),
            'predicted_winner': 'home' if prediction == 1 else 'away',
            'confidence': float(max(proba)),
            'proba_away': float(proba[0]),
            'proba_home': float(proba[1])
        }
        
        if use_bayesian and patterns:
            bayesian_predictor = BayesianPatternPredictor()
            bayesian_prob = bayesian_predictor.calculate_break_probability(patterns)
            is_home_prediction = prediction == 1
            adjusted_prob = bayesian_predictor.bayesian_update_with_base_rate(
                bayesian_prob, is_home_prediction
            )
            result['bayesian_probability'] = float(bayesian_prob)
            result['bayesian_adjusted'] = float(adjusted_prob)
        
        return result


class BayesianPatternPredictor:
    """Байесовский предиктор для CPP с учётом весов паттернов"""
    
    def __init__(self, prior_samples=10):
        self.break_rates = PATTERN_BREAK_RATES
        self.base_rate = BASE_HOME_WIN_RATE
        self.prior_samples = prior_samples  # for Bayesian smoothing
        
    def calculate_break_probability(self, patterns, sample_counts=None):
        """
        Calculate weighted break probability using Bayesian update.
        
        patterns: list of dicts with {type, length, last_result}
        sample_counts: optional dict with {pattern_type: n_samples} for smoothing
        """
        if not patterns:
            return 0.5
            
        weighted_probs = []
        weights = []
        
        for p in patterns:
            pattern_type = p['type']
            length = p.get('length', 5)
            
            # Get base break rate for this pattern type
            base_prob = self.break_rates.get(pattern_type, 0.5)
            
            # Apply length adjustment (longer = slightly higher probability)
            length_factor = min(1.0 + (length - 5) * 0.02, 1.2)
            adjusted_prob = min(base_prob * length_factor, 0.75)
            
            # Bayesian smoothing for small samples
            if sample_counts and pattern_type in sample_counts:
                n = sample_counts[pattern_type]
                smoothed_prob = self._bayesian_smooth(adjusted_prob, n)
            else:
                smoothed_prob = adjusted_prob
            
            # Weight by pattern importance
            weight = self._get_pattern_weight(pattern_type)
            weighted_probs.append(smoothed_prob * weight)
            weights.append(weight)
        
        if sum(weights) > 0:
            return sum(weighted_probs) / sum(weights)
        return 0.5
    
    def _bayesian_smooth(self, observed_rate, n_samples):
        """Apply Bayesian smoothing with prior"""
        prior_rate = 0.5
        alpha = self.prior_samples
        smoothed = (observed_rate * n_samples + prior_rate * alpha) / (n_samples + alpha)
        return smoothed
    
    def _get_pattern_weight(self, pattern_type):
        """Get weight for pattern type based on reliability"""
        weights = {
            'overall_alternation': 1.3,  # most reliable
            'home_alternation': 1.2,
            'overall_streak': 1.0,
            'home_streak': 0.9,
            'h2h_streak': 0.9,
            'away_streak': 0.5,  # least reliable
            'h2h_alternation': 0.8,
            'away_alternation': 0.6,
        }
        return weights.get(pattern_type, 1.0)
    
    def bayesian_update_with_base_rate(self, pattern_prob, is_home_prediction):
        """
        Apply Bayesian update considering base rate of home wins (54%).
        
        If predicting home win: combine with positive base rate
        If predicting away win: work against base rate
        """
        if is_home_prediction:
            # Prediction aligns with base rate
            prior = self.base_rate
        else:
            # Prediction against base rate
            prior = 1 - self.base_rate
        
        # Simple Bayesian combination
        # P(outcome | pattern) = P(pattern | outcome) * P(outcome) / P(pattern)
        # Simplified: weighted average
        combined = 0.6 * pattern_prob + 0.4 * prior
        return combined
    
    def get_conditional_probability(self, pattern_type, length):
        """Get P(break | pattern_type, length) with length adjustment"""
        base = self.break_rates.get(pattern_type, 0.5)
        threshold = CRITICAL_THRESHOLDS.get(pattern_type, 5)
        
        # Excess length over threshold
        excess = max(0, length - threshold)
        
        # Slight increase for longer patterns (diminishing returns)
        adjustment = min(excess * 0.015, 0.10)
        
        return min(base + adjustment, 0.75)
