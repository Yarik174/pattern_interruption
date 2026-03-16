# Production Deployment Info

**ВАЖНО: Сохрани это, чтобы не потерять доступ!**

## Серверы

### Сервер 1: Pattern Interruption (ОСНОВНОЙ)
```
IP:       193.124.114.156
SSH User: root
SSH Pass: Y0XrsOh61Pa3rrV7O2Mjul2Q
Hostname: ruvds-8bfac
DC:       Rucloud (Королёв, Россия)
CPU:      2x2.2GHz
RAM:      4GB
Disk:     40GB SSD
```

**Что там установлено:**
- `/opt/pattern_interruption/` — основное приложение
- `/opt/footballspy/` — второе приложение
- Gunicorn слушает на `127.0.0.1:8000` (2 workers)
- PostgreSQL запущен
- Monitor запущен в dry-run режиме

**Процессы:**
```bash
ssh root@193.124.114.156 "ps aux | grep pattern"
# Выведет:
# - gunicorn (2 worker processes)
# - system_run.py monitor --dry-run --interval 3600
# - postgres connections
```

**Логи:**
```bash
ssh root@193.124.114.156 "tail -f /var/log/pattern_access.log"
ssh root@193.124.114.156 "tail -f /var/log/pattern_error.log"
```

**Управление приложением:**
```bash
# Restart app
ssh root@193.124.114.156 "systemctl restart pattern-interruption"

# Check status
ssh root@193.124.114.156 "systemctl status pattern-interruption"

# View logs
ssh root@193.124.114.156 "journalctl -u pattern-interruption -f"
```

### Сервер 2: Text-to-Speech (для другого проекта)
```
IP:       195.133.48.73
SSH User: root
SSH Pass: sd1afnuIoM
Hostname: ruvds-y7yqq
DC:       Rucloud (Королёв, Россия)
CPU:      2x2.2GHz
RAM:      4GB
Disk:     40GB SSD
```

**Что там установлено:**
- `/root/app.py` — Silero TTS + Whisper (транскрибация)
- Gunicorn слушает на `0.0.0.0:8080`
- Не используется для pattern_interruption

---

## Быстрые команды

### Подключиться к серверу
```bash
ssh root@193.124.114.156
# Пароль: 2WbTYDy0wA
```

### Проверить статус приложения
```bash
ssh root@193.124.114.156 "systemctl status pattern-interruption"
```

### Перезагрузить приложение
```bash
ssh root@193.124.114.156 "systemctl restart pattern-interruption"
```

### Обновить код из GitHub
```bash
ssh root@193.124.114.156 "cd /opt/pattern_interruption && git pull && systemctl restart pattern-interruption"
```

### Проверить логи приложения
```bash
ssh root@193.124.114.156 "journalctl -u pattern-interruption -n 50 -f"
```

### Проверить логи мониторинга
```bash
ssh root@193.124.114.156 "tail -f /var/log/pattern_scraper.log"
```

---

## Конфигурация

**Основной конфиг:** `/opt/pattern_interruption/.env`

```bash
ssh root@193.124.114.156 "cat /opt/pattern_interruption/.env"
```

**Что там должно быть:**
- `SESSION_SECRET` — для Flask sessions
- `DATABASE_URL=postgresql://pattern_user:PASSWORD@localhost/pattern_interruption`
- `RAPIDAPI_KEY` — для FlashLive API
- `TELEGRAM_BOT_TOKEN` — для уведомлений
- `TELEGRAM_CHAT_ID` — для уведомлений

---

## Мониторинг

**Monitor статус:**
```bash
ssh root@193.124.114.156 "ps aux | grep system_run"
```

**Monitor работает в dry-run режиме** (не создаёт реальные ставки, только логирует):
```bash
ssh root@193.124.114.156 "journalctl -u pattern-interruption-monitor-dryrun -f"
```

---

## Бэкап и снапшоты

На серверах отключены:
- ❌ Автопродление
- ❌ Бэкап
- ❌ Локальные сети

При необходимости — включи в панели RUVDS.

---

**ВАЖНО:** Это информация должна быть в защищённом виде!
