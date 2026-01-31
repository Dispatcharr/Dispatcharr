# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Dispatcharr is an open-source IPTV stream management platform. It manages IPTV streams, EPG (Electronic Program Guide) data, and VOD content with support for HDHomeRun emulation, M3U playlists, and XMLTV output for media servers like Plex and Jellyfin.

## Tech Stack

- **Backend:** Python 3.13+, Django 5.2, Django REST Framework, Celery with Redis
- **Frontend:** React 19, Vite 7, Zustand (state), Mantine UI
- **Database:** PostgreSQL (primary) or SQLite (fallback)
- **Real-time:** Django Channels with Redis, WebSockets via Daphne
- **ML:** PyTorch + Sentence-Transformers for EPG auto-matching

## Development Commands

### Backend
```bash
python manage.py runserver              # Django dev server
python manage.py migrate                # Apply migrations
python manage.py makemigrations         # Create migrations
celery -A dispatcharr worker -l info    # Celery worker
celery -A dispatcharr beat -l info      # Celery scheduler
```

### Frontend
```bash
cd frontend
npm run dev         # Vite dev server with HMR
npm run build       # Production build
npm run lint        # ESLint
npm test            # Vitest (single run)
npm run test:watch  # Vitest (watch mode)
```

### Docker
```bash
# All-in-one (recommended for quick start)
docker-compose -f docker/docker-compose.aio.yml up

# Development with pgAdmin and Redis Commander
docker-compose -f docker/docker-compose.dev.yml up

# Modular (separate containers)
docker-compose -f docker/docker-compose.yml up
```

## Architecture

### Django Apps (`apps/`)

Each app follows the pattern: `models.py` → `serializers.py` → `api_views.py` → `api_urls.py`

- **channels/** - Channel management, recordings, channel groups
- **epg/** - Electronic Program Guide import and matching
- **m3u/** - M3U playlist import and stream sources
- **proxy/** - Stream proxying engine (HLS/TS)
- **hdhr/** - HDHomeRun device emulation (SSDP discovery)
- **vod/** - Video on Demand (movies, series)
- **output/** - Xtream Codes API compatibility layer
- **plugins/** - Plugin system for extensibility
- **accounts/** - User authentication (JWT)
- **backups/** - Backup and restore

### Core (`core/`)

Shared functionality across apps:
- `models.py` - StreamProfile, UserAgent, CoreSettings
- `tasks.py` - Celery background tasks
- `redis_pubsub.py` - Real-time event publishing
- `xtream_codes.py` - Xtream Codes protocol implementation

### Frontend (`frontend/src/`)

- `api.js` - Centralized API client (all backend endpoints)
- `WebSocket.jsx` - Real-time WebSocket client
- `store/` - Zustand stores (one per domain: channels, epg, m3u, etc.)
- `components/` - Reusable React components
- `pages/` - Main UI pages

### Settings (`dispatcharr/settings.py`)

Key environment variables:
- `DISPATCHARR_DEBUG` - Enable debug mode
- `DISPATCHARR_LOG_LEVEL` - Logging level (TRACE/DEBUG/INFO/WARNING/ERROR)
- `POSTGRES_*` - Database connection
- `REDIS_HOST`, `REDIS_PORT` - Redis connection
- `CELERY_BROKER_URL` - Celery broker

## Key Patterns

### Adding a REST Endpoint
1. Define model in `apps/<app>/models.py`
2. Create serializer in `apps/<app>/serializers.py`
3. Create ViewSet in `apps/<app>/api_views.py`
4. Register routes in `apps/<app>/api_urls.py`
5. Include in `apps/api/urls.py` if new app
6. Add frontend endpoint to `frontend/src/api.js`
7. Create/update Zustand store in `frontend/src/store/`

### Background Tasks
Tasks use Celery with `@shared_task` decorator. Define in `apps/<app>/tasks.py` or `core/tasks.py`. Call via `.delay()` for async execution. Scheduled tasks configured in `CELERY_BEAT_SCHEDULE` in settings.

### Real-time Updates
Backend publishes to Redis channels via `core/redis_pubsub.py`. Frontend WebSocket client auto-subscribes and updates Zustand stores.

## API Structure

- REST API: `/api/` prefix (DRF ViewSets)
- Xtream Codes compatibility: `/player_api.php`, `/panel_api.php`
- Authentication: JWT tokens (30-min access, 1-day refresh)
- API docs: drf-spectacular at `/api/schema/`

## Plugin System

Plugins live in `/app/data/plugins/` (or `DISPATCHARR_PLUGINS_DIR`). Each plugin has a `plugin.py` with a `Plugin` class defining `name`, `version`, `fields`, `actions`, and a `run()` method. See `Plugins.md` for details.
