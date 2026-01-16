# Hockey Pattern Prediction System

## Overview
The Hockey Pattern Prediction System is a multi-league system designed to predict outcomes of hockey matches across several leagues (NHL, KHL, SHL, Liiga, DEL). It analyzes historical match data to identify recurring patterns in results. The core idea is that when a pattern reaches a critical length (e.g., 5+ repetitions), it has a high probability of breaking. The system aims to provide profitable betting recommendations based on these pattern breaks and calculated Expected Value (EV).

## User Preferences
I prefer clear and concise explanations.
I value iterative development and regular updates on progress.
Please ask for confirmation before implementing significant architectural changes or adding new external dependencies.
Ensure all generated code is well-commented and follows standard Python best practices.

## Agent Documentation Rules (ОБЯЗАТЕЛЬНО)
При каждом значимом изменении обновляй этот файл:

### Что фиксировать:
1. **API Structure** — эндпоинты, формат ответа, обязательные параметры
2. **Баги и решения** — что сломалось и как починили
3. **Ограничения** — что НЕ работает, лимиты API
4. **Важные выводы** — неочевидные факты (например: "FlashLive list НЕ даёт odds")
5. **Дизайн-решения** — почему выбрали такой подход, а не другой
6. **Конфигурация** — порты, таймауты, кэширование, важные настройки
7. **Workarounds** — обходные пути когда что-то не работает напрямую
8. **Структура данных** — что хранится в БД, формат моделей

### Формат записи:
```
### [Дата] Название
**Проблема:** что было не так
**Решение:** что сделали
**Важно помнить:** ключевой вывод
```

### Когда обновлять:
- После фикса бага
- После интеграции нового API
- После обнаружения ограничения
- После изменения архитектуры

## Recent Changes (2026-01-16)

### FlashLive API Integration (UPDATED)
**ВАЖНО: FlashLive API Structure**
- Список матчей: `GET /v1/events/list` (БЕЗ коэффициентов!)
- Коэффициенты: `GET /v1/events/odds?event_id=XXX` (отдельный вызов для каждого матча)
- Ответ odds содержит: `DATA[].PERIODS[].GROUPS[].MARKETS[].ODD_CELL_FIRST/SECOND/THIRD.VALUE`
- Bookmaker: bet365, Unibet и другие

**Replaced API-Sports with FlashLive Sports API (via RapidAPI)**
- API-Sports free plan doesn't support season 2025
- FlashLive provides hockey matches across 30+ leagues
- **Поддерживаемые лиги (только 5):** NHL, KHL, SHL, Liiga, DEL
- RapidAPI free tier available

### Features:
1. **PostgreSQL Database Integration** - Tables for predictions, user decisions, model versions, system logs
2. **FlashLive API Integration** - Real-time match data for all hockey leagues (requires RAPIDAPI_KEY)
3. **Telegram Bot Notifications** - Alerts when new predictions are generated
4. **AutoMonitor** - Автоматический мониторинг каждые 4 часа:
   - Проверка матчей через FlashLive API
   - Обновление исторических данных раз в день
   - Логирование всех операций в БД
5. **Web Interface:**
   - `/predictions` - Table of all predictions with filters
   - `/prediction/<id>` - Detailed prediction page with patterns
   - `/dashboard` - AI Model Dashboard with live stats
   - `/statistics` - Model vs manual selection comparison
   - `/logs` - System logs with filters (data_update, monitoring, error)

### Key Files:
- `src/flashlive_loader.py` - FlashLive Sports API client (primary source)
- `src/allbestbets_loader.py` - AllBestBets API client (fallback)
- `src/apisports_odds_loader.py` - API-Sports client (historical data only)
- `src/telegram_bot.py` - Telegram notification system
- `src/odds_monitor.py` - Background odds monitoring
- `src/routes.py` - Flask routes for web interface

## System Architecture
The system is built around a core pattern recognition engine that identifies various types of patterns, including home series, away series, head-to-head records, and alternating win/loss sequences. It utilizes both a Random Forest model for general predictions and a Critical Pattern Prediction (CPP) logic for identifying high-confidence pattern breaks.

**Technical Implementations:**
- **Data Loading:** `data_loader.py` handles NHL data via an API with caching. `flashlive_loader.py` fetches live match data for all leagues via FlashLive API (RapidAPI). `multi_league_loader.py` used for historical European leagues data.
- **Pattern Engine:** `pattern_engine.py` is central to identifying and analyzing patterns, including calculating their "weights" or reliability.
- **Feature Engineering:** `feature_builder.py` creates features for machine learning models, incorporating series lengths, alternations, synergies, and deep H2H statistics.
- **Prediction Models:**
    - **Random Forest:** `model.py` implements a Random Forest classifier with probability calibration. It uses 112 features and achieves an accuracy of ~54.44%.
    - **LSTM Sequence Model:** `sequence_model.py` uses a PyTorch-based LSTM neural network with dual prediction for regulation (1X2) and final (Money Line) results.
- **CPP Logic:** This logic determines pattern breaks based on predefined critical lengths and rules. Synergy (multiple patterns pointing to the same outcome) is a key factor for bet recommendations.
- **Database:** PostgreSQL with SQLAlchemy ORM for storing predictions, user decisions, and model versions.
- **Notifications:** Telegram bot for real-time alerts.

## LSTM Sequence Model (обновлено 2026-01-15)

### Dual Prediction
Модель предсказывает два типа результатов:
1. **Regulation (1X2)** — основное время, ничья возможна
2. **Final (Money Line)** — включая овертайм, всегда победитель

### Признаки (16):
goals_scored, goals_conceded, won, home_game, overtime, goal_diff, total_goals, won_regulation, won_overtime, draw_regulation, home_odds, away_odds, implied_prob, **is_underdog**, **won_as_underdog**, **odds_diff**

### Результаты обучения (v2 с odds features):
| Тип прогноза | Accuracy | Распределение |
|--------------|----------|---------------|
| Regulation (1X2) | 44.68% | Home=42.8%, Away=35.1%, Draw=22.1% |
| Final (Money Line) | **56.22%** | Home=53.9%, Away=46.1% |

### ROI на валидации:
| Тип ставки | Ставок | Win Rate | ROI |
|------------|--------|----------|-----|
| Money Line | 371 | **64.2%** | **-0.04%** |
| 1X2 | 111 | 56.8% | -32.96% |

**Улучшение:** Новые odds-based features улучшили Money Line ROI с -3.24% до **-0.04%** (почти безубыточно!)

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

### CPP Odds Filter (2026-01-15)
**Фильтр по коэффициентам улучшает ROI:**

| Фильтр odds | Ставок | Win Rate | ROI |
|-------------|--------|----------|-----|
| Без фильтра | 135 | 44.4% | +20.1% |
| **[2.0, 3.5]** | 92 | **47.8%** | **+25.1%** |
| [1.7, ∞] | 132 | 44.7% | +21.8% |

**Стратегия:** Ставить только когда коэффициент от 2.0 до 3.5 — "небольшой аутсайдер" (не слишком фаворит, не слишком рискованно).

### Вывод
- **Money Line лучше 1X2** — ничья в 1X2 = проигрыш
- **CPP паттерны дают +20-25% ROI** (с odds filter [2.0, 3.5])
- LSTM модель почти безубыточна (-0.04% ROI)
- **CPP + Odds Filter = основная стратегия**

## External Dependencies
- **FlashLive Sports API (RapidAPI):** Primary source for all hockey matches (281+ matches, 30+ leagues)
- **NHL API:** For NHL historical match data (nhle.com API)
- **AllBestBets API:** Fallback source for valuebets
- **Telegram Bot API:** For notifications
- **Historical odds:** data/odds/sbro-*.csv (2016-2023, 5320 matches)
- **Flask, Flask-SQLAlchemy, PyTorch, Scikit-learn:** Core frameworks

## Environment Variables (Secrets)
- `DATABASE_URL` - PostgreSQL connection string (auto-configured)
- `SESSION_SECRET` - Flask session secret (required)
- `RAPIDAPI_KEY` - FlashLive Sports API key (required for live predictions)
- `ALLBESTBETS_API_TOKEN` - AllBestBets API token (optional fallback)
- `ALLBESTBETS_FILTER_ID` - AllBestBets filter ID (optional)
- `TELEGRAM_BOT_TOKEN` - Telegram bot token (optional)
- `TELEGRAM_CHAT_ID` - Telegram chat ID for notifications (optional)

## FlashLive API (2026-01-15)
**Primary data source for live match data**

Features:
- 281+ hockey matches available
- 30+ leagues (NHL, KHL, SHL, Liiga, DEL, AHL, OHL, WHL, VHL, MHL...)
- Real-time updates every 5 minutes
- 5-minute cache to reduce API calls
- RapidAPI free tier available

Endpoints used:
- `/v1/sports/list` - Get hockey sport_id
- `/v1/events/list` - Get matches by day

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

## CPP Betting Strategy (Critical Pattern Prediction)

**Ключевой принцип:** Система ставит на ПРЕРЫВАНИЕ серии, а не на её продолжение.

**Когда делаем ставку:**
- Паттерн достиг критической длины (домашняя серия ≥4, гостевая ≥3, общая ≥5)
- Синергия ≥2 (минимум 2 паттерна указывают на одну команду)
- Ставим на команду, которая ПРЕРВЁТ эти серии

**Пример логики:**
- Calgary: 5 домашних побед подряд → серия достигла критической длины
- Calgary: 4 победы в H2H дома → серия достигла критической длины  
- **Вывод:** Ставим на Edmonton (прерывание серий Calgary)

**Подробная документация:** [docs/theory.md](docs/theory.md)

## UI Design (2026-01-15)
- **Theme:** Perk.com inspired light theme
- **Colors:** #BEFF50 accent, #F5F5EB background, #14140F text
- **Navigation:** 3 pages (Predictions → Dashboard → Statistics)
- **Dashboard:** Impressive AI visualization with:
  - LSTM + Random Forest architecture diagram
  - 112 features, 5320 matches, 847K parameters
  - Feature Importance chart (top-8 features with pattern visualization)
  - CPP Logic profitable patterns (+64.3% ROI)
  - Live inference stats
  - **NEW: "Как работает AI" — ML Education Section** with 8 interactive tabs:
    1. Зачем ML? — цель машинного обучения
    2. Данные — 5320 матчей, что записываем
    3. Признаки — 112 features, группы (серии, H2H, форма, odds, календарь)
    4. Обучение — train/test split, переобучение
    5. Random Forest — 100 деревьев, голосование
    6. LSTM — нейросеть с памятью, 10 матчей
    7. CPP Правила — экспертные правила, синергия
    8. Пример — Edmonton @ Calgary от данных к прогнозу
