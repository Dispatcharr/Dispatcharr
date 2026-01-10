# Building Dispatcharr for FreeBSD

This document describes how to build a FreeBSD release package for Dispatcharr.

## Overview

Dispatcharr is a Python/Django application with a React frontend. The FreeBSD "build" creates a distributable package containing:

- Pre-built React frontend (compiled with Vite)
- Django application code
- FreeBSD installation script (`freebsd_start.sh`)
- RC.d service templates
- Compatibility tests

## Quick Start

### Automated Build (GitHub Actions)

The easiest way to build is using GitHub Actions:

1. **Tag a release:**
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
   This triggers the `freebsd-release.yml` workflow automatically.

2. **Manual trigger:**
   - Go to **Actions** → **FreeBSD Release**
   - Click **Run workflow**
   - Optionally specify a version
   - Click **Run workflow**

The workflow will:
- Build the frontend
- Run compatibility tests
- Create a release package
- (Optionally) Test in a FreeBSD VM
- Upload to GitHub Releases

### Local Build

Build locally using the standalone script:

```bash
# Standard build
./scripts/build-freebsd.sh

# Build with specific version
./scripts/build-freebsd.sh --version 1.0.0

# Quick rebuild (skip frontend if unchanged)
./scripts/build-freebsd.sh --skip-frontend

# Clean build to custom location
./scripts/build-freebsd.sh --clean --output /tmp/build
```

## Build Requirements

### For Local Builds

| Tool | Version | Purpose |
|------|---------|---------|
| Node.js | 18+ | Frontend build |
| npm | 9+ | Package management |
| Python | 3.9+ | Syntax validation |
| bash | 4+ | Build script |
| tar | any | Packaging |
| sha256sum | any | Checksums |

### For FreeBSD Installation

| Package | Purpose |
|---------|---------|
| python3 | Runtime |
| py311-pip | Package installation |
| postgresql17-server | Database |
| redis | Cache/queue |
| nginx | Web server |
| node, npm | Frontend (if rebuilding) |
| git | Updates |

## Build Script Options

```
./scripts/build-freebsd.sh [OPTIONS]

OPTIONS:
    --version <ver>     Version string (default: from version.py)
    --output <path>     Output directory (default: ./build)
    --skip-frontend     Skip frontend build, use existing dist/
    --skip-tests        Skip compatibility tests
    --clean             Clean build directory first
    --help              Show help
```

## Package Contents

The generated package (`dispatcharr-VERSION-freebsd.tar.gz`) contains:

```
dispatcharr-VERSION-freebsd/
├── apps/                   # Django applications
├── core/                   # Core Django app
├── dispatcharr/            # Django settings
├── frontend/
│   └── dist/               # Pre-built React frontend
├── scripts/                # Utility scripts
├── tests/
│   └── freebsd/            # Compatibility tests
├── freebsd_start.sh        # Main installation script
├── install.sh              # Installation wrapper
├── manage.py               # Django management
├── requirements.txt        # Python dependencies
├── BUILD_INFO              # Build metadata
├── README.md
└── LICENSE
```

## Installation on FreeBSD

```bash
# Download the release
fetch https://github.com/USER/REPO/releases/download/vX.X.X/dispatcharr-X.X.X-freebsd.tar.gz

# Verify checksum (optional but recommended)
fetch https://github.com/USER/REPO/releases/download/vX.X.X/dispatcharr-X.X.X-freebsd.tar.gz.sha256
sha256 -c dispatcharr-X.X.X-freebsd.tar.gz.sha256

# Extract
tar -xzf dispatcharr-X.X.X-freebsd.tar.gz
cd dispatcharr-X.X.X-freebsd

# Install (as root)
sudo ./install.sh
```

The installation script will:
1. Install required packages via `pkg`
2. Create the `dispatcharr` user
3. Set up PostgreSQL database
4. Install Python dependencies
5. Run Django migrations
6. Configure Nginx
7. Create and start RC.d services

## GitHub Actions Workflow

### Triggers

| Event | Condition | Action |
|-------|-----------|--------|
| Push tag | `v*` | Build and release |
| Manual | workflow_dispatch | Build (optional release) |

### Jobs

1. **build**: Creates the package on Ubuntu
2. **test**: Tests package in FreeBSD VM (tags only)
3. **release**: Uploads to GitHub Releases

### Secrets Required

None - uses `GITHUB_TOKEN` automatically provided.

### Customization

Edit `.github/workflows/freebsd-release.yml` to:
- Change FreeBSD version (default: 14.0)
- Add additional build steps
- Modify release notes template
- Adjust artifact retention

## Testing

### Compatibility Tests

Run tests before building:

```bash
# Quick CI tests
./scripts/ci_test.sh

# Detailed tests
./tests/freebsd/test_freebsd_compat.sh --verbose

# Python tests
python3 tests/freebsd/test_freebsd_script.py
```

### Test in FreeBSD Jail

On a FreeBSD host:

```bash
sudo ./scripts/test_in_jail.sh --branch main --verbose
```

## Troubleshooting

### Frontend Build Fails

```bash
# Clear npm cache
cd frontend
rm -rf node_modules package-lock.json
npm cache clean --force
npm install --legacy-peer-deps
```

### Python Syntax Errors

```bash
# Find problematic files
find apps core dispatcharr -name "*.py" -exec python3 -m py_compile {} \;
```

### Package Too Large

The frontend `dist/` includes source maps by default. To reduce size:

```bash
# Edit frontend/vite.config.js
build: {
  sourcemap: false,
  ...
}
```

### Checksum Mismatch

Ensure you're downloading both files from the same release:

```bash
# Re-download and verify
rm -f dispatcharr-*.tar.gz*
fetch URL/dispatcharr-X.X.X-freebsd.tar.gz
fetch URL/dispatcharr-X.X.X-freebsd.tar.gz.sha256
sha256 -c dispatcharr-X.X.X-freebsd.tar.gz.sha256
```

## Development Workflow

1. Make changes to the codebase
2. Run compatibility tests: `./scripts/ci_test.sh`
3. Test locally: `./scripts/build-freebsd.sh --skip-tests`
4. Test in jail: `sudo ./scripts/test_in_jail.sh`
5. Commit and push
6. Tag for release: `git tag vX.X.X && git push origin vX.X.X`

## Related Files

- `.github/workflows/freebsd-release.yml` - GitHub Actions workflow
- `.github/workflows/freebsd-compat.yml` - Compatibility testing
- `scripts/build-freebsd.sh` - Standalone build script
- `scripts/ci_test.sh` - CI test runner
- `scripts/test_in_jail.sh` - Jail-based testing
- `freebsd_start.sh` - Installation script
- `tests/freebsd/` - Compatibility test suite
