#!/usr/bin/env bash

##############################################################################
# FreeBSD Installation Script for Dispatcharr
#
# WARNING: While we do not anticipate any problems, we disclaim all
# responsibility for anything that happens to your machine.
#
# This script is intended for **FreeBSD 14.x/15.x only**.
# This script is **NOT RECOMMENDED** for use on your primary machine.
# For safety and best results, we strongly advise running this inside a
# clean virtual machine (VM) or jail environment.
#
# There is NO SUPPORT for this method; Docker is the only officially
# supported way to run Dispatcharr.
##############################################################################

set -e
set -u
set -o pipefail
IFS=$'\n\t'

# Root check
if [ "$(id -u)" -ne 0 ]; then
  echo "[ERROR] This script must be run as root." >&2
  exit 1
fi

trap 'echo -e "\n[ERROR] Line $LINENO failed. Exiting." >&2; exit 1' ERR

##############################################################################
# 0) Warning / Disclaimer
##############################################################################

show_disclaimer() {
  cat <<'EOF'
**************************************************************

WARNING: While we do not anticipate any problems, we disclaim all
responsibility for anything that happens to your machine.

This script is intended for **FreeBSD 14.x/15.x only**.
Running it on other operating systems WILL cause unexpected issues.

This script is **NOT RECOMMENDED** for use on your primary machine.
For safety and best results, we strongly advise running this inside a
clean virtual machine (VM) or jail environment.

Additionally, there is NO SUPPORT for this method; Docker is the only
officially supported way to run Dispatcharr.

**************************************************************
EOF

  # Skip interactive prompt if DISPATCHARR_AUTO_CONFIRM is set
  if [ "${DISPATCHARR_AUTO_CONFIRM:-}" != "yes" ]; then
    printf "If you wish to proceed, type \"I understand\" and press Enter: "
    read -r user_input
    if [ "$user_input" != "I understand" ]; then
      echo "Exiting script..."
      exit 1
    fi
  else
    echo "Auto-confirmed via DISPATCHARR_AUTO_CONFIRM=yes"
  fi
}

##############################################################################
# 1) Configuration
##############################################################################

configure_variables() {
  DISPATCH_USER="dispatcharr"
  DISPATCH_GROUP="dispatcharr"
  APP_DIR="/usr/local/dispatcharr"
  DISPATCH_BRANCH="main"
  POSTGRES_DB="dispatcharr"
  POSTGRES_USER="dispatch"
  POSTGRES_PASSWORD="secret"
  POSTGRES_HOST="localhost"
  NGINX_HTTP_PORT="9191"
  WEBSOCKET_PORT="8001"
  GUNICORN_SOCKET="/var/run/dispatcharr/dispatcharr.sock"
  # defaults for Gunicorn/celery/etc
  DISPATCHARR_WORKERS="4"
  DISPATCHARR_TIMEOUT="300"
  DJANGO_SECRET_KEY="freebsd-install-temp-key-change-in-production"
  PYTHON_BIN=$(command -v python3 || true)
  RC_DIR="/usr/local/etc/rc.d"
  NGINX_CONFD="/usr/local/etc/nginx"
}

##############################################################################
# 2) Install System Packages
##############################################################################

install_packages() {
  echo ">>> Updating package repository..."
  pkg update -f

  echo ">>> Installing system packages..."
  pkg install -y \
    git curl wget \
    python3 \
    py311-pip \
    py311-pytorch \
    py311-gevent \
    py311-cryptography \
    py311-regex \
    postgresql17-server \
    postgresql17-client \
    redis \
    nginx \
    node \
    npm \
    ffmpeg \
    sudo \
    bash \
    gmake

  # Install Gunicorn via pip if not provided by pkg (use configured python)
  PY_PIP_BIN="${PYTHON_BIN:-python3}"
  if ! pkg info -e py311-gunicorn >/dev/null 2>&1; then
    echo ">>> Installing Gunicorn via pip..."
    "${PY_PIP_BIN}" -m pip install --break-system-packages gunicorn || true
  fi

  echo ">>> Enabling and starting PostgreSQL..."
  sysrc -f /etc/rc.conf postgresql_enable="YES"

  # Initialize PostgreSQL only if data directory doesn't exist or is empty
  if [ ! -d "/var/db/postgres/data17" ] || [ -z "$(ls -A /var/db/postgres/data17 2>/dev/null)" ]; then
    service postgresql oneinitdb || echo "PostgreSQL initialization attempted"
  else
    echo "PostgreSQL data directory already exists, skipping initdb"
  fi

  # Start PostgreSQL if not already running
  if ! service postgresql status >/dev/null 2>&1; then
    service postgresql start
  else
    echo "PostgreSQL is already running"
  fi

  echo ">>> Enabling and starting Redis..."
  sysrc -f /etc/rc.conf redis_enable="YES"
  if ! service redis status >/dev/null 2>&1; then
    service redis start
  else
    echo "Redis is already running"
  fi
}

##############################################################################
# 3) Create User/Group
##############################################################################

create_dispatcharr_user() {
  echo ">>> Creating dispatcharr user and group..."
  if ! pw group show "$DISPATCH_GROUP" >/dev/null 2>&1; then
    pw groupadd "$DISPATCH_GROUP"
  fi
  if ! pw user show "$DISPATCH_USER" >/dev/null 2>&1; then
    # FreeBSD's pw command: -m creates home, -d specifies home dir, -s shell, -g primary group
    pw useradd "$DISPATCH_USER" -g "$DISPATCH_GROUP" -s /bin/sh -m -d "$APP_DIR" -w no
  fi
}

##############################################################################
# 4) PostgreSQL Setup
##############################################################################

setup_postgresql() {
  echo ">>> Checking PostgreSQL database and user..."

  # Wait for PostgreSQL to be ready (use TCP or check /tmp for socket)
  until pg_isready -h "${POSTGRES_HOST}" >/dev/null 2>&1; do
    echo "Waiting for PostgreSQL to start..."
    sleep 2
  done

  db_exists=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\"")
  if [ "$db_exists" != "1" ]; then
    echo ">>> Creating database '${POSTGRES_DB}'..."
    su - postgres -c "createdb ${POSTGRES_DB}"
  else
    echo ">>> Database '${POSTGRES_DB}' already exists, skipping creation."
  fi

  user_exists=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\"")
  if [ "$user_exists" != "1" ]; then
    echo ">>> Creating user '${POSTGRES_USER}'..."
    su - postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}';\""
  else
    echo ">>> User '${POSTGRES_USER}' already exists, skipping creation."
  fi

  echo ">>> Granting privileges..."
  su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};\""
  su - postgres -c "psql -c \"ALTER DATABASE ${POSTGRES_DB} OWNER TO ${POSTGRES_USER};\""
  su - postgres -c "psql -d ${POSTGRES_DB} -c \"ALTER SCHEMA public OWNER TO ${POSTGRES_USER};\""
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
    su - "$DISPATCH_USER" -c "
      cd '$APP_DIR'
      git fetch origin
      git reset --hard HEAD
      git fetch origin
      git checkout ${DISPATCH_BRANCH}
      git pull origin ${DISPATCH_BRANCH}
    "
  else
    echo ">>> Cloning Dispatcharr repo into ${APP_DIR}..."
    rm -rf "$APP_DIR"/*
    chown "$DISPATCH_USER:$DISPATCH_GROUP" "$APP_DIR"
    su - "$DISPATCH_USER" -c "git clone -b ${DISPATCH_BRANCH} https://github.com/Dispatcharr/Dispatcharr.git ${APP_DIR}"
  fi
}

##############################################################################
# 6) Setup Python Environment
##############################################################################

setup_python_env() {
  echo ">>> Setting up Python virtual environment..."
  PY_BIN="${PYTHON_BIN:-python3}"
  su - "$DISPATCH_USER" -c "
    cd '$APP_DIR'
    ${PY_BIN} -m venv --system-site-packages env
    env/bin/pip install --upgrade pip
  "

  # Create FreeBSD-specific requirements file
  echo ">>> Creating FreeBSD-specific requirements.txt..."
  su - "$DISPATCH_USER" -c "
    cd '$APP_DIR'
    grep -v '^--extra-index-url' requirements.txt | \
    grep -v '^torch' | \
    grep -v '^gevent' | \
    grep -v '^cryptography' | \
    grep -v '^sentence-transformers' | \
    grep -v '^tokenizers' | \
    grep -v '^transformers' | \
    grep -v '^huggingface' | \
    grep -v '^regex ' > requirements-freebsd.txt
    env/bin/pip install -r requirements-freebsd.txt || true
  "

  # Link ffmpeg for the venv
  ln -sf /usr/local/bin/ffmpeg "$APP_DIR/env/bin/ffmpeg"
}

##############################################################################
# 7) Build Frontend
##############################################################################

build_frontend() {
  echo ">>> Building frontend..."
  su - "$DISPATCH_USER" -c "
    cd '$APP_DIR/frontend'
    npm install --legacy-peer-deps
    npm run build
  "
}

##############################################################################
# 8) Create Directories
##############################################################################

create_directories() {
  echo ">>> Creating data directories..."
  mkdir -p /data/logos
  mkdir -p /data/recordings
  mkdir -p /data/uploads/m3us
  mkdir -p /data/uploads/epgs
  mkdir -p /data/m3us
  mkdir -p /data/epgs
  mkdir -p /data/plugins
  mkdir -p /var/run/dispatcharr

  chown -R "$DISPATCH_USER:$DISPATCH_GROUP" /data
  chown -R "$DISPATCH_USER:$DISPATCH_GROUP" /var/run/dispatcharr
  chmod +x /data 2>/dev/null || true

  mkdir -p "$APP_DIR/logo_cache"
  mkdir -p "$APP_DIR/media"
  chown -R "$DISPATCH_USER:$DISPATCH_GROUP" "$APP_DIR/logo_cache"
  chown -R "$DISPATCH_USER:$DISPATCH_GROUP" "$APP_DIR/media"
}

##############################################################################
# 9) Django Migrations & Static
##############################################################################

django_migrate_collectstatic() {
  echo ">>> Running Django migrations & collectstatic..."
  su - "$DISPATCH_USER" -c "
    cd '$APP_DIR'
    export POSTGRES_DB='${POSTGRES_DB}'
    export POSTGRES_USER='${POSTGRES_USER}'
    export POSTGRES_PASSWORD='${POSTGRES_PASSWORD}'
    export POSTGRES_HOST='${POSTGRES_HOST}'
    export DJANGO_SECRET_KEY='${DJANGO_SECRET_KEY}'
    env/bin/python manage.py migrate --noinput || echo 'Migrate failed, continuing...'
    env/bin/python manage.py collectstatic --noinput || echo 'Collectstatic failed, continuing...'
  "
}

##############################################################################
# 10) Configure Services - FreeBSD rc.d Scripts
##############################################################################

configure_services() {
  echo ">>> Creating FreeBSD rc.d service scripts..."

  # We'll write template files with placeholders and then substitute
  # placeholders to ensure other runtime variables like $name remain intact.

  # Gunicorn rc.d script template
  cat >"$RC_DIR/dispatcharr" <<'EOF'
#!/bin/sh
#
# PROVIDE: dispatcharr
# REQUIRE: NETWORKING postgresql redis
# KEYWORD: shutdown

. /etc/rc.subr

# Environment variables
export DJANGO_SECRET_KEY="__DJANGO_SECRET_KEY__"
export POSTGRES_DB="__POSTGRES_DB__"
export POSTGRES_USER="__POSTGRES_USER__"
export POSTGRES_PASSWORD="__POSTGRES_PASSWORD__"
export POSTGRES_HOST="__POSTGRES_HOST__"

name="dispatcharr"
rcvar="dispatcharr_enable"

load_rc_config $name

: ${dispatcharr_enable:="NO"}
: ${dispatcharr_user:="dispatcharr"}
: ${dispatcharr_group:="dispatcharr"}
: ${dispatcharr_appdir:="__APP_DIR__"}
: ${dispatcharr_socket:="__GUNICORN_SOCKET__"}
: ${dispatcharr_workers:="__WORKERS__"}
: ${dispatcharr_timeout:="__TIMEOUT__"}

pidfile="__PID_DIR__/dispatcharr.pid"
command="${dispatcharr_appdir}/env/bin/gunicorn"
command_args="
    --workers=${dispatcharr_workers}
    --worker-class=gevent
    --timeout=${dispatcharr_timeout}
    --bind unix:${dispatcharr_socket}
    --user ${dispatcharr_user}
    --group ${dispatcharr_group}
    --pid ${pidfile}
    dispatcharr.wsgi:application
"

required_files="${dispatcharr_appdir}/manage.py"
start_precmd="dispatcharr_prestart"

dispatcharr_prestart()
{
    mkdir -p $(dirname ${dispatcharr_socket})
    chown ${dispatcharr_user}:${dispatcharr_group} $(dirname ${dispatcharr_socket})
    mkdir -p $(dirname ${pidfile})
    chown ${dispatcharr_user}:${dispatcharr_group} $(dirname ${pidfile})

    # Wait for PostgreSQL
    until pg_isready -h __POSTGRES_HOST__ >/dev/null 2>&1; do
        echo "Waiting for PostgreSQL..."
        sleep 1
    done

    cd ${dispatcharr_appdir}
}

run_rc_command "$1"
EOF

  # Celery Worker rc.d script template
  cat >"$RC_DIR/dispatcharr_celery" <<'EOF'
#!/bin/sh
#
# PROVIDE: dispatcharr_celery
# REQUIRE: NETWORKING redis dispatcharr
# KEYWORD: shutdown

. /etc/rc.subr

# Environment variables
export DJANGO_SECRET_KEY="__DJANGO_SECRET_KEY__"
export POSTGRES_DB="__POSTGRES_DB__"
export POSTGRES_USER="__POSTGRES_USER__"
export POSTGRES_PASSWORD="__POSTGRES_PASSWORD__"
export POSTGRES_HOST="__POSTGRES_HOST__"

name="dispatcharr_celery"
rcvar="dispatcharr_celery_enable"

load_rc_config $name

: ${dispatcharr_celery_enable:="NO"}
: ${dispatcharr_celery_user:="dispatcharr"}
: ${dispatcharr_celery_appdir:="__APP_DIR__"}

pidfile="__PID_DIR__/dispatcharr_celery.pid"
command="${dispatcharr_celery_appdir}/env/bin/celery"
command_args="-A dispatcharr worker -l info --pidfile=${pidfile}"
required_files="${dispatcharr_celery_appdir}/dispatcharr/celery.py"

start_precmd="dispatcharr_celery_prestart"

dispatcharr_celery_prestart()
{
    mkdir -p $(dirname ${pidfile})
    chown ${dispatcharr_celery_user} $(dirname ${pidfile})
    cd ${dispatcharr_celery_appdir}
}

run_rc_command "$1"
EOF

  # Celery Beat rc.d script template
  cat >"$RC_DIR/dispatcharr_celerybeat" <<'EOF'
#!/bin/sh
#
# PROVIDE: dispatcharr_celerybeat
# REQUIRE: NETWORKING redis dispatcharr
# KEYWORD: shutdown

. /etc/rc.subr

# Environment variables
export DJANGO_SECRET_KEY="__DJANGO_SECRET_KEY__"
export POSTGRES_DB="__POSTGRES_DB__"
export POSTGRES_USER="__POSTGRES_USER__"
export POSTGRES_PASSWORD="__POSTGRES_PASSWORD__"
export POSTGRES_HOST="__POSTGRES_HOST__"

name="dispatcharr_celerybeat"
rcvar="dispatcharr_celerybeat_enable"

load_rc_config $name

: ${dispatcharr_celerybeat_enable:="NO"}
: ${dispatcharr_celerybeat_user:="dispatcharr"}
: ${dispatcharr_celerybeat_appdir:="__APP_DIR__"}

pidfile="__PID_DIR__/dispatcharr_celerybeat.pid"
command="${dispatcharr_celerybeat_appdir}/env/bin/celery"
command_args="-A dispatcharr beat -l info --pidfile=${pidfile}"
required_files="${dispatcharr_celerybeat_appdir}/dispatcharr/celery.py"

start_precmd="dispatcharr_celerybeat_prestart"

dispatcharr_celerybeat_prestart()
{
    mkdir -p $(dirname ${pidfile})
    chown ${dispatcharr_celerybeat_user} $(dirname ${pidfile})
    cd ${dispatcharr_celerybeat_appdir}
}

run_rc_command "$1"
EOF

  # Daphne rc.d script template
  cat >"$RC_DIR/dispatcharr_daphne" <<'EOF'
#!/bin/sh
#
# PROVIDE: dispatcharr_daphne
# REQUIRE: NETWORKING dispatcharr
# KEYWORD: shutdown

. /etc/rc.subr

# Environment variables
export DJANGO_SECRET_KEY="__DJANGO_SECRET_KEY__"
export POSTGRES_DB="__POSTGRES_DB__"
export POSTGRES_USER="__POSTGRES_USER__"
export POSTGRES_PASSWORD="__POSTGRES_PASSWORD__"
export POSTGRES_HOST="__POSTGRES_HOST__"

name="dispatcharr_daphne"
rcvar="dispatcharr_daphne_enable"

load_rc_config $name

: ${dispatcharr_daphne_enable:="NO"}
: ${dispatcharr_daphne_user:="dispatcharr"}
: ${dispatcharr_daphne_appdir:="__APP_DIR__"}
: ${dispatcharr_daphne_port:="__WEBSOCKET_PORT__"}

pidfile="__PID_DIR__/dispatcharr_daphne.pid"
command="${dispatcharr_daphne_appdir}/env/bin/daphne"
command_args="-b 0.0.0.0 -p ${dispatcharr_daphne_port} dispatcharr.asgi:application"
required_files="${dispatcharr_daphne_appdir}/dispatcharr/asgi.py"

start_precmd="dispatcharr_daphne_prestart"

dispatcharr_daphne_prestart()
{
    mkdir -p $(dirname ${pidfile})
    chown ${dispatcharr_daphne_user} $(dirname ${pidfile})
    cd ${dispatcharr_daphne_appdir}
}

run_rc_command "$1"
EOF

  # Substitute placeholders with configured values. Use BSD sed compatible -i ''.
  for f in "$RC_DIR/dispatcharr" "$RC_DIR/dispatcharr_celery" "$RC_DIR/dispatcharr_celerybeat" "$RC_DIR/dispatcharr_daphne"; do
    sed -i '' "s|__DJANGO_SECRET_KEY__|${DJANGO_SECRET_KEY}|g" "$f"
    sed -i '' "s|__POSTGRES_DB__|${POSTGRES_DB}|g" "$f"
    sed -i '' "s|__POSTGRES_USER__|${POSTGRES_USER}|g" "$f"
    sed -i '' "s|__POSTGRES_PASSWORD__|${POSTGRES_PASSWORD}|g" "$f"
    sed -i '' "s|__POSTGRES_HOST__|${POSTGRES_HOST}|g" "$f"
    sed -i '' "s|__APP_DIR__|${APP_DIR}|g" "$f"
    sed -i '' "s|__GUNICORN_SOCKET__|${GUNICORN_SOCKET}|g" "$f"
    sed -i '' "s|__WORKERS__|${DISPATCHARR_WORKERS}|g" "$f"
    sed -i '' "s|__TIMEOUT__|${DISPATCHARR_TIMEOUT}|g" "$f"
    sed -i '' "s|__WEBSOCKET_PORT__|${WEBSOCKET_PORT}|g" "$f"
    # Use a PID dir variable; keep consistent with GUNICORN_SOCKET dirname
    PID_DIR=$(dirname "${GUNICORN_SOCKET}")
    sed -i '' "s|__PID_DIR__|${PID_DIR}|g" "$f"
  done

  # Make scripts executable
  chmod +x "$RC_DIR/dispatcharr"
  chmod +x "$RC_DIR/dispatcharr_celery"
  chmod +x "$RC_DIR/dispatcharr_celerybeat"
  chmod +x "$RC_DIR/dispatcharr_daphne"

  echo ">>> Creating Nginx config..."
  # Create proxy_params file if it doesn't exist (FreeBSD doesn't have it by default)
  if [ ! -f "$NGINX_CONFD/proxy_params" ]; then
    cat >"$NGINX_CONFD/proxy_params" <<'EOF'
proxy_set_header Host $http_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
EOF
  fi

  # Comment out default server block in main nginx.conf that listens on port 80
  if [ -f /usr/local/etc/nginx/nginx.conf ]; then
    sed -i '' '/^[[:space:]]*server[[:space:]]*{/,/^}[[:space:]]*$/s/^/#/' /usr/local/etc/nginx/nginx.conf || true
  fi

  cat >"$NGINX_CONFD/dispatcharr.conf" <<EOF
server {
    listen ${NGINX_HTTP_PORT};
    server_name _;

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

  # Enable and start nginx
  sysrc -f /etc/rc.conf nginx_enable="YES"
  service nginx configtest || true
  service nginx stop 2>/dev/null || true
  pkill -9 nginx 2>/dev/null || true
  service nginx start
}

##############################################################################
# 11) Enable and Start Services
##############################################################################

start_services() {
  echo ">>> Enabling and starting services..."

  # Enable services in rc.conf
  sysrc -f /etc/rc.conf dispatcharr_enable="YES"
  sysrc -f /etc/rc.conf dispatcharr_celery_enable="YES"
  sysrc -f /etc/rc.conf dispatcharr_celerybeat_enable="YES"
  sysrc -f /etc/rc.conf dispatcharr_daphne_enable="YES"

  # Start services
  service dispatcharr start
  sleep 2
  service dispatcharr_celery start
  service dispatcharr_celerybeat start
  service dispatcharr_daphne start
}

##############################################################################
# 12) Summary
##############################################################################

show_summary() {
  # Try to detect server IP
  server_ip=$(ifconfig | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $2}' | head -n 1)
  if [ -z "$server_ip" ]; then
    server_ip="your-server-ip"
  fi

  cat <<EOF

=================================================
Dispatcharr installation (or update) complete!

Nginx is listening on port ${NGINX_HTTP_PORT}.
Gunicorn socket: ${GUNICORN_SOCKET}.
WebSockets on port ${WEBSOCKET_PORT} (path /ws/).

Service management:
  service dispatcharr status|restart|stop
  service dispatcharr_celery status|restart|stop
  service dispatcharr_celerybeat status|restart|stop
  service dispatcharr_daphne status|restart|stop

View logs:
  tail -f /var/log/nginx/error.log
  (Service logs go to /var/log/messages or use syslog)

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
