# Hockey Pattern Prediction System

## Overview
The Hockey Pattern Prediction System is a multi-league system designed to predict outcomes of hockey matches across several leagues (NHL, KHL, SHL, Liiga, DEL). It analyzes historical match data to identify recurring patterns in results. The core idea is that when a pattern reaches a critical length (e.g., 5+ repetitions), it has a high probability of breaking. The system aims to provide profitable betting recommendations based on these pattern breaks and calculated Expected Value (EV).

## User Preferences
I prefer clear and concise explanations.
I value iterative development and regular updates on progress.
Please ask for confirmation before implementing significant architectural changes or adding new external dependencies.
Ensure all generated code is well-commented and follows standard Python best practices.

## Recent Changes (2026-01-14)

### New Features Added:
1. **PostgreSQL Database Integration** - Tables for predictions, user decisions, model versions
2. **API-Sports Integration** - For real-time betting odds and game schedules (requires API_SPORTS_KEY)
   - Поддерживает: NHL, KHL, SHL, Liiga, DEL, Czech Extraliga, Swiss NL
   - 100 запросов/день на бесплатном плане
3. **Telegram Bot Notifications** - Alerts when new predictions are generated (requires TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
4. **Background Odds Monitor** - Automatically checks for new odds and generates predictions
5. **New Web Pages:**
   - `/predictions` - Table of all predictions with filters
   - `/prediction/<id>` - Detailed prediction page with patterns (Flashscore-style) and decision form
   - `/dashboard` - Model dashboard with metrics, version info, and monitor controls
   - `/statistics` - Comparison of model predictions vs manual selection
   - `/settings/telegram` - Telegram bot setup instructions

### New Files:
- `models.py` - SQLAlchemy database models
- `src/apisports_odds_loader.py` - API-Sports client for odds and games
- `src/telegram_bot.py` - Telegram notification system
- `src/odds_monitor.py` - Background odds monitoring
- `src/routes.py` - New Flask routes for predictions, dashboard, statistics
- `templates/predictions.html` - Predictions table page
- `templates/prediction_detail.html` - Detailed prediction view
- `templates/dashboard.html` - Model dashboard
- `templates/statistics.html` - Statistics comparison page
- `templates/telegram_setup.html` - Telegram setup instructions

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
- **Database:** PostgreSQL with SQLAlchemy ORM for storing predictions, user decisions, and model versions.
- **Notifications:** Telegram bot for real-time alerts.

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
- **NHL API:** For NHL match data (nhle.com API).
- **API-Sports:** For all hockey leagues (NHL, KHL, SHL, Liiga, DEL) - odds and game schedules.
- **Telegram Bot API:** For notifications
- **Исторические odds:** data/odds/sbro-*.csv (2016-2023, 5320 матчей)
- **Flask, Flask-SQLAlchemy, PyTorch, Scikit-learn:** Core frameworks

## Environment Variables (Secrets)
- `DATABASE_URL` - PostgreSQL connection string (auto-configured)
- `SESSION_SECRET` - Flask session secret (required)
- `API_SPORTS_KEY` - API-Sports key for odds and games (required for live predictions)
- `TELEGRAM_BOT_TOKEN` - Telegram bot token (optional)
- `TELEGRAM_CHAT_ID` - Telegram chat ID for notifications (optional)

## Команды

```bash
# Обучение LSTM с коэффициентами
uv run python train_sequence.py --epochs 50 --seasons 7 --with-odds

# Запуск сервера
gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app
```

## Web Interface Routes
- `/` - Redirect to predictions (main page)
- `/predictions` - Predictions table with filters
- `/prediction/<id>` - Detailed prediction with patterns and decision form
- `/dashboard` - AI Model Dashboard with neural network visualization
- `/statistics` - Model vs manual selection comparison
- `/settings/telegram` - Telegram bot setup

## UI Design (2026-01-14)
- **Theme:** Perk.com inspired light theme
- **Colors:** #BEFF50 accent, #F5F5EB background, #14140F text
- **Navigation:** 3 pages (Predictions → Dashboard → Statistics)
- **Dashboard:** Impressive AI visualization with:
  - LSTM + Random Forest architecture diagram
  - 112 features, 5320 matches, 847K parameters
  - Feature Importance chart (top-8 features)
  - Training History loss graph (Chart.js)
  - CPP Logic profitable patterns (+64.3% ROI)
  - Live inference stats
