#!/bin/bash
# =============================================================================
# Pattern Interruption — Setup Script for Ubuntu 22.04 LTS
# RUVDS VPS: 2x2.2GHz, 4GB RAM, 40GB SSD
#
# Usage:
#   chmod +x setup.sh
#   sudo ./setup.sh
# =============================================================================

set -e

APP_NAME="pattern-interruption"
APP_DIR="/opt/pattern_interruption"
APP_USER="appuser"
REPO_URL="https://github.com/Yarik174/pattern-interruption.git"
DB_NAME="pattern_interruption"
DB_USER="pattern_user"
DB_PASS=$(openssl rand -hex 16)
GUNICORN_PORT=8000

echo "=============================="
echo " Pattern Interruption Deploy  "
echo "=============================="

# --- 1. System packages ---
echo "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip \
    nginx \
    postgresql postgresql-contrib \
    git \
    curl \
    openssl \
    build-essential \
    libpq-dev

# --- 2. Create app user ---
echo "[2/8] Creating app user..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /bin/false "$APP_USER"
fi

# --- 3. PostgreSQL setup ---
echo "[3/8] Setting up PostgreSQL..."
systemctl start postgresql
systemctl enable postgresql

sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename = '$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
    sudo -u postgres createdb "$DB_NAME" -O "$DB_USER"

echo "  DB User:     $DB_USER"
echo "  DB Name:     $DB_NAME"
echo "  DB Password: $DB_PASS  <-- сохрани в .env!"

# --- 4. Clone repo ---
echo "[4/8] Cloning repository..."
if [ -d "$APP_DIR" ]; then
    echo "  Directory exists, pulling latest..."
    cd "$APP_DIR"
    git pull
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# --- 5. Python virtualenv + dependencies ---
echo "[5/8] Installing Python dependencies (may take 5-10 min for PyTorch)..."
cd "$APP_DIR"
python3.11 -m venv venv
chown -R "$APP_USER":"$APP_USER" venv

sudo -u "$APP_USER" venv/bin/pip install --upgrade pip -q
sudo -u "$APP_USER" venv/bin/pip install -r requirements.txt

# --- 6. .env file ---
echo "[6/8] Creating .env file..."
SESSION_SECRET=$(openssl rand -hex 32)

if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" <<EOF
SESSION_SECRET=$SESSION_SECRET
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost/$DB_NAME

# API Keys (заполни вручную)
RAPIDAPI_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
APISPORTS_KEY=
ALLBESTBETS_API_TOKEN=
EOF
    chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo "  .env создан. Заполни API ключи: $APP_DIR/.env"
else
    echo "  .env уже существует, пропускаем."
fi

# --- 7. Systemd service ---
echo "[7/8] Installing systemd service..."
cp "$APP_DIR/deploy/pattern-interruption.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable pattern-interruption

# --- 8. Nginx ---
echo "[8/8] Configuring Nginx..."
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/pattern-interruption
ln -sf /etc/nginx/sites-available/pattern-interruption /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx

# --- Start services ---
echo ""
echo "Starting services..."
systemctl start postgresql
systemctl start pattern-interruption
systemctl restart nginx

# --- Cron jobs ---
echo "Setting up cron jobs..."
CRON_FILE="/etc/cron.d/pattern-interruption"
cat > "$CRON_FILE" <<EOF
# Pattern Interruption scheduled jobs
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Daily scraping at 06:00
0 6 * * * $APP_USER $APP_DIR/venv/bin/python $APP_DIR/scripts/scrape_all_leagues.py hockey >> /var/log/pattern_scraper.log 2>&1

# Weekly model retraining on Sunday at 03:00
0 3 * * 0 $APP_USER $APP_DIR/venv/bin/python $APP_DIR/main.py >> /var/log/pattern_train.log 2>&1
EOF
chmod 644 "$CRON_FILE"

echo ""
echo "=============================="
echo " Deploy Complete!             "
echo "=============================="
echo ""
echo "Status check:"
systemctl status pattern-interruption --no-pager | head -5
echo ""
echo "Next steps:"
echo "  1. Edit API keys: nano $APP_DIR/.env"
echo "  2. Restart app:   systemctl restart pattern-interruption"
echo "  3. View logs:     journalctl -u pattern-interruption -f"
echo "  4. Test:          curl http://localhost:$GUNICORN_PORT"
echo ""
echo "  DB Password (сохрани!): $DB_PASS"
