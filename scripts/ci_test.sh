#!/usr/bin/env bash
#
# CI Test Script for FreeBSD Compatibility
#
# This script runs static analysis and compatibility tests that don't require
# a full FreeBSD environment. It's suitable for GitHub Actions or other CI systems.
#
# Usage:
#   ./ci_test.sh [--verbose]
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERBOSE=0

# Colors
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    BOLD=''
    NC=''
fi

log_step() {
    echo ""
    echo -e "${BOLD}━━━ $1 ━━━${NC}"
}

log_pass() {
    echo -e "  ${GREEN}✓${NC} $1"
}

log_fail() {
    echo -e "  ${RED}✗${NC} $1"
}

# Parse args
if [ "$1" = "--verbose" ] || [ "$1" = "-v" ]; then
    VERBOSE=1
fi

echo ""
echo -e "${BOLD}FreeBSD Compatibility CI Tests${NC}"
echo ""

FAILURES=0

# Test 1: Script exists
log_step "Checking required files"

if [ -f "$PROJECT_ROOT/freebsd_start.sh" ]; then
    log_pass "freebsd_start.sh exists"
else
    log_fail "freebsd_start.sh not found"
    ((FAILURES++))
fi

if [ -f "$PROJECT_ROOT/tests/freebsd/test_freebsd_compat.sh" ]; then
    log_pass "test_freebsd_compat.sh exists"
else
    log_fail "test_freebsd_compat.sh not found"
    ((FAILURES++))
fi

if [ -f "$PROJECT_ROOT/tests/freebsd/test_freebsd_script.py" ]; then
    log_pass "test_freebsd_script.py exists"
else
    log_fail "test_freebsd_script.py not found"
    ((FAILURES++))
fi

# Test 2: Bash syntax check
log_step "Checking bash syntax"

if bash -n "$PROJECT_ROOT/freebsd_start.sh" 2>/dev/null; then
    log_pass "freebsd_start.sh has valid syntax"
else
    log_fail "freebsd_start.sh has syntax errors"
    ((FAILURES++))
fi

if bash -n "$PROJECT_ROOT/tests/freebsd/test_freebsd_compat.sh" 2>/dev/null; then
    log_pass "test_freebsd_compat.sh has valid syntax"
else
    log_fail "test_freebsd_compat.sh has syntax errors"
    ((FAILURES++))
fi

# Test 3: Python syntax check
log_step "Checking Python syntax"

if python3 -m py_compile "$PROJECT_ROOT/tests/freebsd/test_freebsd_script.py" 2>/dev/null; then
    log_pass "test_freebsd_script.py has valid syntax"
else
    log_fail "test_freebsd_script.py has syntax errors"
    ((FAILURES++))
fi

# Test 4: Run shell compatibility tests
log_step "Running shell compatibility tests"

if [ $VERBOSE -eq 1 ]; then
    "$PROJECT_ROOT/tests/freebsd/test_freebsd_compat.sh" --verbose
    SHELL_RESULT=$?
else
    "$PROJECT_ROOT/tests/freebsd/test_freebsd_compat.sh" 2>&1
    SHELL_RESULT=$?
fi

if [ $SHELL_RESULT -eq 0 ]; then
    log_pass "Shell tests passed"
else
    log_fail "Shell tests failed"
    ((FAILURES++))
fi

# Test 5: Run Python tests
log_step "Running Python compatibility tests"

if python3 "$PROJECT_ROOT/tests/freebsd/test_freebsd_script.py" 2>&1; then
    log_pass "Python tests passed"
else
    log_fail "Python tests failed"
    ((FAILURES++))
fi

# Summary
echo ""
echo -e "${BOLD}════════════════════════════════════════${NC}"
if [ $FAILURES -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All CI tests passed!${NC}"
    exit 0
else
    echo -e "${RED}${BOLD}$FAILURES test(s) failed${NC}"
    exit 1
fi
