# Hockey Pattern Prediction System

## Overview
Production-ready hockey prediction system monitoring betting odds via FlashLive Sports API (RapidAPI) for 5 leagues (NHL, KHL, SHL, Liiga, DEL). System automatically generates predictions 1-2 days before matches using Random Forest + CPP logic + LSTM, sends Telegram notifications, and provides web interface with Perk.com-inspired light theme.

**Current Status:** Fully automated system with automatic result verification.

## User Preferences
- **Стиль общения:** коротко, прямо, неформально
- Командный тон, 2-5 слов — но отвечать развёрнуто
- Пользователь новичок в разработке — объяснять логику и ход мысли
- Сразу к делу, без вступлений и расшаркиваний
- Общаться на равных — без извинений, заискиваний и "ты прав"
- Жёсткость и конкретика, не размазывать
- Iterative development with regular progress updates
- Ask confirmation before major architectural changes
- Well-commented code following Python best practices
- Verify facts before accepting — accuracy over quick agreement

## System Architecture

### Core Components
1. **Pattern Engine** (`pattern_engine.py`) — identifies home/away series, H2H records, alternating win/loss sequences
2. **Feature Builder** (`feature_builder.py`) — creates 112 features for ML models
3. **Prediction Models:**
   - Random Forest (probability calibration, 112 features)
   - LSTM Neural Network (PyTorch, dual predictions for regulation/final)
   - CPP Logic (Critical Pattern Prediction for high-confidence breaks)

### Data Architecture (ВАЖНО!)
| Компонент | Источник | Назначение |
|-----------|----------|------------|
| MultiLeaguePatternEngine | Кэш исторических матчей | Обучение моделей (6,632 матча) |
| FlashLive H2H API | `/v1/events/h2h` | Отображение последних 5 матчей в UI |
| FlashLive Events | `/v1/events/list` | Список предстоящих матчей |
| FlashLive Odds | `/v1/events/odds` | Коэффициенты (отдельный запрос!) |
| FlashLive Data | `/v1/events/data` | Результаты завершённых матчей |

### Key Data Fields
- `predicted_outcome` — хранит **НАЗВАНИЕ КОМАНДЫ** (например "Anaheim Ducks"), НЕ 'home'/'away'
- `patterns_data.bet_on` — хранит 'home'/'away' флаг
- `is_win` — результат прогноза (True/False/None)
- `flashlive_event_id` — ID матча для API запросов

### Automation Pipeline
1. **Мониторинг** (каждые 12 часов):
   - Загрузка предстоящих матчей через FlashLive API
   - Генерация прогнозов через RF + LSTM + CPP
   - Отправка уведомлений в Telegram
2. **Проверка результатов** (автоматически):
   - Находит прогнозы с `is_win == None` и прошедшей датой
   - Запрашивает результат через `/v1/events/data`
   - Обновляет `actual_result`, `is_win`, `result_updated_at`

## FlashLive API Reference

### Endpoints
| Endpoint | Параметры | Возвращает |
|----------|-----------|------------|
| `/v1/events/list` | sport_id, timezone | Список матчей БЕЗ коэффициентов |
| `/v1/events/odds` | event_id, odds_source | Коэффициенты для конкретного матча |
| `/v1/events/h2h` | event_id | Последние 5 матчей каждой команды |
| `/v1/events/data` | event_id | Детали матча, счёт, статус |

### Sport IDs
- Hockey: sport_id = 4
- Поддерживаемые лиги: NHL, KHL, SHL, Liiga, DEL

### API Budget (Ultra Plan: 75,000/month)
| Операция | Запросов/день | В месяц |
|----------|--------------|---------|
| Список матчей (5 лиг) | 10 | 300 |
| Коэффициенты (~50 матчей) | 500 | 15,000 |
| Проверка результатов | 30 | 900 |
| H2H при просмотре | ~3 | 100 |
| **ИТОГО** | | **~16,300** |

**Запас:** ~58,700 запросов для расширения на другие виды спорта.

## UI/UX Design
- **Theme:** Perk.com inspired — #BEFF50 accent, #F5F5EB background, #14140F text
- **Pages:**
  - `/predictions` — таблица прогнозов с фильтрами
  - `/prediction/<id>` — детали с паттернами и историей H2H
  - `/dashboard` — AI визуализация, архитектура моделей
  - `/statistics` — расширенная аналитика точности модели
  - `/logs` — системные логи

### Страница статистики (/statistics)
- **Общая статистика:** W/L, Win Rate, ROI, pending прогнозы
- **По лигам:** NHL, KHL, SHL, Liiga, DEL с цветовой индикацией
- **По паттернам:** какие типы паттернов работают лучше
- **По уверенности:** точность на каждом уровне 1-10
- **История по месяцам:** тренды, принятые ставки
- **График Chart.js:** динамика Win Rate по месяцам

### Формула ROI
```
profit = Σ(odds_win - 1) - N_losses
ROI = (profit / N_total) × 100%
```

## Key Files
| Файл | Назначение |
|------|------------|
| `src/flashlive_loader.py` | API клиент для FlashLive |
| `src/odds_monitor.py` | AutoMonitor, проверка результатов |
| `src/prediction_service.py` | Генерация прогнозов |
| `src/pattern_engine.py` | Анализ паттернов |
| `src/multi_league_loader.py` | Загрузка исторических данных |
| `models.py` | SQLAlchemy модели (Prediction, etc.) |
| `src/routes.py` | Flask маршруты |

## Recent Changes

### [2026-01-17] Трёхстороннее сравнение статистики
- **Model AI** — все прогнозы модели с Win Rate и ROI
- **RL-агент** — только BET рекомендации, SKIP показывает спасённые ставки
- **Manual** — принятые пользователем прогнозы
- Сохранение `rl_recommendation`, `rl_confidence`, `rl_comment` при создании прогноза
- RL-агент генерирует текстовые комментарии с объяснением решений

### [2026-01-17] RL-агент для meta-стратегии
- **DQN-агент** для принятия решений BET/SKIP
- State space: 8 признаков (confidence, odds, серии, bankroll)
- Обучен на 20k+ исторических матчей
- Интегрирован в UI страницы прогноза
- Файлы: `src/rl_agent.py`, `src/rl_trainer.py`

### [2026-01-17] Отказоустойчивость и визуализация ROI
- **Retry логика** с exponential backoff (1с→2с→4с) для FlashLive API
- **Telegram алерты** при критических сбоях API (после 3 неудачных попыток)
- **Накопительный график ROI** на странице статистики с цветовой индикацией
- Динамическая привязка TelegramNotifier через `set_telegram_notifier()`

### [2026-01-17] Автоматическая проверка результатов
- Добавлен `get_match_result()` в FlashLiveLoader
- AutoMonitor автоматически проверяет завершённые матчи
- Обновляет `is_win` на основе сравнения predicted_outcome с победителем

### [2026-01-17] Оптимизация API запросов
- Интервал мониторинга: 12 часов
- Кэширование H2H: 24 часа, матчей/odds: 60 минут

## External Dependencies
- **FlashLive Sports API (RapidAPI)** — основной источник данных
- **NHL API** — исторические данные NHL
- **AllBestBets API** — fallback для value bets
- **Telegram Bot API** — уведомления
- **PostgreSQL** — база данных
- **Python:** Flask, SQLAlchemy, PyTorch, Scikit-learn

## Future Plans
- Расширение на 5 видов спорта (25 лиг) — бюджет API позволяет
- Улучшение точности моделей на основе накопленных результатов
