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
# 0) Locales & Warning / Disclaimer
##############################################################################

setup_locales() {
  echo ">>> Setting up locales..."
  apt-get update
  apt-get install -y locales
  sed -i '/en_US.UTF-8 UTF-8/s/^# //g' /etc/locale.gen
  locale-gen
  update-locale LANG=en_US.UTF-8
  export LANG=en_US.UTF-8
  export LC_ALL=en_US.UTF-8
}

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
  UWSGI_RUNTIME_DIR="dispatcharr"
  UWSGI_SOCKET="/run/${UWSGI_RUNTIME_DIR}/dispatcharr.sock"
  SYSTEMD_DIR="/etc/systemd/system"
}

# Helper: pick the first candidate package that exists in apt repos
pick_candidate() {
  local cand info candidate
  for cand in "$@"; do
    info=$(apt-cache policy "$cand" 2>/dev/null || true)
    candidate=$(printf '%s' "$info" | awk '/Candidate:/ {print $2; exit}')
    if [ -n "$candidate" ] && [ "$candidate" != "(none)" ]; then
      printf '%s' "$cand"
      return 0
    fi
  done
  return 1
}

# Resolve a list of package candidate entries into installable package names.
# Each entry may contain alternatives separated by '|', e.g. 'libpcre3-dev|libpcre2-dev'
resolve_packages() {
  local entry
  local alts
  local alt
  local resolved=()
  for entry in "$@"; do
    IFS='|' read -r -a alts <<<"$entry"
    alt=$(pick_candidate "${alts[@]}" 2>/dev/null || true)
    if [ -n "$alt" ]; then
      resolved+=("$alt")
    else
      echo "[WARN] No available candidate for package group: $entry" >&2
    fi
  done
  printf '%s\n' "${resolved[@]}"
}

##############################################################################
# 2) Install System Packages
##############################################################################

install_packages() {
  echo ">>> Installing system packages..."
  # Refresh package lists before probing availability
  apt-get update

  # Candidate package groups (use '|' to separate alternatives)
  package_candidates=(
    'git'
    'curl'
    'wget'
    'build-essential'
    'gcc'
    'libpq-dev'
    'libpcre3-dev|libpcre2-dev|pcre3-dev'
    'python3-dev|python3.13-dev'
    'libssl-dev'
    'pkg-config'
    'nginx'
    'redis-server'
    'postgresql'
    'postgresql-contrib'
    'ffmpeg'
    'procps'
    'streamlink'
    'sudo'
  )

  # Resolve candidates to actual installable package names
  mapfile -t packages < <(resolve_packages "${package_candidates[@]}")

  if [ "${#packages[@]}" -eq 0 ]; then
    echo "[ERROR] No installable packages found. Aborting." >&2
    exit 1
  fi

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
  echo ">>> Waiting for PostgreSQL to accept connections..."
  until pg_isready -h /var/run/postgresql >/dev/null 2>&1; do
    sleep 1
  done

  echo ">>> Checking PostgreSQL database and user..."

  db_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$POSTGRES_DB'")
  if [[ "$db_exists" != "1" ]]; then
    echo ">>> Creating database '${POSTGRES_DB}' with UTF8 encoding..."
    sudo -u postgres createdb -E UTF8 "$POSTGRES_DB"
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
  echo ">>> Setting up Python virtual environment with UV (Python 3.13)..."

  su - "$DISPATCH_USER" <<EOSU
  set -euo pipefail
  cd "$APP_DIR"
  export PATH="\$HOME/.local/bin:\$PATH"

  command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh

  rm -rf env
  # uv creates the venv with a managed Python 3.13 (auto-downloads if missing),
  # avoiding system Python version mismatches on Debian 12 / Ubuntu 24.04.
  uv venv --python 3.13 env

  export UV_PROJECT_ENVIRONMENT="$APP_DIR/env"
  uv sync --no-dev
EOSU

  ln -sf /usr/bin/ffmpeg "$APP_DIR/env/bin/ffmpeg"
}


##############################################################################
# 6.1) Ensure Environment File
##############################################################################

ensure_env_file() {
  echo ">>> Ensuring DJANGO_SECRET_KEY exists in ${APP_DIR}/.env..."
  su - "$DISPATCH_USER" <<EOSU
set -euo pipefail
cd "$APP_DIR"
touch .env
chmod 600 .env
if ! grep -q '^DJANGO_SECRET_KEY=' .env; then
  key=\$(env/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(64))
PY
)
  echo "DJANGO_SECRET_KEY=\$key" >> .env
fi
EOSU
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
set -euo pipefail
cd "$APP_DIR"
set -a
source .env
set +a
export POSTGRES_DB="$POSTGRES_DB"
export POSTGRES_USER="$POSTGRES_USER"
export POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
export POSTGRES_HOST="localhost"
env/bin/python manage.py migrate --noinput
env/bin/python manage.py collectstatic --noinput
EOSU
}


##############################################################################
# 10) Configure Services & Nginx
##############################################################################

configure_services() {
  echo ">>> Creating systemd service files..."

  # uWSGI config
  cat <<EOF >${APP_DIR}/uwsgi-debian.ini
[uwsgi]
chdir = ${APP_DIR}
module = dispatcharr.wsgi:application
virtualenv = ${APP_DIR}/env
master = true
workers = 4
socket = ${UWSGI_SOCKET}
chmod-socket = 666
vacuum = true
die-on-term = true
gevent = 100
gevent-early-monkey-patch = true
import = dispatcharr.gevent_patch
lazy-apps = true
buffer-size = 65536
socket-timeout = 600
thunder-lock = true
EOF

  chown ${DISPATCH_USER}:${DISPATCH_GROUP} ${APP_DIR}/uwsgi-debian.ini

  # uWSGI
  cat <<EOF >${SYSTEMD_DIR}/dispatcharr.service
[Unit]
Description=uWSGI for Dispatcharr
After=network.target postgresql.service redis-server.service

[Service]
User=${DISPATCH_USER}
Group=${DISPATCH_GROUP}
WorkingDirectory=${APP_DIR}
RuntimeDirectory=${UWSGI_RUNTIME_DIR}
RuntimeDirectoryMode=0775
EnvironmentFile=/opt/dispatcharr/.env
Environment="PATH=${APP_DIR}/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
Environment="POSTGRES_DB=${POSTGRES_DB}"
Environment="POSTGRES_USER=${POSTGRES_USER}"
Environment="POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
Environment="POSTGRES_HOST=localhost"
ExecStartPre=/usr/bin/bash -c 'until pg_isready -h localhost -U ${POSTGRES_USER}; do sleep 1; done'
ExecStart=${APP_DIR}/env/bin/uwsgi --ini ${APP_DIR}/uwsgi-debian.ini
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
EnvironmentFile=/opt/dispatcharr/.env
Environment="PATH=${APP_DIR}/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
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
EnvironmentFile=/opt/dispatcharr/.env
Environment="PATH=${APP_DIR}/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
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
EnvironmentFile=/opt/dispatcharr/.env
Environment="PATH=${APP_DIR}/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
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
    client_max_body_size 0;

    location / {
        include uwsgi_params;
        uwsgi_param HTTP_X_REAL_IP \$remote_addr;
        uwsgi_read_timeout 600;
        uwsgi_send_timeout 600;
        uwsgi_pass unix:${UWSGI_SOCKET};
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
uWSGI socket: ${UWSGI_SOCKET}.
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
  setup_locales
  show_disclaimer
  configure_variables
  install_packages
  create_dispatcharr_user
  setup_postgresql
  clone_dispatcharr_repo
  setup_python_env
  build_frontend
  create_directories
  ensure_env_file
  django_migrate_collectstatic
  configure_services
  start_services
  show_summary
}

main "$@"