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

# ccextractor: decodes DVB teletext (and DVB subtitle) to SRT for the DVR
# subtitle sidecar (#259) - ffmpeg ships no teletext decoder. Plain
# systemlibs release, not the AppImage (needs FUSE) or hardsubx variant
# (OCR support we don't use) - GPL-2.0, ~3.3MB.
ARG CCEXTRACTOR_VERSION=v0.96.6
RUN curl -sL "https://github.com/CCExtractor/ccextractor/releases/download/${CCEXTRACTOR_VERSION}/ccextractor-linux-systemlibs-x86_64.tar.gz" \
    -o /tmp/ccextractor.tar.gz \
    && tar -xzf /tmp/ccextractor.tar.gz -C /usr/local/bin ./ccextractor \
    && rm -f /tmp/ccextractor.tar.gz \
    && chmod +x /usr/local/bin/ccextractor \
    && /usr/local/bin/ccextractor --version

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