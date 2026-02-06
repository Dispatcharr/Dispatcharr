# Contributing to Dispatcharr

Thank you for your interest in contributing to Dispatcharr! We're excited to have you join our community of contributors. This guide will help you get your development environment set up and running tests in no time.

## Welcome!

Whether you're fixing a bug, adding a feature, improving documentation, or just exploring the codebase, we appreciate your contribution. This guide will walk you through everything you need to know to get started.

## Prerequisites

Before you begin, make sure you have the following installed on your system:

### Required Software

1. **Python 3.13 or higher**
   - Check your version: `python3 --version`
   - Download: [https://www.python.org/downloads/](https://www.python.org/downloads/)
   - We recommend using Python 3.14 for the best experience

2. **Git**
   - Check if installed: `git --version`
   - Download: [https://git-scm.com/downloads](https://git-scm.com/downloads)

3. **Docker**
   - Required for running PostgreSQL database
   - Check if installed: `docker --version`
   - Download: [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/)

4. **uv** - Fast Python package manager
   - Check if installed: `uv --version`
   - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Documentation: [https://docs.astral.sh/uv/](https://docs.astral.sh/uv/)

## Getting Started

### 1. Fork and Clone the Repository

First, fork the repository on GitHub, then clone your fork:

```bash
git clone https://github.com/YOUR-USERNAME/Dispatcharr.git
cd Dispatcharr
```

### 2. Install Dependencies

Dispatcharr uses [uv](https://docs.astral.sh/uv/) for fast, reliable dependency management. The `uv sync` command reads from `pyproject.toml` and automatically creates a virtual environment:

```bash
uv sync
```

**Expected output:** You'll see packages being resolved and installed. UV is fast - this typically completes in seconds.

**Note:** Some dependencies like `torch` and `sentence-transformers` are large ML libraries required for EPG auto-matching features.

**macOS Users:** The ML dependencies (torch) are configured for Linux. On macOS, you have two options:

1. **Use Docker for development** (recommended): See [Alternative: Docker Development](#alternative-docker-development) below
2. **Modify torch version temporarily**: Edit `pyproject.toml` and change `torch==2.9.1+cpu` to `torch>=2.0.0`, then remove the `[tool.uv.sources]` section for torch. Don't commit these changes.

### 3. Activate the Virtual Environment

After `uv sync` creates the `.venv` directory, activate it:

**On macOS/Linux:**
```bash
source .venv/bin/activate
```

**On Windows:**
```bash
.venv\Scripts\activate
```

You should see `(.venv)` appear in your terminal prompt, indicating the virtual environment is active.

### 4. Start PostgreSQL Database

Dispatcharr requires PostgreSQL for testing and development. We use Docker to make this easy:

```bash
docker run -d \
  --name dispatcharr-test-postgres \
  -e POSTGRES_DB=dispatcharr_test \
  -e POSTGRES_USER=dispatch \
  -e POSTGRES_PASSWORD=test123 \
  -p 5432:5432 \
  postgres:17-alpine
```

**What this does:**
- Downloads PostgreSQL 17 Alpine image (if not already downloaded)
- Starts PostgreSQL in a container named `dispatcharr-test-postgres`
- Creates a database called `dispatcharr_test`
- Makes it accessible on `localhost:5432`

**Verify PostgreSQL is running:**
```bash
docker exec dispatcharr-test-postgres pg_isready
```

**Expected output:**
```
/var/run/postgresql:5432 - accepting connections
```

### 5. Set Up Environment Variables

Create a `.env` file in the project root to store your environment variables. This makes it easy to load them whenever you need to run tests or development commands.

Create the file:

```bash
cat > .env << 'EOF'
export POSTGRES_DB=dispatcharr_test
export POSTGRES_USER=dispatch
export POSTGRES_PASSWORD=test123
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export DJANGO_SECRET_KEY=test-secret-key-for-development
EOF
```

**What this does:**
- Creates a `.env` file with all the necessary environment variables
- The file is already in `.gitignore`, so it won't be committed to version control
- You'll source this file once per terminal session to load the variables

**Note:** The `.env` file is for local development only and should never be committed to the repository.

**How it works:**
- When you run `source .env`, the environment variables are loaded into your current terminal session
- They remain available for all subsequent commands in that session
- When you open a new terminal window/tab, you'll need to `source .env` again

## Running Tests

Before running tests for the first time in a terminal session, load your environment variables from the `.env` file:

```bash
source .env
```

**Important:** You only need to run `source .env` once per terminal session. The environment variables will persist for all commands in that session. If you open a new terminal window or tab, you'll need to source the file again.

### Run All Tests

To run the complete test suite:

```bash
python manage.py test apps.channels.tests
```

**Expected output:**
```
...
----------------------------------------------------------------------
Ran 11 tests in 20.523s

OK
```

### Run Specific Test Files

To run just the channel API tests:

```bash
python manage.py test apps.channels.tests.test_channel_api
```

To run recurring rules tests:

```bash
python manage.py test apps.channels.tests.test_recurring_rules
```

### Understanding Test Output

When tests run successfully, you'll see:
- ✅ Each test case listed with "ok" status
- ⚠️  Some warnings about Redis connections (this is normal - Redis isn't required for these tests)
- ✅ Final summary: "Ran X tests in Y seconds" followed by "OK"

If a test fails, you'll see detailed error messages showing which test failed and why.

## Development Workflow

### 1. Create a Feature Branch

Always create a new branch for your work:

```bash
git checkout -b feature/your-feature-name
```

Or for bug fixes:

```bash
git checkout -b fix/bug-description
```

### 2. Make Your Changes

- Write clean, maintainable code
- Follow the existing code style and patterns
- Add tests for new features
- Update documentation as needed

### 3. Run Tests Before Committing

Always run tests to ensure you haven't broken anything:

```bash
python manage.py test apps.channels.tests
```

**Note:** If you're in a new terminal session and haven't sourced `.env` yet, run `source .env` first.

### 4. Commit Your Changes

Use clear, descriptive commit messages:

```bash
git add .
git commit -m "Add feature: description of your changes"
```

### 5. Push and Create a Pull Request

```bash
git push origin feature/your-feature-name
```

Then open a pull request on GitHub with:
- A clear description of what you changed and why
- Any relevant issue numbers
- Screenshots if you modified the UI

## Database Management

### Stop the PostgreSQL Container

When you're done developing:

```bash
docker stop dispatcharr-test-postgres
```

### Start the Existing Container

To restart the container later:

```bash
docker start dispatcharr-test-postgres
```

### Remove the Container

If you need to start fresh:

```bash
docker stop dispatcharr-test-postgres
docker rm dispatcharr-test-postgres
```

Then recreate it using the `docker run` command from step 4 above.

### Access PostgreSQL Directly

If you need to inspect the database:

```bash
docker exec -it dispatcharr-test-postgres psql -U dispatch -d dispatcharr_test
```

## Alternative: Docker Development

If you're on macOS or prefer a fully containerized environment, you can use the dev Docker setup:

```bash
cd docker
docker compose -f docker-compose.dev.yml up -d
```

This starts a development container with all dependencies pre-installed. The container:
- Mounts your local code at `/app`
- Runs the frontend dev server on port 9191
- Runs the backend on port 5656
- Includes PostgreSQL and Redis

To run tests inside the container:

```bash
docker exec dispatcharr_dev python manage.py test apps.channels.tests
```

To view logs:

```bash
docker logs -f dispatcharr_dev
```

## Troubleshooting

### "No module named 'X'" Error

If you see import errors, ensure you've:
1. Installed dependencies: `uv sync`
2. Activated your virtual environment: `source .venv/bin/activate`

### PostgreSQL Connection Errors

If tests fail with database connection errors:
1. Check PostgreSQL is running: `docker ps | grep postgres`
2. Verify port 5432 isn't already in use by another process
3. Ensure you've sourced the `.env` file: `source .env`
4. Verify environment variables are loaded: `echo $POSTGRES_HOST`

### Tests Fail with "near 'DO': syntax error"

This happens if you try to use SQLite instead of PostgreSQL. Dispatcharr requires PostgreSQL due to database-specific migrations. Make sure:
- PostgreSQL container is running
- Environment variables point to PostgreSQL (not SQLite)

### Redis Connection Warnings

You may see warnings like "Connection to Redis lost" during tests. This is expected and normal - Redis isn't required for the test suite. These warnings can be safely ignored.

## Code Style and Best Practices

- Follow Django best practices and conventions
- Write tests for new features using Django's TestCase
- Keep changes focused - one feature or fix per pull request
- Update documentation when adding new features
- Be respectful and constructive in code reviews

## Getting Help

- **Issues:** [https://github.com/Dispatcharr/Dispatcharr/issues](https://github.com/Dispatcharr/Dispatcharr/issues)
- **Discord:** [https://discord.gg/Sp45V5BcxU](https://discord.gg/Sp45V5BcxU)
- **Documentation:** [https://dispatcharr.github.io/Dispatcharr-Docs/](https://dispatcharr.github.io/Dispatcharr-Docs/)

## License

By contributing to Dispatcharr, you agree that your contributions will be licensed under the CC BY-NC-SA 4.0 license. See [LICENSE](LICENSE) for details.

---

Thank you for contributing to Dispatcharr! Your efforts help make IPTV management better for everyone. 🎬
