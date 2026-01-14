# Hockey Pattern Prediction System

## Overview
The Hockey Pattern Prediction System is a multi-league system designed to predict outcomes of hockey matches across several leagues (NHL, KHL, SHL, Liiga, DEL). It analyzes historical match data to identify recurring patterns in results. The core idea is that when a pattern reaches a critical length (e.g., 5+ repetitions), it has a high probability of breaking. The system aims to provide profitable betting recommendations based on these pattern breaks and calculated Expected Value (EV).

## User Preferences
I prefer clear and concise explanations.
I value iterative development and regular updates on progress.
Please ask for confirmation before implementing significant architectural changes or adding new external dependencies.
Ensure all generated code is well-commented and follows standard Python best practices.

## System Architecture
The system is built around a core pattern recognition engine that identifies various types of patterns, including home series, away series, head-to-head records, and alternating win/loss sequences. It utilizes both a Random Forest model for general predictions and a Critical Pattern Prediction (CPP) logic for identifying high-confidence pattern breaks.

**Technical Implementations:**
- **Data Loading:** `data_loader.py` handles NHL data via an API with caching. `multi_league_loader.py` fetches data for European leagues using API-Sports.
- **Pattern Engine:** `pattern_engine.py` is central to identifying and analyzing patterns, including calculating their "weights" or reliability.
- **Feature Engineering:** `feature_builder.py` creates features for machine learning models, incorporating series lengths, alternations, synergies, and deep H2H statistics.
- **Prediction Models:**
    - **Random Forest:** `model.py` implements a Random Forest classifier with probability calibration. It uses 112 features and achieves an accuracy of ~54.44%.
    - **LSTM Sequence Model:** `sequence_model.py` uses a PyTorch-based LSTM neural network with dual prediction for regulation (1X2) and final (Money Line) results.
- **CPP Logic:** This logic determines pattern breaks based on predefined critical lengths and rules. Synergy (multiple patterns pointing to the same outcome) is a key factor for bet recommendations.

## LSTM Sequence Model (обновлено 2026-01-14)

### Dual Prediction
Модель предсказывает два типа результатов:
1. **Regulation (1X2)** — основное время, ничья возможна
2. **Final (Money Line)** — включая овертайм, всегда победитель

### Признаки (13):
goals_scored, goals_conceded, won, home_game, overtime, goal_diff, total_goals, won_regulation, won_overtime, draw_regulation, home_odds, away_odds, implied_prob

### Результаты обучения:
| Тип прогноза | Accuracy | Распределение |
|--------------|----------|---------------|
| Regulation (1X2) | 44.51% | Home=42.8%, Away=35.1%, Draw=22.1% |
| Final (Money Line) | 55.49% | Home=53.9%, Away=46.1% |

### ROI на валидации:
| Тип ставки | Ставок | Win Rate | ROI |
|------------|--------|----------|-----|
| Money Line | 265 | 62.6% | -3.24% |
| 1X2 | 9 | 77.8% | -14.15% |

## CPP Backtest (5320 матчей NHL, 2016-2023)

### Поддержка двух типов ставок
- **Money Line (Final)** — с овертаймом, всегда победитель
- **1X2 (Regulation)** — основное время, ничья возможна (~22%)

### Прибыльные комбинации паттернов (синергия ≥2)

| Комбинация | ML ROI | 1X2 ROI | n |
|------------|--------|---------|---|
| AwayLoss→Break + HomeWin→Break + Overall→Break | **+64.3%** | +12.2% | 17 |
| H2H_Away→Break + HomeLoss→Break | **+27.4%** | +20.8% | 21 |
| AwayLoss→Break + HomeWin→Break | **+11.8%** | +5.8% | 54 |

### Вывод
- **Money Line лучше 1X2** — ничья в 1X2 = проигрыш
- **CPP паттерны дают +11-64% ROI** на проверенных комбинациях
- LSTM модель пока не прибыльна (-3% ROI)
- **Переход к реальным прогнозам** для дообучения на живых данных

## External Dependencies
- **NHL API:** For NHL match data.
- **API-Sports:** For KHL, SHL, Liiga, and DEL match data.
- **The Odds API:** For real-time betting odds (ODDS_API_KEY в секретах).
- **Исторические odds:** data/odds/sbro-*.csv (2016-2023, 5320 матчей)
- **Flask, PyTorch, Scikit-learn:** Core frameworks

## Команды

```bash
# Обучение LSTM с коэффициентами
uv run python train_sequence.py --epochs 50 --seasons 7 --with-odds

# Запуск сервера
uv run python app.py
```
