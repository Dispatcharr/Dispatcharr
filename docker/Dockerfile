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

# AppImage extracted once at build time, not the systemlibs release: that
# one wants libutf8proc.so.2, which Ubuntu 24.04 no longer ships. Upstream
# ships no arm64 build at all, so it's amd64-only; the DVB teletext DVR
# decode step degrades to a no-op there (see _dvr_fold_subtitle_sidecar_into_mkv).
ARG TARGETARCH
ARG CCEXTRACTOR_VERSION=v0.96.6
RUN if [ "$TARGETARCH" = "amd64" ]; then \
    curl -sL "https://github.com/CCExtractor/ccextractor/releases/download/${CCEXTRACTOR_VERSION}/ccextractor-x86_64.AppImage" \
    -o /tmp/ccextractor.AppImage \
    && chmod +x /tmp/ccextractor.AppImage \
    && cd /tmp && ./ccextractor.AppImage --appimage-extract \
    && mv /tmp/squashfs-root /opt/ccextractor \
    && ln -s /opt/ccextractor/AppRun /usr/local/bin/ccextractor \
    && rm -f /tmp/ccextractor.AppImage \
    && ccextractor --version; \
    else \
    echo "ccextractor: no upstream ${TARGETARCH} build for ${CCEXTRACTOR_VERSION}, skipping"; \
    fi

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