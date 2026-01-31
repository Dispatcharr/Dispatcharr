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

### Optional but Recommended

- **uv** - Fast Python package installer (alternative to pip)
  - Install: [https://docs.astral.sh/uv/](https://docs.astral.sh/uv/)
  - If you don't have uv, standard pip will work fine

## Getting Started

### 1. Fork and Clone the Repository

First, fork the repository on GitHub, then clone your fork:

```bash
git clone https://github.com/YOUR-USERNAME/Dispatcharr.git
cd Dispatcharr
```

If you're contributing directly (for team members):

```bash
git clone https://github.com/Dispatcharr/Dispatcharr.git
cd Dispatcharr
```

### 2. Set Up Python Virtual Environment

Create a virtual environment to isolate project dependencies:

```bash
python3 -m venv .venv
```

Activate the virtual environment:

**On macOS/Linux:**
```bash
source .venv/bin/activate
```

**On Windows:**
```bash
.venv\Scripts\activate
```

You should see `(.venv)` appear in your terminal prompt, indicating the virtual environment is active.

### 3. Install Dependencies

Install the project dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Expected output:** You'll see packages being downloaded and installed. This may take a few minutes on first run.

**Note:** Some dependencies like `torch` and `sentence-transformers` are large ML libraries. They're optional for basic development but required for EPG auto-matching features.

### 4. Start PostgreSQL Database

Dispatcharr requires PostgreSQL for testing and development. We use Docker to make this easy:

```bash
docker run -d \
  --name dispatcharr-test-postgres \
  -e POSTGRES_DB=dispatcharr_test \
  -e POSTGRES_USER=dispatch \
  -e POSTGRES_PASSWORD=test123 \
  -p 5432:5432 \
  postgres:16-alpine
```

**What this does:**
- Downloads PostgreSQL 16 Alpine image (if not already downloaded)
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

For testing, you'll need to set environment variables. The easiest way is to export them before running tests:

```bash
export POSTGRES_DB=dispatcharr_test
export POSTGRES_USER=dispatch
export POSTGRES_PASSWORD=test123
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export DJANGO_SECRET_KEY=test-secret-key-for-development
```

**Tip:** Consider adding these to a `.env` file or a shell script that you source before development.

## Running Tests

### Run All Tests

To run the complete test suite:

```bash
POSTGRES_DB=dispatcharr_test \
POSTGRES_USER=dispatch \
POSTGRES_PASSWORD=test123 \
POSTGRES_HOST=localhost \
POSTGRES_PORT=5432 \
DJANGO_SECRET_KEY=test-secret-key \
.venv/bin/python manage.py test apps.channels.tests
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
POSTGRES_DB=dispatcharr_test \
POSTGRES_USER=dispatch \
POSTGRES_PASSWORD=test123 \
POSTGRES_HOST=localhost \
POSTGRES_PORT=5432 \
DJANGO_SECRET_KEY=test-secret-key \
.venv/bin/python manage.py test apps.channels.tests.test_channel_api
```

To run recurring rules tests:

```bash
POSTGRES_DB=dispatcharr_test \
POSTGRES_USER=dispatch \
POSTGRES_PASSWORD=test123 \
POSTGRES_HOST=localhost \
POSTGRES_PORT=5432 \
DJANGO_SECRET_KEY=test-secret-key \
.venv/bin/python manage.py test apps.channels.tests.test_recurring_rules
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
POSTGRES_DB=dispatcharr_test \
POSTGRES_USER=dispatch \
POSTGRES_PASSWORD=test123 \
POSTGRES_HOST=localhost \
POSTGRES_PORT=5432 \
DJANGO_SECRET_KEY=test-secret-key \
.venv/bin/python manage.py test apps.channels.tests
```

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

## Troubleshooting

### "No module named 'X'" Error

If you see import errors, ensure you've:
1. Activated your virtual environment: `source .venv/bin/activate`
2. Installed all dependencies: `pip install -r requirements.txt`

### PostgreSQL Connection Errors

If tests fail with database connection errors:
1. Check PostgreSQL is running: `docker ps | grep postgres`
2. Verify port 5432 isn't already in use by another process
3. Ensure environment variables are set correctly

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
