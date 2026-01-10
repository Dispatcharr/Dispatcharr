# FreeBSD Compatibility Tests

This test suite validates that changes to the upstream Dispatcharr repository don't break FreeBSD compatibility.

## Quick Start

### Shell-based Tests (Recommended for CI)

```bash
# Run all tests
./tests/freebsd/test_freebsd_compat.sh

# Run with verbose output
./tests/freebsd/test_freebsd_compat.sh --verbose
```

### Python Tests (More Detailed)

```bash
# Using pytest
python -m pytest tests/freebsd/ -v

# Direct execution
python tests/freebsd/test_freebsd_script.py
```

## What These Tests Check

### Script Syntax Validation
- Valid shebang line
- BSD-compatible shell syntax
- No problematic process substitution

### BSD sed Compatibility
- Uses `sed -i ''` instead of GNU `sed -i`
- Proper escape sequences

### Linux Command Detection
Tests ensure the FreeBSD script doesn't accidentally include Linux-specific commands:
- `systemctl` → use `service` or `sysrc`
- `apt-get`/`apt` → use `pkg`
- `useradd`/`groupadd` → use `pw useradd`/`pw groupadd`
- `journalctl` → use syslog
- `/etc/systemd/` → use `/usr/local/etc/rc.d/`

### FreeBSD Command Verification
Confirms the script uses FreeBSD-native tools:
- `pkg` for package management
- `sysrc` for RC configuration
- `pw` for user/group management
- `service` for service control

### RC Script Structure
Validates generated rc.d scripts include:
- `# PROVIDE:` directive
- `# REQUIRE:` dependencies
- `. /etc/rc.subr` source
- `rcvar=` definition
- `run_rc_command` call

### Nginx Configuration
Checks:
- Correct FreeBSD path (`/usr/local/etc/nginx`)
- All location blocks (/, /static/, /assets/, /media/, /ws/)
- WebSocket upgrade headers
- proxy_params creation

### Directory Structure
Verifies all required directories are created:
- `/data/logos`, `/data/recordings`
- `/data/uploads/m3us`, `/data/uploads/epgs`
- `/var/run/dispatcharr`

### Environment Variables
Confirms all required variables are defined:
- `DJANGO_SECRET_KEY`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`
- `APP_DIR`, `DISPATCH_USER`

### Placeholder Substitution
Ensures all template placeholders have corresponding `sed` substitutions.

## Understanding Test Output

Each failed test provides:

1. **FAIL message**: What specifically failed
2. **WHY**: Explanation of why this matters for FreeBSD
3. **FIX**: Specific steps to resolve the issue

Example:
```
✗ FAIL: Found GNU-style sed -i syntax
  WHY: BSD sed requires an extension argument after -i
  FIX: Change 'sed -i "s/..."' to 'sed -i "" "s/..."'
```

## Adding New Tests

When adding FreeBSD-specific functionality:

1. Add a test to `test_freebsd_script.py` or `test_freebsd_compat.sh`
2. Include clear WHY and FIX messages
3. Run tests locally before pushing

## CI Integration

Add to your CI workflow:

```yaml
- name: FreeBSD Compatibility Check
  run: |
    ./tests/freebsd/test_freebsd_compat.sh
```

Or for Python:

```yaml
- name: FreeBSD Compatibility Check
  run: |
    pip install pytest
    python -m pytest tests/freebsd/ -v
```

## Common Issues and Fixes

### sed -i Syntax
**Problem**: GNU sed uses `sed -i 's/.../'`, BSD sed requires `sed -i '' 's/.../'`
**Fix**: Always use `sed -i ''` in the FreeBSD script

### Package Management
**Problem**: Using `apt-get install package`
**Fix**: Use `pkg install package`

### User Management
**Problem**: Using `useradd` or `groupadd`
**Fix**: Use `pw useradd` or `pw groupadd`

### Service Management
**Problem**: Using `systemctl enable --now service`
**Fix**: Use `sysrc service_enable="YES"` and `service X start`

### File Paths
**Problem**: Using `/etc/nginx/` or `/etc/systemd/`
**Fix**: Use `/usr/local/etc/nginx/` and `/usr/local/etc/rc.d/`
