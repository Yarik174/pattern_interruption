# Hockey Pattern Prediction System

## Overview
The Hockey Pattern Prediction System is a multi-league system designed to predict outcomes of hockey matches across several leagues (NHL, KHL, SHL, Liiga, DEL). It analyzes historical match data to identify recurring patterns in results. The core idea is that when a pattern reaches a critical length, it has a high probability of breaking. The system aims to provide profitable betting recommendations based on these pattern breaks and calculated Expected Value (EV).

## User Preferences
I prefer clear and concise explanations.
I value iterative development and regular updates on progress.
Please ask for confirmation before implementing significant architectural changes or adding new external dependencies.
Ensure all generated code is well-commented and follows standard Python best practices.

## System Architecture
The system is built around a core pattern recognition engine that identifies various types of patterns, including home series, away series, head-to-head records, and alternating win/loss sequences. It utilizes both a Random Forest model for general predictions and a Critical Pattern Prediction (CPP) logic for identifying high-confidence pattern breaks.

**UI/UX Decisions:**
- **Theme:** Perk.com inspired light theme with #BEFF50 accent, #F5F5EB background, and #14140F text.
- **Navigation:** Features 3 primary pages: Predictions, Dashboard, and Statistics.
- **Dashboard:** Includes an impressive AI visualization with LSTM + Random Forest architecture diagram, feature importance charts, and a "How AI Works" ML education section with interactive tabs explaining machine learning concepts from data to prediction.

**Technical Implementations:**
- **Data Loading:** `flashlive_loader.py` fetches live match data for all leagues via the FlashLive API. Historical data is loaded via `data_loader.py` (for NHL) and `multi_league_loader.py` (for European leagues).
- **Pattern Engine:** `pattern_engine.py` is central to identifying and analyzing patterns, calculating their weights and reliability.
- **Feature Engineering:** `feature_builder.py` creates features for machine learning models, incorporating series lengths, alternations, synergies, and deep H2H statistics.
- **Prediction Models:**
    - **Random Forest:** Implemented in `model.py`, it's a classifier with probability calibration using 112 features.
    - **LSTM Sequence Model:** A PyTorch-based LSTM neural network in `sequence_model.py` performs dual predictions for regulation (1X2) and final (Money Line) results using 16 features.
- **CPP Logic:** This logic determines pattern breaks based on predefined critical lengths and rules. Synergy (multiple patterns pointing to the same outcome) is a key factor for bet recommendations, focusing on betting against critical length series. A filter applied to odds between 2.0 and 3.5 has been shown to improve ROI for CPP predictions.
- **Database:** PostgreSQL with SQLAlchemy ORM stores predictions, user decisions, and model versions.
- **Notifications:** A Telegram bot provides real-time alerts for new predictions.
- **AutoMonitoring:** The system automatically monitors matches and updates historical data, logging all operations to the database.

**Feature Specifications:**
- **Web Interface:**
    - `/predictions`: Table of all predictions with filters.
    - `/prediction/<id>`: Detailed prediction page with patterns.
    - `/dashboard`: AI Model Dashboard with live stats and ML education.
    - `/statistics`: Model vs. manual selection comparison.
    - `/logs`: System logs with filters.

## Recent Changes Log

### [2026-01-17] Оптимизация расхода API запросов
**Проблема:** 500 запросов FlashLive API быстро расходовались
**Решение:** 
- Отключён автозапуск мониторинга при старте сервера
- Интервал мониторинга: 12 часов (вместо 4)
- Кэширование H2H данных: 24 часа
- Кэширование матчей/odds: 60 минут
**Расход:** ~1,860 запросов/месяц (достаточно для Basic плана)

### [2026-01-16] Исправление отображения коэффициентов + история матчей
**Проблема:** Коэффициенты показывались неправильно; не было истории матчей
**Решение:** 
- predicted_outcome хранит НАЗВАНИЕ команды, не 'home'/'away'
- Добавлен endpoint /v1/events/h2h для загрузки истории
- H_RESULT возвращает 'WIN'/'LOSS'/'DRAW'

### FlashLive API Structure (ВАЖНО)
- Список матчей: `GET /v1/events/list` (БЕЗ коэффициентов!)
- Коэффициенты: `GET /v1/events/odds?event_id=XXX` (отдельный запрос)
- H2H история: `GET /v1/events/h2h?event_id=XXX`
- Результат матча: `GET /v1/events/data?event_id=XXX` (STAGE_TYPE='FINISHED', HOME_SCORE_CURRENT, AWAY_SCORE_CURRENT)
- Только 5 лиг: NHL, KHL, SHL, Liiga, DEL

### [2026-01-17] Автоматическая проверка результатов
- Добавлен метод `get_match_result()` в FlashLiveLoader
- AutoMonitor теперь автоматически проверяет результаты завершённых матчей
- Обновляет поля: `actual_result`, `is_win`, `result_updated_at`

### Расчёт API запросов (Ultra план: 75,000/месяц)
- Список матчей (5 спортов): 5 × 2/день × 30 = 300
- Коэффициенты (~50 матчей): 250 × 2/день × 30 = 15,000
- Проверка результатов (~30 прогнозов): 30 × 1/день × 30 = 900
- H2H при просмотре: ~100/месяц
- **ИТОГО: ~16,300 запросов/месяц** (запас ~58,700)

## External Dependencies
- **FlashLive Sports API (RapidAPI):** Primary source for live hockey match data across 30+ leagues.
- **NHL API:** Used for NHL historical match data.
- **AllBestBets API:** Fallback source for value bets.
- **Telegram Bot API:** For sending notifications.
- **PostgreSQL:** Database for storing system data.
- **Python Libraries:** Flask, Flask-SQLAlchemy, PyTorch, Scikit-learn.