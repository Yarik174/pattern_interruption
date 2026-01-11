import pandas as pd
import numpy as np
from sklearn.metrics import precision_recall_curve, precision_score, recall_score
import matplotlib.pyplot as plt
from src.data_loader import NHLDataLoader
from src.feature_builder import FeatureBuilder
from src.model import PatternPredictionModel
from src.config import Config
import json
import os

class PatternAnalyzer:
    def __init__(self, config=None):
        self.config = config or Config()
        self.data_loader = NHLDataLoader()
        self.feature_builder = FeatureBuilder(critical_length=5)
        
    def analyze_break_rates_by_pattern_type(self, features_df, targets, game_info):
        print("\n" + "=" * 70)
        print("📊 АНАЛИЗ ПРЕРЫВАНИЙ ПО ТИПАМ ПАТТЕРНОВ")
        print("=" * 70)
        
        results = {}
        
        pattern_types = {
            'home_streak': {
                'critical_col': 'home_home_streak_critical',
                'streak_col': 'home_home_win_streak',
                'name': 'Домашняя серия (home team)'
            },
            'away_streak': {
                'critical_col': 'home_away_streak_critical', 
                'streak_col': 'home_away_win_streak',
                'name': 'Гостевая серия (home team)'
            },
            'overall_streak': {
                'critical_col': 'home_overall_streak_critical',
                'streak_col': 'home_overall_win_streak', 
                'name': 'Общая серия (home team)'
            },
            'h2h_streak': {
                'critical_col': 'home_h2h_streak_critical',
                'streak_col': 'home_h2h_win_streak',
                'name': 'Личные встречи'
            },
            'home_alternation': {
                'critical_col': 'home_home_alt_critical',
                'name': 'Домашнее чередование'
            },
            'overall_alternation': {
                'critical_col': 'home_overall_alt_critical',
                'name': 'Общее чередование'
            },
            'any_critical': {
                'critical_col': 'home_any_critical',
                'name': 'Любой критический паттерн'
            },
            'critical_synergy': {
                'critical_col': 'critical_synergy_home',
                'name': 'Синергия критических (2+)'
            }
        }
        
        print("\n📈 Частота прерываний по типам паттернов:")
        print("-" * 70)
        print(f"{'Тип паттерна':<35} {'Матчей':<10} {'Прерываний':<12} {'% прерыв.':<10}")
        print("-" * 70)
        
        for ptype, info in pattern_types.items():
            crit_col = info['critical_col']
            
            if crit_col not in features_df.columns:
                continue
                
            if ptype == 'critical_synergy':
                mask = features_df[crit_col] >= 2
            else:
                mask = features_df[crit_col] == 1
            
            if mask.sum() == 0:
                continue
                
            n_matches = mask.sum()
            n_breaks = targets[mask].sum()
            break_rate = n_breaks / n_matches * 100 if n_matches > 0 else 0
            
            results[ptype] = {
                'name': info['name'],
                'matches': int(n_matches),
                'breaks': int(n_breaks),
                'break_rate': round(break_rate, 1)
            }
            
            print(f"{info['name']:<35} {n_matches:<10} {n_breaks:<12} {break_rate:>6.1f}%")
        
        print("-" * 70)
        total_crit = (features_df['critical_pattern_exists'] == 1).sum()
        total_breaks = targets[features_df['critical_pattern_exists'] == 1].sum()
        base_rate = total_breaks / total_crit * 100 if total_crit > 0 else 0
        print(f"{'ВСЕГО с критическими паттернами':<35} {total_crit:<10} {total_breaks:<12} {base_rate:>6.1f}%")
        
        print("\n🔍 Анализ по длине серии:")
        print("-" * 70)
        print(f"{'Длина серии':<20} {'Матчей':<10} {'Прерываний':<12} {'% прерыв.':<10}")
        print("-" * 70)
        
        streak_col = 'home_overall_win_streak'
        if streak_col in features_df.columns:
            for streak_len in [3, 4, 5, 6, 7, 8, 9, 10]:
                mask = features_df[streak_col].abs() >= streak_len
                if mask.sum() > 10:
                    n_matches = mask.sum()
                    n_breaks = targets[mask].sum()
                    break_rate = n_breaks / n_matches * 100
                    
                    results[f'streak_{streak_len}+'] = {
                        'name': f'Серия {streak_len}+',
                        'matches': int(n_matches),
                        'breaks': int(n_breaks),
                        'break_rate': round(break_rate, 1)
                    }
                    
                    marker = "⭐" if break_rate > 50 else ""
                    print(f"Серия ≥{streak_len:<14} {n_matches:<10} {n_breaks:<12} {break_rate:>6.1f}% {marker}")
        
        print("\n🔥 Анализ синергии (несколько критических паттернов):")
        print("-" * 70)
        
        synergy_col = 'critical_synergy_home'
        if synergy_col in features_df.columns:
            for synergy in [1, 2, 3, 4]:
                mask = features_df[synergy_col] >= synergy
                if mask.sum() > 10:
                    n_matches = mask.sum()
                    n_breaks = targets[mask].sum()
                    break_rate = n_breaks / n_matches * 100
                    
                    results[f'synergy_{synergy}+'] = {
                        'name': f'Синергия {synergy}+',
                        'matches': int(n_matches),
                        'breaks': int(n_breaks),
                        'break_rate': round(break_rate, 1)
                    }
                    
                    marker = "⭐" if break_rate > 50 else ""
                    print(f"Синергия ≥{synergy}          {n_matches:<10} {n_breaks:<12} {break_rate:>6.1f}% {marker}")
        
        return results
    
    def find_optimal_threshold(self, model, X_test, y_test):
        print("\n" + "=" * 70)
        print("📊 ПОИСК ОПТИМАЛЬНОГО ПОРОГА УВЕРЕННОСТИ")
        print("=" * 70)
        
        y_proba = model.predict_proba(X_test)[:, 1]
        
        precision, recall, thresholds = precision_recall_curve(y_test, y_proba)
        
        print("\n🎯 Метрики для разных порогов:")
        print("-" * 70)
        print(f"{'Порог':<10} {'Precision':<12} {'Recall':<12} {'F1':<10} {'Сигналов':<10}")
        print("-" * 70)
        
        threshold_results = []
        
        for thresh in [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
            y_pred = (y_proba >= thresh).astype(int)
            
            if y_pred.sum() == 0:
                continue
                
            prec = precision_score(y_test, y_pred)
            rec = recall_score(y_test, y_pred)
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
            n_signals = y_pred.sum()
            
            threshold_results.append({
                'threshold': thresh,
                'precision': round(prec, 3),
                'recall': round(rec, 3),
                'f1': round(f1, 3),
                'signals': int(n_signals)
            })
            
            marker = ""
            if prec >= 0.65:
                marker = "⭐ ХОРОШИЙ"
            elif prec >= 0.55:
                marker = "✓ ПРИЕМЛЕМЫЙ"
                
            print(f"{thresh:<10.2f} {prec:<12.1%} {rec:<12.1%} {f1:<10.3f} {n_signals:<10} {marker}")
        
        filtered = [(i, r) for i, r in enumerate(threshold_results) if r['recall'] >= 0.3]
        
        if filtered:
            best_idx = max(filtered, key=lambda x: x[1]['precision'])[0]
            best_threshold = threshold_results[best_idx]['threshold']
        else:
            best_idx = 0 if threshold_results else None
            best_threshold = threshold_results[0]['threshold'] if threshold_results else 0.5
            print("\n⚠️ Нет порогов с recall ≥30%, выбран первый доступный")
        
        print("-" * 70)
        if best_idx is not None and threshold_results:
            print(f"\n✅ Рекомендуемый порог: {best_threshold:.2f}")
            print(f"   При этом пороге precision = {threshold_results[best_idx]['precision']:.1%}, recall = {threshold_results[best_idx]['recall']:.1%}")
        else:
            print(f"\n✅ Рекомендуемый порог: {best_threshold:.2f} (по умолчанию)")
        
        try:
            plt.figure(figsize=(10, 6))
            plt.plot(recall[:-1], precision[:-1], 'b-', linewidth=2, label='Precision-Recall кривая')
            plt.xlabel('Recall (полнота)', fontsize=12)
            plt.ylabel('Precision (точность)', fontsize=12)
            plt.title('Precision-Recall кривая для прерываний', fontsize=14)
            plt.grid(True, alpha=0.3)
            
            for thresh in [0.5, 0.6, 0.7]:
                idx = np.argmin(np.abs(thresholds - thresh))
                if idx < len(precision) - 1 and idx < len(recall) - 1:
                    plt.scatter(recall[idx], precision[idx], s=100, zorder=5)
                    plt.annotate(f'p={thresh}', (recall[idx], precision[idx]), 
                               textcoords="offset points", xytext=(10, 10))
            
            plt.legend()
            plt.tight_layout()
            
            os.makedirs('artifacts', exist_ok=True)
            plt.savefig('artifacts/precision_recall_curve.png', dpi=150)
            print(f"\n💾 График сохранён: artifacts/precision_recall_curve.png")
            plt.close()
        except Exception as e:
            print(f"\n⚠️ Не удалось построить график: {e}")
        
        return best_threshold, threshold_results
    
    def run_full_analysis(self):
        print("\n" + "=" * 70)
        print("🔬 ПОЛНЫЙ АНАЛИЗ ПАТТЕРНОВ")
        print("=" * 70)
        
        print("\n📥 Загрузка данных...")
        seasons = NHLDataLoader.get_default_seasons(n_seasons=10)
        games_df = self.data_loader.load_all_data(seasons=seasons, use_cache=True)
        
        print("\n🔧 Формирование признаков...")
        features_df, targets, game_info = self.feature_builder.build_features(games_df)
        
        pattern_stats = self.analyze_break_rates_by_pattern_type(features_df, targets, game_info)
        
        print("\n🤖 Обучение модели для анализа порогов...")
        model = PatternPredictionModel()
        results = model.train(features_df, targets)
        
        best_threshold, threshold_results = self.find_optimal_threshold(
            model, results['X_test'], results['y_test']
        )
        
        print("\n" + "=" * 70)
        print("📋 КЛЮЧЕВЫЕ ВЫВОДЫ")
        print("=" * 70)
        
        high_break_patterns = [k for k, v in pattern_stats.items() if v.get('break_rate', 0) > 40]
        
        print("\n🎯 Паттерны с повышенной частотой прерываний (>40%):")
        for p in high_break_patterns:
            info = pattern_stats[p]
            print(f"   • {info['name']}: {info['break_rate']}% ({info['matches']} матчей)")
        
        if not high_break_patterns:
            print("   ⚠️ Не найдено паттернов с частотой прерываний >40%")
            print("   → Рекомендация: использовать модель для прогноза ПРОДОЛЖЕНИЙ")
        
        print(f"\n✅ Рекомендуемый порог для сигналов прерывания: {best_threshold:.0%}")
        
        analysis_results = {
            'pattern_stats': pattern_stats,
            'threshold_results': threshold_results,
            'recommended_threshold': best_threshold
        }
        
        with open('artifacts/pattern_analysis.json', 'w', encoding='utf-8') as f:
            json.dump(analysis_results, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Результаты анализа сохранены: artifacts/pattern_analysis.json")
        
        return analysis_results


if __name__ == '__main__':
    analyzer = PatternAnalyzer()
    analyzer.run_full_analysis()
