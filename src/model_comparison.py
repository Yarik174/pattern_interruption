import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import accuracy_score, f1_score, recall_score, precision_score
import xgboost as xgb
import lightgbm as lgb
import logging

logger = logging.getLogger(__name__)

class ModelComparison:
    def __init__(self, random_state=42):
        self.random_state = random_state
        self.models = {}
        self.results = {}
        
    def get_models(self, class_weight='balanced'):
        scale_pos_weight = 4
        
        models = {
            'RandomForest': RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                min_samples_leaf=2,
                class_weight=class_weight,
                random_state=self.random_state,
                n_jobs=-1
            ),
            'GradientBoosting': GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=self.random_state
            ),
            'XGBoost': xgb.XGBClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                scale_pos_weight=scale_pos_weight,
                random_state=self.random_state,
                n_jobs=-1,
                eval_metric='logloss'
            ),
            'LightGBM': lgb.LGBMClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                class_weight=class_weight,
                random_state=self.random_state,
                n_jobs=-1,
                verbose=-1
            )
        }
        return models
    
    def compare_models(self, X, y, test_size=0.2, cv_folds=5):
        print("\n" + "=" * 70)
        print("🔬 СРАВНЕНИЕ МОДЕЛЕЙ")
        print("=" * 70)
        
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=self.random_state, stratify=y
        )
        
        print(f"\n📊 Данные: {len(X_train)} train / {len(X_test)} test")
        print(f"   Распределение классов: {sum(y_train==0)} продолжений / {sum(y_train==1)} прерываний")
        
        self.models = self.get_models()
        
        results = []
        
        for name, model in self.models.items():
            print(f"\n🔄 Обучение {name}...")
            
            model.fit(X_train, y_train)
            
            y_pred = model.predict(X_test)
            y_proba = model.predict_proba(X_test)[:, 1]
            
            cv_scores = cross_val_score(model, X, y, cv=cv_folds, scoring='accuracy')
            
            metrics = {
                'model': name,
                'accuracy': accuracy_score(y_test, y_pred),
                'f1_break': f1_score(y_test, y_pred, pos_label=1),
                'recall_break': recall_score(y_test, y_pred, pos_label=1),
                'precision_break': precision_score(y_test, y_pred, pos_label=1),
                'cv_mean': cv_scores.mean(),
                'cv_std': cv_scores.std()
            }
            
            results.append(metrics)
            self.results[name] = {
                'model': model,
                'metrics': metrics,
                'y_pred': y_pred,
                'y_proba': y_proba
            }
            
            print(f"   ✅ Accuracy: {metrics['accuracy']:.3f}, "
                  f"F1: {metrics['f1_break']:.3f}, "
                  f"Recall: {metrics['recall_break']:.3f}")
        
        print("\n" + "-" * 70)
        print("📊 СВОДНАЯ ТАБЛИЦА РЕЗУЛЬТАТОВ")
        print("-" * 70)
        
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values('f1_break', ascending=False)
        
        print(f"\n{'Модель':<20} {'Accuracy':>10} {'F1':>10} {'Recall':>10} {'Precision':>10} {'CV':>12}")
        print("-" * 75)
        
        for _, row in results_df.iterrows():
            print(f"{row['model']:<20} {row['accuracy']:>10.3f} {row['f1_break']:>10.3f} "
                  f"{row['recall_break']:>10.3f} {row['precision_break']:>10.3f} "
                  f"{row['cv_mean']:>6.3f}±{row['cv_std']:.3f}")
        
        best_model = results_df.iloc[0]['model']
        print(f"\n🏆 Лучшая модель по F1: {best_model}")
        
        logger.info(f"Сравнение моделей завершено. Лучшая: {best_model}")
        
        return results_df, self.results
    
    def get_best_model(self, metric='f1_break'):
        if not self.results:
            raise ValueError("Сначала запустите compare_models()")
        
        best_name = None
        best_value = -1
        
        for name, data in self.results.items():
            value = data['metrics'].get(metric, 0)
            if value > best_value:
                best_value = value
                best_name = name
        
        return best_name, self.results[best_name]['model']
    
    def get_feature_importance(self, model_name='RandomForest', feature_names=None, top_n=15):
        if model_name not in self.results:
            raise ValueError(f"Модель {model_name} не найдена")
        
        model = self.results[model_name]['model']
        
        if hasattr(model, 'feature_importances_'):
            importances = model.feature_importances_
        else:
            return None
        
        if feature_names is None:
            feature_names = [f"feature_{i}" for i in range(len(importances))]
        
        df = pd.DataFrame({
            'feature': feature_names,
            'importance': importances
        }).sort_values('importance', ascending=False).head(top_n)
        
        return df
