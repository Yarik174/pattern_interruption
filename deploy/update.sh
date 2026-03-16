#!/bin/bash
# =============================================================================
# Pattern Interruption — Safe Update Script
# Backs up .env before pulling, restores if lost.
#
# Usage:
#   ssh root@193.124.114.156 "bash /opt/pattern_interruption/deploy/update.sh"
# =============================================================================

set -e

APP_DIR="/opt/pattern_interruption"
ENV_FILE="$APP_DIR/.env"
ENV_BACKUP="$APP_DIR/.env.backup"

cd "$APP_DIR"

# --- Backup .env ---
if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$ENV_BACKUP"
    echo "[✓] .env backed up"
else
    echo "[!] No .env found — will need manual setup"
fi

# --- Pull latest code ---
echo "[*] Pulling latest code..."
git pull

# --- Verify .env survived ---
if [ ! -f "$ENV_FILE" ]; then
    echo "[!] .env was deleted by git pull — restoring from backup"
    cp "$ENV_BACKUP" "$ENV_FILE"
elif ! grep -q "FLASH_API_PROXY_URL" "$ENV_FILE"; then
    echo "[!] .env missing FLASH_API_PROXY_URL — restoring from backup"
    cp "$ENV_BACKUP" "$ENV_FILE"
fi

# --- Validate critical vars ---
MISSING=""
for var in RAPIDAPI_KEY FLASH_API_PROXY_URL TELEGRAM_BOT_TOKEN; do
    val=$(grep "^${var}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
    if [ -z "$val" ]; then
        MISSING="$MISSING $var"
    fi
done

if [ -n "$MISSING" ]; then
    echo "[WARNING] Empty vars in .env:$MISSING"
    echo "  Edit: nano $ENV_FILE"
fi

# --- Run pending migrations ---
echo "[*] Running migrations..."
for f in "$APP_DIR"/migrations/*.sql; do
    [ -f "$f" ] || continue
    echo "  Applying: $(basename $f)"
    sudo -u postgres psql -d pattern_interruption -f "$f" 2>&1 | grep -v "already exists" || true
done

# --- Restart ---
echo "[*] Restarting app..."
systemctl restart pattern-interruption
sleep 2

if systemctl is-active --quiet pattern-interruption; then
    echo "[✓] App is running"
else
    echo "[FAIL] App failed to start! Check: journalctl -u pattern-interruption -n 30"
    exit 1
fi

echo "[✓] Update complete"
