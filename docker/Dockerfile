FROM python:3.13-slim AS builder

ENV PATH="/dispatcharrpy/bin:$PATH" \
    VIRTUAL_ENV=/dispatcharrpy \
    DJANGO_SETTINGS_MODULE=dispatcharr.settings \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        git \
        wget && \
    echo "=== setting up nodejs ===" && \
    curl -sL https://deb.nodesource.com/setup_23.x -o /tmp/nodesource_setup.sh && \
    bash /tmp/nodesource_setup.sh && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        nodejs && \
    python -m pip install virtualenv && \
    virtualenv /dispatcharrpy && \
    git clone https://github.com/Dispatcharr/Dispatcharr /app && \
    cd /app && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-pytorch.txt && \
    pip install --no-cache-dir -r requirements-sentence-transformers.txt && \
    python manage.py collectstatic --noinput && \
    echo "installing sentence-transformers" && \
    pip install sentence-transformers==3.4.1 && \
    cd /app/frontend && \
    npm install && \
    npm run build && \
    find . -maxdepth 1 ! -name '.' ! -name 'build' -exec rm -rf '{}' \;

FROM python:3.13-slim

ENV PATH="/dispatcharrpy/bin:$PATH" \
    VIRTUAL_ENV=/dispatcharrpy \
    DJANGO_SETTINGS_MODULE=dispatcharr.settings \
    PYTHONUNBUFFERED=1

# Copy the virtual environment and application from the builder stage
COPY --from=builder /dispatcharrpy /dispatcharrpy
COPY --from=builder /app /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        gnupg2 \
        gpg \
        libpq-dev \
        lsb-release \
        nginx \
        procps \
        streamlink \
        wget && \
    cp /app/docker/nginx.conf /etc/nginx/sites-enabled/default && \
    echo "=== setting up postgres ====" && \
    echo "deb http://apt.postgresql.org/pub/repos/apt/ bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
    echo "=== setting up redis ===" && \
    curl -fsSL https://packages.redis.io/gpg | gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg && \
    chmod 644 /usr/share/keyrings/redis-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/redis.list && \
    apt-get update && \
    apt-get install -y \
        postgresql-14 \
        postgresql-contrib-14 \
        redis-server && \
    mkdir /data && \
    apt-get remove -y \
        gnupg2 \
        gpg \
        lsb-release && \
    apt-get clean && \
    apt-get autoremove -y && \
    rm -rf \
        /tmp/* \
        /var/lib/apt/lists/* \
        /var/tmp/*

WORKDIR /app

CMD ["/app/docker/entrypoint.sh"]
