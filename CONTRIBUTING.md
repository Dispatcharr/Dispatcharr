# Contributing to Dispatcharr

Thank you for your interest in contributing. Dispatcharr is a complex, production-oriented platform and we hold contributions to a high standard. Please read this guide in full before opening a pull request — it will save everyone time.

---

## Table of Contents

- [Before You Start](#before-you-start)
- [Project Overview](#project-overview)
- [Setting Up the Development Environment](#setting-up-the-development-environment)
- [Code Standards](#code-standards)
- [Writing Tests](#writing-tests)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [On AI-Assisted Code](#on-ai-assisted-code)
- [What We Will Decline](#what-we-will-decline)

---

## Before You Start

**Open an issue before writing code.** If you want to add a feature or fix a non-trivial bug, open a GitHub issue first. This lets us tell you whether it aligns with the project's direction, whether it's already being worked on, and how it should be approached — before you invest time writing code.

For small, obvious bug fixes (a typo, an off-by-one error, a missing validation) you can go straight to a PR.

---

## Project Overview

Understanding the architecture is a prerequisite for contributing. If you are not familiar with the following, take time to learn them before submitting changes:

| Layer       | Technology                                        |
| ----------- | ------------------------------------------------- |
| Backend     | Python 3.13, Django 5, Django REST Framework      |
| Async tasks | Celery 5 with Redis broker                        |
| Real-time   | Django Channels (WebSockets), Redis channel layer |
| Database    | PostgreSQL 17                                     |
| Frontend    | React 19, Vite, Mantine UI, Zustand               |
| API docs    | drf-spectacular (OpenAPI)                         |
| Packaging   | `uv`, `pyproject.toml`, Hatchling                 |
| Deployment  | Docker, Nginx, uWSGI/Daphne                       |

### Key Django Apps

| App             | Responsibility                                        |
| --------------- | ----------------------------------------------------- |
| `apps/channels` | Core channel management                               |
| `apps/proxy`    | Stream proxying, client management, failover          |
| `apps/epg`      | EPG ingestion, matching, XMLTV output                 |
| `apps/m3u`      | M3U playlist parsing and management                   |
| `apps/output`   | M3U, Xtream Codes, XMLTV export                       |
| `apps/hdhr`     | HDHomeRun device emulation                            |
| `apps/vod`      | VOD library with TMDB/IMDB metadata                   |
| `apps/ffmpeg`   | FFmpeg stream profile management                      |
| `apps/plugins`  | Plugin/event-hook system                              |
| `apps/accounts` | Auth, permissions, API keys                           |
| `core/`         | Shared tasks, scheduling, utilities, Xtream Codes API |

Before touching any app, read its models, serializers, and views end-to-end so you understand what already exists.

---

## Setting Up the Development Environment

### Prerequisites

- Docker and Docker Compose
- Node.js 24+ (for frontend)
- Python 3.13+ and [`uv`](https://docs.astral.sh/uv/)

### Backend (Docker — recommended)

```bash
# Full stack (modular mode with separate containers)
docker compose -f docker/docker-compose.dev.yml up

# Or run Django directly against a local Redis/Postgres
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

### Frontend

```bash
cd frontend
npm install
npm run dev       # dev server with HMR (proxies API to Django)
npm run build     # production build
npm run test      # run Vitest test suite
```

The Vite dev server is configured to proxy `/api/` requests to the Django backend.

### Environment Variables

Copy the relevant `docker-compose.*.yml` as a reference for required environment variables. Key ones:

| Variable                | Purpose                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------- |
| `POSTGRES_*`            | Database connection                                                                         |
| `REDIS_*`               | Redis broker / channel layer                                                                |
| `DJANGO_SECRET_KEY`     | Django secret (auto-generated in Docker)                                                    |
| `DISPATCHARR_DEBUG`     | Enables Django debug mode **and** starts debugpy for remote debugging (attach on port 5678) |
| `DISPATCHARR_LOG_LEVEL` | Log verbosity                                                                               |

---

## Code Standards

### Backend (Python/Django)

- Follow [PEP 8](https://peps.python.org/pep-0008/). Use 4-space indentation.
- Follow Django conventions: fat models, thin views, business logic out of serializers.
- New API endpoints must use Django REST Framework. Include serializers — do not return raw dicts from views.
- New endpoints must be registered in the appropriate `api_urls.py` and must appear correctly in the OpenAPI schema (check via drf-spectacular).
- Database changes require a migration: `uv run python manage.py makemigrations <app>`. Migrations must be included in your PR.
- Celery tasks belong in `tasks.py` of the relevant app, or `core/tasks.py` for shared tasks. Tasks must be idempotent where possible.
- Do not introduce new top-level dependencies without discussion. Add them to `pyproject.toml` with a justification in your PR description.

### Frontend (React/JavaScript)

- Code must pass ESLint without errors: `npm run lint`
- Code must be formatted with Prettier: `npm run format`
- Use existing Mantine UI components. Do not introduce new UI libraries.
- State management uses Zustand. New global state belongs in a store under `frontend/src/store/`. Do not use React Context for app-level state.
- API calls belong in `frontend/src/api.js`. Do not make `fetch`/`axios` calls directly from components.
- Components should be functional. Avoid class components.

### General

- Do not leave debug logging, `console.log`, `print()`, or commented-out code in your PR.
- Do not reformat or refactor code outside the scope of your change. Noise in diffs makes review harder.
- Keep commits focused. One logical change per commit.

---

## Writing Tests

Untested code is significantly less likely to be merged.

### Backend

- Use Django's `TestCase` for unit/integration tests.
- Test files live at `apps/<app>/tests/`.
- Run the test suite with: `uv run python manage.py test`

### Frontend

- Use Vitest and React Testing Library.
- Test files live alongside what they test in `__tests__/` directories.
- Run with: `npm run test`
- Every new store should have a test file under `frontend/src/store/__tests__/`.
- Every new page should have a test file under `frontend/src/pages/__tests__/`.

---

## Submitting a Pull Request

### PR Checklist

Before opening your PR, verify each of the following yourself:

- [ ] I have read this entire document
- [ ] I opened (or was assigned to) a GitHub issue for this change before writing code
- [ ] I understand — line by line — every change in this PR
- [ ] Backend: migrations are included if models changed
- [ ] Backend: new endpoints are documented in the OpenAPI schema
- [ ] Frontend: ESLint and Prettier pass cleanly
- [ ] Tests are included for new functionality
- [ ] Existing tests still pass
- [ ] No debug artifacts are left in the code
- [ ] My PR targets the `dev` branch (or the branch specified in the issue)

### PR Description

A good PR description answers:

1. **What** does this change do?
2. **Why** is this change needed? (link to the issue)
3. **How** does it work? Describe any non-obvious technical decisions.
4. **How was it tested?** What did you run to verify this works?

One-line PR descriptions like _"fixed bug"_ or _"added feature"_ will be closed and asked to resubmit.

### Review Process

Maintainers review PRs as time allows. To keep the process moving:

- Respond to review comments promptly. Stale PRs (no activity for 30 days) may be closed.
- Do not force-push to a branch under review without flagging it in a comment.
- Keep your branch up to date with `dev` by rebasing, not merging `dev` into your branch.

---

## On AI-Assisted Code

We are aware that AI coding tools are capable of generating plausible-looking code quickly. We do not prohibit their use, but we require the following:

**You must understand every line of code you submit.**

AI tools frequently produce code that:

- Duplicates logic that already exists elsewhere in the codebase
- Ignores the established patterns for how the project is structured
- Introduces subtle bugs that are invisible without domain knowledge
- Passes superficial review but breaks edge cases in production

If you cannot explain, during code review, why a particular line of code is written the way it is — including the tradeoffs involved — the PR will not be merged. There are no exceptions.

Using an AI tool to help you understand the codebase, generate a first draft, or write boilerplate is fine. Submitting code you have not read and do not understand is not.

---

## What We Will Decline

To save your time and ours, the following types of PRs will be closed without extended review:

- **Undiscussed feature additions.** If there is no linked issue where the feature was agreed upon, we will close the PR and ask you to open one.
- **Large, unfocused diffs.** A PR that touches 20 files across 5 apps to "improve code quality" is almost never reviewable. Scope your changes.
- **Dependency bumps without justification.** Don't open a PR just to bump a library version unless you have identified a specific bug or security issue it resolves.
- **Cosmetic/style-only changes.** Reformatting files, renaming variables for preference, or reorganizing imports with no functional change.
- **Duplicate work.** Check open PRs and issues before starting. If someone is already working on it, coordinate with them.
- **Code the author cannot explain.** See [On AI-Assisted Code](#on-ai-assisted-code).

---

## Questions

If you are unsure whether a contribution is a good fit, join the [Discord](https://discord.gg/Sp45V5BcxU) and start a conversation, or comment on the relevant issue. We would rather have a five-minute conversation upfront than a 30-comment review thread on a PR that ultimately doesn't get merged.
