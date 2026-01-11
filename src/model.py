import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.calibration import CalibratedClassifierCV
import joblib
import logging
import os

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
        
        if use_grid_search and grid_params:
            print("\n🔍 Grid Search для подбора гиперпараметров...")
            self.model, best_params = self._run_grid_search(X_train, y_train, grid_params)
            self.model_params.update(best_params)
        else:
            print("\n  Обучение модели...")
            self.model.fit(X_train, y_train)
        
        if self.calibrate:
            print("\n📊 Калибровка вероятностей...")
            self.calibrated_model = CalibratedClassifierCV(
                self.model, method='isotonic', cv=3
            )
            self.calibrated_model.fit(X_train, y_train)
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
        report = classification_report(y_test, y_pred, target_names=['Продолжение', 'Прерывание'])
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
        
        def print_examples(examples, title, n, is_correct, is_break):
            print(f"\n{title}: {len(examples)}")
            print("-" * 70)
            for ex in examples[:n]:
                pred_text = "ПРЕРЫВАНИЕ" if is_break else "ПРОДОЛЖЕНИЕ"
                conf = ex['proba_break'] if is_break else (1 - ex['proba_break'])
                mark = "✓" if is_correct else "✗"
                suffix = "" if is_correct else (" (было прерывание)" if not is_break else "")
                
                print(f"  {ex['date']}  {ex['home']:20s} vs {ex['away']:20s}  "
                      f"Прогноз: {pred_text} ({conf*100:.0f}%) {mark}{suffix}")
                
                if show_features and X_test is not None and len(examples) <= 3:
                    self._show_example_features(X_test[ex['idx']])
        
        print_examples(correct_breaks, "✅ ПРАВИЛЬНЫЕ ПРЕРЫВАНИЯ (TP)", min(5, n_examples//2), True, True)
        print_examples(correct_continues, "✅ ПРАВИЛЬНЫЕ ПРОДОЛЖЕНИЯ (TN)", min(5, n_examples//2), True, False)
        print_examples(wrong_breaks, "❌ ЛОЖНЫЕ ПРЕРЫВАНИЯ (FP)", min(5, n_examples//2), False, True)
        print_examples(wrong_continues, "❌ ПРОПУЩЕННЫЕ ПРЕРЫВАНИЯ (FN)", min(5, n_examples//2), False, False)
        
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
            'prediction_label': 'ПРЕРЫВАНИЕ' if prediction == 1 else 'ПРОДОЛЖЕНИЕ',
            'probability_break': float(proba[1]),
            'probability_continue': float(proba[0]),
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
        print(f"   Вероятность прерывания: {details['probability_break']*100:.1f}%")
        print(f"   Вероятность продолжения: {details['probability_continue']*100:.1f}%")
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
    
    def predict_match(self, home_features, away_features):
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
        
        return {
            'pattern_break_prediction': prediction,
            'confidence': float(max(proba)),
            'proba_continue': float(proba[0]),
            'proba_break': float(proba[1])
        }
