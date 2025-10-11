#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

# Root check
if [[ $EUID -ne 0 ]]; then
  echo "[ERROR] This script must be run as root." >&2
  exit 1
fi

trap 'echo -e "\n[ERROR] Line $LINENO failed. Exiting." >&2; exit 1' ERR

##############################################################################
# 0) Warning / Disclaimer
##############################################################################

show_disclaimer() {
  echo "**************************************************************"
  echo "WARNING: While we do not anticipate any problems, we disclaim all"
  echo "responsibility for anything that happens to your machine."
  echo ""
  echo "This script is intended for **Debian-based operating systems only**."
  echo "Running it on other distributions WILL cause unexpected issues."
  echo ""
  echo "This script is **NOT RECOMMENDED** for use on your primary machine."
  echo "For safety and best results, we strongly advise running this inside a"
  echo "clean virtual machine (VM) or LXC container environment."
  echo ""
  echo "Additionally, there is NO SUPPORT for this method; Docker is the only"
  echo "officially supported way to run Dispatcharr."
  echo "**************************************************************"
  echo ""
  echo "If you wish to proceed, type \"I understand\" and press Enter."
  read user_input
  if [ "$user_input" != "I understand" ]; then
    echo "Exiting script..."
    exit 1
  fi
}

##############################################################################
# 1) Configuration
##############################################################################

configure_variables() {
  DISPATCH_USER="dispatcharr"
  DISPATCH_GROUP="dispatcharr"
  APP_DIR="/opt/dispatcharr"
  DISPATCH_BRANCH="main"
  POSTGRES_DB="dispatcharr"
  POSTGRES_USER="dispatch"
  POSTGRES_PASSWORD="secret"
  NGINX_HTTP_PORT="9191"
  WEBSOCKET_PORT="8001"
  GUNICORN_RUNTIME_DIR="dispatcharr"
  GUNICORN_SOCKET="/run/${GUNICORN_RUNTIME_DIR}/dispatcharr.sock"
  PYTHON_BIN=$(command -v python3)
  SYSTEMD_DIR="/etc/systemd/system"
  NGINX_SITE="/etc/nginx/sites-available/dispatcharr"
}

##############################################################################
# 2) Install System Packages
##############################################################################

install_packages() {
  echo ">>> Installing system packages..."
  apt-get update
  declare -a packages=(
    git curl wget build-essential gcc libpq-dev
    python3-dev python3-venv python3-pip nginx redis-server
    postgresql postgresql-contrib ffmpeg procps streamlink
    sudo
  )
  apt-get install -y --no-install-recommends "${packages[@]}"

  if ! command -v node >/dev/null 2>&1; then
    echo ">>> Installing Node.js..."
    curl -sL https://deb.nodesource.com/setup_24.x | bash -
    apt-get install -y nodejs
  fi

  systemctl enable --now postgresql redis-server
}

##############################################################################
# 3) Create User/Group
##############################################################################

create_dispatcharr_user() {
  if ! getent group "$DISPATCH_GROUP" >/dev/null; then
    groupadd "$DISPATCH_GROUP"
  fi
  if ! id -u "$DISPATCH_USER" >/dev/null; then
    useradd -m -g "$DISPATCH_GROUP" -s /bin/bash "$DISPATCH_USER"
  fi
}

##############################################################################
# 4) PostgreSQL Setup
##############################################################################

setup_postgresql() {
  echo ">>> Checking PostgreSQL database and user..."

  db_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$POSTGRES_DB'")
  if [[ "$db_exists" != "1" ]]; then
    echo ">>> Creating database '${POSTGRES_DB}'..."
    sudo -u postgres createdb "$POSTGRES_DB"
  else
    echo ">>> Database '${POSTGRES_DB}' already exists, skipping creation."
  fi

  user_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$POSTGRES_USER'")
  if [[ "$user_exists" != "1" ]]; then
    echo ">>> Creating user '${POSTGRES_USER}'..."
    sudo -u postgres psql -c "CREATE USER $POSTGRES_USER WITH PASSWORD '$POSTGRES_PASSWORD';"
  else
    echo ">>> User '${POSTGRES_USER}' already exists, skipping creation."
  fi

  echo ">>> Granting privileges..."
  sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_DB TO $POSTGRES_USER;"
  sudo -u postgres psql -c "ALTER DATABASE $POSTGRES_DB OWNER TO $POSTGRES_USER;"
  sudo -u postgres psql -d "$POSTGRES_DB" -c "ALTER SCHEMA public OWNER TO $POSTGRES_USER;"
}

##############################################################################
# 5) Clone Dispatcharr Repository
##############################################################################

clone_dispatcharr_repo() {
  echo ">>> Installing or updating Dispatcharr in ${APP_DIR} ..."
  
  if [ ! -d "$APP_DIR" ]; then
    mkdir -p "$APP_DIR"
    chown "$DISPATCH_USER:$DISPATCH_GROUP" "$APP_DIR"
  fi

  if [ -d "$APP_DIR/.git" ]; then
    echo ">>> Updating existing Dispatcharr repo..."
    su - "$DISPATCH_USER" <<EOSU
    cd "$APP_DIR"
    git fetch origin
    git reset --hard HEAD
    git fetch origin
    git checkout $DISPATCH_BRANCH
    git pull origin $DISPATCH_BRANCH
EOSU
  else
    echo ">>> Cloning Dispatcharr repo into ${APP_DIR}..."
    rm -rf "$APP_DIR"/*
    chown "$DISPATCH_USER:$DISPATCH_GROUP" "$APP_DIR"
    su - "$DISPATCH_USER" -c "git clone -b $DISPATCH_BRANCH https://github.com/Dispatcharr/Dispatcharr.git $APP_DIR"
  fi
}

##############################################################################
# 6) Setup Python Environment
##############################################################################

setup_python_env() {
  echo ">>> Setting up Python virtual environment..."
  su - "$DISPATCH_USER" <<EOSU
cd "$APP_DIR"
$PYTHON_BIN -m venv env
source env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
EOSU
  ln -sf /usr/bin/ffmpeg "$APP_DIR/env/bin/ffmpeg"
}

##############################################################################
# 7) Build Frontend
##############################################################################

build_frontend() {
  echo ">>> Building frontend..."
  su - "$DISPATCH_USER" <<EOSU
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps
npm run build
EOSU
}

##############################################################################
# 8) Create Directories
##############################################################################

create_directories() {
  mkdir -p /data/logos
  mkdir -p /data/recordings
  mkdir -p /data/uploads/m3us
  mkdir -p /data/uploads/epgs
  mkdir -p /data/m3us
  mkdir -p /data/epgs
  mkdir -p /data/plugins
  mkdir -p /data/db

  # Needs to own ALL of /data except db
  chown -R $DISPATCH_USER:$DISPATCH_GROUP /data
  chown -R postgres:postgres /data/db
  chmod +x /data

  mkdir -p "$APP_DIR"/logo_cache
  mkdir -p "$APP_DIR"/media
  chown -R $DISPATCH_USER:$DISPATCH_GROUP "$APP_DIR"/logo_cache
  chown -R $DISPATCH_USER:$DISPATCH_GROUP "$APP_DIR"/media
}

##############################################################################
# 9) Django Migrations & Static
##############################################################################

django_migrate_collectstatic() {
  echo ">>> Running Django migrations & collectstatic..."
  su - "$DISPATCH_USER" <<EOSU
cd "$APP_DIR"
source env/bin/activate
export POSTGRES_DB="$POSTGRES_DB"
export POSTGRES_USER="$POSTGRES_USER"
export POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
export POSTGRES_HOST="localhost"
python manage.py migrate --noinput
python manage.py collectstatic --noinput
EOSU
}

##############################################################################
# 10) Configure Services & Nginx
##############################################################################

configure_services() {
  echo ">>> Creating systemd service files..."

  # Gunicorn
  cat <<EOF >${SYSTEMD_DIR}/dispatcharr.service
[Unit]
Description=Gunicorn for Dispatcharr
After=network.target postgresql.service redis-server.service

[Service]
User=${DISPATCH_USER}
Group=${DISPATCH_GROUP}
WorkingDirectory=${APP_DIR}
RuntimeDirectory=${GUNICORN_RUNTIME_DIR}
RuntimeDirectoryMode=0775
Environment="PATH=${APP_DIR}/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
Environment="POSTGRES_DB=${POSTGRES_DB}"
Environment="POSTGRES_USER=${POSTGRES_USER}"
Environment="POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
Environment="POSTGRES_HOST=localhost"
ExecStartPre=/usr/bin/bash -c 'until pg_isready -h localhost -U ${POSTGRES_USER}; do sleep 1; done'
ExecStart=${APP_DIR}/env/bin/gunicorn \\
    --workers=4 \\
    --worker-class=gevent \\
    --timeout=300 \\
    --bind unix:${GUNICORN_SOCKET} \\
    dispatcharr.wsgi:application
Restart=always
KillMode=mixed
SyslogIdentifier=dispatcharr
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
EOF

  # Celery
  cat <<EOF >${SYSTEMD_DIR}/dispatcharr-celery.service
[Unit]
Description=Celery Worker for Dispatcharr
After=network.target redis-server.service
Requires=dispatcharr.service

[Service]
User=${DISPATCH_USER}
Group=${DISPATCH_GROUP}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/env/bin"
Environment="POSTGRES_DB=${POSTGRES_DB}"
Environment="POSTGRES_USER=${POSTGRES_USER}"
Environment="POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
Environment="POSTGRES_HOST=localhost"
Environment="CELERY_BROKER_URL=redis://localhost:6379/0"
ExecStart=${APP_DIR}/env/bin/celery -A dispatcharr worker -l info
Restart=always
KillMode=mixed
SyslogIdentifier=dispatcharr-celery
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
EOF

  # Celery Beat
  cat <<EOF >${SYSTEMD_DIR}/dispatcharr-celerybeat.service
[Unit]
Description=Celery Beat Scheduler for Dispatcharr
After=network.target redis-server.service
Requires=dispatcharr.service

[Service]
User=${DISPATCH_USER}
Group=${DISPATCH_GROUP}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/env/bin"
Environment="POSTGRES_DB=${POSTGRES_DB}"
Environment="POSTGRES_USER=${POSTGRES_USER}"
Environment="POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
Environment="POSTGRES_HOST=localhost"
Environment="CELERY_BROKER_URL=redis://localhost:6379/0"
ExecStart=${APP_DIR}/env/bin/celery -A dispatcharr beat -l info
Restart=always
KillMode=mixed
SyslogIdentifier=dispatcharr-celerybeat
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
EOF

  # Daphne
  cat <<EOF >${SYSTEMD_DIR}/dispatcharr-daphne.service
[Unit]
Description=Daphne for Dispatcharr (ASGI/WebSockets)
After=network.target
Requires=dispatcharr.service

[Service]
User=${DISPATCH_USER}
Group=${DISPATCH_GROUP}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/env/bin"
Environment="POSTGRES_DB=${POSTGRES_DB}"
Environment="POSTGRES_USER=${POSTGRES_USER}"
Environment="POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
Environment="POSTGRES_HOST=localhost"
ExecStart=${APP_DIR}/env/bin/daphne -b 0.0.0.0 -p ${WEBSOCKET_PORT} dispatcharr.asgi:application
Restart=always
KillMode=mixed
SyslogIdentifier=dispatcharr-daphne
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
EOF

  echo ">>> Creating Nginx config..."
  cat <<EOF >/etc/nginx/sites-available/dispatcharr.conf
server {
    listen ${NGINX_HTTP_PORT};
    location / {
        include proxy_params;
        proxy_pass http://unix:${GUNICORN_SOCKET};
    }
    location /static/ {
        alias ${APP_DIR}/static/;
    }
    location /assets/ {
        alias ${APP_DIR}/frontend/dist/assets/;
    }
    location /media/ {
        alias ${APP_DIR}/media/;
    }
    location /ws/ {
        proxy_pass http://127.0.0.1:${WEBSOCKET_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header Host \$host;
    }
}
EOF

  ln -sf /etc/nginx/sites-available/dispatcharr.conf /etc/nginx/sites-enabled/dispatcharr.conf
  [ -f /etc/nginx/sites-enabled/default ] && rm /etc/nginx/sites-enabled/default
  nginx -t
  systemctl restart nginx
  systemctl enable nginx
}

##############################################################################
# 11) Start Services
##############################################################################

start_services() {
  echo ">>> Enabling and starting services..."
  systemctl daemon-reexec
  systemctl daemon-reload
  systemctl enable --now dispatcharr dispatcharr-celery dispatcharr-celerybeat dispatcharr-daphne
}

##############################################################################
# 12) Summary
##############################################################################

show_summary() {
  server_ip=$(ip route get 1 | awk '{print $7; exit}')
  cat <<EOF
=================================================
Dispatcharr installation (or update) complete!
Nginx is listening on port ${NGINX_HTTP_PORT}.
Gunicorn socket: ${GUNICORN_SOCKET}.
WebSockets on port ${WEBSOCKET_PORT} (path /ws/).

You can check logs via:
  sudo journalctl -u dispatcharr -f
  sudo journalctl -u dispatcharr-celery -f
  sudo journalctl -u dispatcharr-celerybeat -f
  sudo journalctl -u dispatcharr-daphne -f

Visit the app at:
  http://${server_ip}:${NGINX_HTTP_PORT}
=================================================
EOF
}

##############################################################################
# Run Everything
##############################################################################

main() {
  show_disclaimer
  configure_variables
  install_packages
  create_dispatcharr_user
  setup_postgresql
  clone_dispatcharr_repo
  setup_python_env
  build_frontend
  create_directories
  django_migrate_collectstatic
  configure_services
  start_services
  show_summary
}

main "$@"