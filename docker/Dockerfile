# Define base image build arguments (must be before any FROM)
ARG REPO_OWNER=dispatcharr
ARG REPO_NAME=dispatcharr
ARG BASE_TAG=base

# --- Build frontend ---

FROM node:24 AS frontend-builder

WORKDIR /app/frontend
COPY ./frontend /app/frontend
# remove any node_modules that may have been copied from the host (x86)
RUN rm -rf node_modules || true; \
    npm install --no-audit --progress=false;
RUN    npm run build && \
    rm -rf node_modules .cache

# --- Redeclare build arguments for the next stage ---
ARG REPO_OWNER
ARG REPO_NAME
ARG BASE_TAG

# --- Final image based on the dynamic base ---
FROM ghcr.io/${REPO_OWNER}/${REPO_NAME}:${BASE_TAG} AS final
ENV VIRTUAL_ENV=/dispatcharrpy
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /app

# IMPORTANT: Verify Python packages are still available after base image
RUN echo "=== Verifying packages in final stage ===" && \
    /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ django-db-geventpool in final')" || \
    echo "⚠️ WARNING: django-db-geventpool NOT found in final stage!"

# Fallback: Install critical packages if they're missing
RUN /dispatcharrpy/bin/python -c "import psycopg; import psycopg.pq" 2>/dev/null || \
    (echo "⚠️  psycopg missing! Installing..." && \
    uv pip install --python /dispatcharrpy/bin/python 'psycopg[binary]>=3.1.18')

RUN /dispatcharrpy/bin/python -c "import django_db_geventpool" 2>/dev/null || \
    (echo "Installing missing django-db-geventpool..." && \
    uv pip install --python /dispatcharrpy/bin/python django-db-geventpool>=4.0.8)

RUN /dispatcharrpy/bin/python -c "import drf_spectacular" 2>/dev/null || \
    (echo "Installing missing drf-spectacular..." && \
    uv pip install --python /dispatcharrpy/bin/python drf-spectacular>=0.29.0)

RUN /dispatcharrpy/bin/python -c "import django_redis" 2>/dev/null || \
    (echo "Installing missing django-redis..." && \
    uv pip install --python /dispatcharrpy/bin/python django-redis)

RUN /dispatcharrpy/bin/python -c "import channels_redis" 2>/dev/null || \
    (echo "Installing missing channels-redis..." && \
    uv pip install --python /dispatcharrpy/bin/python channels-redis==4.3.0)

# Final verification - fail build if packages are still missing
RUN echo "=== Final verification ===" && \
    /dispatcharrpy/bin/python -c "import psycopg; print('✓ psycopg version:', psycopg.__version__)" && \
    /dispatcharrpy/bin/python -c "import psycopg.pq; print('✓ psycopg binary driver')" && \
    /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ django-db-geventpool available')" && \
    /dispatcharrpy/bin/python -c "import drf_spectacular; print('✓ drf-spectacular available')" && \
    /dispatcharrpy/bin/python -c "import django_redis; print('✓ django-redis available')" && \
    /dispatcharrpy/bin/python -c "import channels_redis; print('✓ channels-redis available')"

# Copy application code
COPY . /app
# Copy nginx configuration
COPY ./docker/nginx.conf /etc/nginx/sites-enabled/default
# Fix line endings and make entrypoint scripts executable
RUN for f in /app/docker/entrypoint*.sh; do \
    if [ -f "$f" ]; then \
    sed -i 's/\r$//' "$f" && chmod +x "$f"; \
    fi; \
    done
# Clean out existing frontend folder
RUN rm -rf /app/frontend
# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Add timestamp argument
ARG TIMESTAMP

# Update version.py with build timestamp if provided
RUN if [ -n "$TIMESTAMP" ]; then \
    echo "Updating timestamp to ${TIMESTAMP} in version.py" && \
    sed -i "s|__timestamp__ = None.*|__timestamp__ = '${TIMESTAMP}'    # Set during CI/CD build process|" /app/version.py && \
    cat /app/version.py; \
    fi

ENTRYPOINT ["/app/docker/entrypoint.sh"]