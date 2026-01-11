import json
import csv
import os
from datetime import datetime
import logging
import pandas as pd

logger = logging.getLogger(__name__)

class ArtifactManager:
    def __init__(self, artifacts_dir='artifacts'):
        self.artifacts_dir = artifacts_dir
        self.run_id = None
        self.run_dir = None
        
    def start_run(self, run_id=None):
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(self.artifacts_dir, self.run_id)
        os.makedirs(self.run_dir, exist_ok=True)
        logger.info(f"Начат запуск: {self.run_id}")
        return self.run_id
    
    def save_predictions(self, predictions_df, filename='predictions.csv'):
        if self.run_dir is None:
            self.start_run()
        
        filepath = os.path.join(self.run_dir, filename)
        predictions_df.to_csv(filepath, index=False)
        logger.info(f"Предсказания сохранены: {filepath}")
        return filepath
    
    def save_prediction_details(self, details, filename='prediction_details.json'):
        if self.run_dir is None:
            self.start_run()
        
        filepath = os.path.join(self.run_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(details, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Детали предсказаний сохранены: {filepath}")
        return filepath
    
    def save_model_metrics(self, metrics, filename='metrics.json'):
        if self.run_dir is None:
            self.start_run()
        
        filepath = os.path.join(self.run_dir, filename)
        
        serializable_metrics = {}
        for key, value in metrics.items():
            if hasattr(value, 'tolist'):
                serializable_metrics[key] = value.tolist()
            elif hasattr(value, 'to_dict'):
                serializable_metrics[key] = value.to_dict()
            else:
                serializable_metrics[key] = value
        
        with open(filepath, 'w') as f:
            json.dump(serializable_metrics, f, indent=2, default=str)
        logger.info(f"Метрики сохранены: {filepath}")
        return filepath
    
    def save_feature_importance(self, feature_names, importances, filename='feature_importance.csv'):
        if self.run_dir is None:
            self.start_run()
        
        filepath = os.path.join(self.run_dir, filename)
        
        df = pd.DataFrame({
            'feature': feature_names,
            'importance': importances
        }).sort_values('importance', ascending=False)
        
        df.to_csv(filepath, index=False)
        logger.info(f"Важность признаков сохранена: {filepath}")
        return filepath
    
    def save_patterns_summary(self, patterns, filename='patterns_summary.json'):
        if self.run_dir is None:
            self.start_run()
        
        filepath = os.path.join(self.run_dir, filename)
        
        summary = {}
        for pattern_type, pattern_list in patterns.items():
            critical_count = sum(1 for p in pattern_list if p.get('critical', False))
            summary[pattern_type] = {
                'total': len(pattern_list),
                'critical': critical_count,
                'critical_patterns': [p for p in pattern_list if p.get('critical', False)][:20]
            }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Сводка паттернов сохранена: {filepath}")
        return filepath
    
    def save_training_config(self, config, filename='training_config.json'):
        if self.run_dir is None:
            self.start_run()
        
        filepath = os.path.join(self.run_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2, default=str)
        logger.info(f"Конфигурация обучения сохранена: {filepath}")
        return filepath
    
    def save_data_stats(self, stats, filename='data_stats.json'):
        if self.run_dir is None:
            self.start_run()
        
        filepath = os.path.join(self.run_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(stats, f, indent=2, default=str)
        logger.info(f"Статистика данных сохранена: {filepath}")
        return filepath
    
    def get_run_summary(self):
        if self.run_dir is None:
            return None
        
        files = os.listdir(self.run_dir) if os.path.exists(self.run_dir) else []
        return {
            'run_id': self.run_id,
            'run_dir': self.run_dir,
            'files': files
        }
    
    def list_runs(self):
        if not os.path.exists(self.artifacts_dir):
            return []
        
        runs = []
        for dirname in sorted(os.listdir(self.artifacts_dir), reverse=True):
            run_path = os.path.join(self.artifacts_dir, dirname)
            if os.path.isdir(run_path):
                metrics_path = os.path.join(run_path, 'metrics.json')
                accuracy = None
                if os.path.exists(metrics_path):
                    try:
                        with open(metrics_path, 'r') as f:
                            metrics = json.load(f)
                        accuracy = metrics.get('accuracy')
                    except:
                        pass
                
                runs.append({
                    'run_id': dirname,
                    'path': run_path,
                    'accuracy': accuracy
                })
        
        return runs
