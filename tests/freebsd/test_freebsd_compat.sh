#!/usr/bin/env bash
#
# FreeBSD Compatibility Test Suite - Shell Version
#
# This script tests freebsd_start.sh for common compatibility issues.
# It can run on both FreeBSD and Linux for CI purposes.
#
# Usage:
#   ./test_freebsd_compat.sh           # Run all tests
#   ./test_freebsd_compat.sh --verbose # Run with extra detail
#   ./test_freebsd_compat.sh --help    # Show help
#

set -o pipefail

# Colors for output (disabled if not a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    BOLD=''
    NC=''
fi

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE=0

# Script paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FREEBSD_SCRIPT="$PROJECT_ROOT/freebsd_start.sh"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"

# Show help
show_help() {
    cat << 'EOF'
FreeBSD Compatibility Test Suite

USAGE:
    ./test_freebsd_compat.sh [OPTIONS]

OPTIONS:
    --verbose, -v    Show detailed output for each test
    --help, -h       Show this help message

DESCRIPTION:
    This script validates that freebsd_start.sh remains compatible with
    FreeBSD after upstream changes. Run it before merging changes to
    catch compatibility issues early.

TESTS PERFORMED:
    - Script syntax validation (BSD shell compatibility)
    - BSD sed syntax verification
    - Linux command detection (should not be present)
    - FreeBSD command verification (should be present)
    - RC script structure validation
    - Nginx configuration checks
    - Directory structure validation
    - Environment variable checks

EXIT CODES:
    0    All tests passed
    1    One or more tests failed

EXAMPLES:
    # Run all tests
    ./test_freebsd_compat.sh

    # Run with verbose output
    ./test_freebsd_compat.sh --verbose

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Logging functions
log_header() {
    echo ""
    echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${BLUE}  $1${NC}"
    echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

log_test() {
    ((TESTS_RUN++))
    if [ $VERBOSE -eq 1 ]; then
        echo -e "\n${BOLD}TEST $TESTS_RUN:${NC} $1"
    fi
}

log_pass() {
    ((TESTS_PASSED++))
    echo -e "  ${GREEN}✓ PASS:${NC} $1"
}

log_fail() {
    ((TESTS_FAILED++))
    echo -e "  ${RED}✗ FAIL:${NC} $1"
}

log_detail() {
    if [ $VERBOSE -eq 1 ]; then
        echo -e "    ${YELLOW}→${NC} $1"
    fi
}

log_fix() {
    echo -e "    ${YELLOW}FIX:${NC} $1"
}

log_why() {
    echo -e "    ${BLUE}WHY:${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_header "Checking Prerequisites"

    log_test "freebsd_start.sh exists"
    if [ -f "$FREEBSD_SCRIPT" ]; then
        log_pass "freebsd_start.sh found at $FREEBSD_SCRIPT"
    else
        log_fail "freebsd_start.sh not found"
        log_why "The FreeBSD installation depends on this script"
        log_fix "Ensure freebsd_start.sh is in the project root"
        return 1
    fi

    log_test "requirements.txt exists"
    if [ -f "$REQUIREMENTS_FILE" ]; then
        log_pass "requirements.txt found"
    else
        log_fail "requirements.txt not found"
        log_why "FreeBSD script filters this file for compatible packages"
        log_fix "Ensure requirements.txt is in the project root"
        return 1
    fi

    log_test "Script is readable"
    if [ -r "$FREEBSD_SCRIPT" ]; then
        log_pass "Script is readable"
    else
        log_fail "Script is not readable"
        log_fix "Check file permissions: chmod +r freebsd_start.sh"
        return 1
    fi
}

# Test shell syntax
test_shell_syntax() {
    log_header "Testing Shell Syntax"

    # Test 1: Valid shebang
    log_test "Script has valid shebang"
    local first_line
    first_line=$(head -n 1 "$FREEBSD_SCRIPT")

    if [[ "$first_line" =~ ^#!.*bash ]] || [[ "$first_line" =~ ^#!/bin/sh ]]; then
        log_pass "Valid shebang: $first_line"
    else
        log_fail "Invalid or missing shebang: $first_line"
        log_why "FreeBSD requires a valid shebang for script execution"
        log_fix "First line should be: #!/usr/bin/env bash"
    fi

    # Test 2: Bash syntax check
    log_test "Script passes bash syntax check"
    if bash -n "$FREEBSD_SCRIPT" 2>/dev/null; then
        log_pass "No syntax errors detected"
    else
        log_fail "Bash syntax errors found"
        log_why "Syntax errors will prevent the script from running"
        log_fix "Run 'bash -n freebsd_start.sh' to see errors"
    fi

    # Test 3: No bashisms that break on strict POSIX
    log_test "Uses 'set -e' for error handling"
    if grep -q "set -e" "$FREEBSD_SCRIPT"; then
        log_pass "Script uses 'set -e'"
    else
        log_fail "Script doesn't use 'set -e'"
        log_why "Scripts should exit on error to prevent partial installations"
        log_fix "Add 'set -e' near the top of the script"
    fi
}

# Test BSD-specific syntax
test_bsd_syntax() {
    log_header "Testing BSD-Specific Syntax"

    # Test: BSD sed syntax
    log_test "Uses BSD-compatible sed -i syntax"

    # Find all sed -i commands
    local gnu_sed_count
    gnu_sed_count=$(grep -E "sed\s+-i\s+['\"]s[|/]" "$FREEBSD_SCRIPT" 2>/dev/null | wc -l)

    local bsd_sed_count
    bsd_sed_count=$(grep -E "sed\s+-i\s+''" "$FREEBSD_SCRIPT" 2>/dev/null | wc -l)

    if [ "$gnu_sed_count" -gt 0 ]; then
        log_fail "Found $gnu_sed_count GNU-style sed -i commands"
        log_why "BSD sed requires an extension argument after -i"
        log_fix "Change 'sed -i \"s/...\"' to 'sed -i \"\" \"s/...\"'"
        if [ $VERBOSE -eq 1 ]; then
            echo "    Problematic lines:"
            grep -n -E "sed\s+-i\s+['\"]s[|/]" "$FREEBSD_SCRIPT" | head -5 | while read -r line; do
                echo "      $line"
            done
        fi
    else
        log_pass "No GNU-style sed -i found"
    fi

    if [ "$bsd_sed_count" -gt 0 ]; then
        log_pass "Found $bsd_sed_count BSD-style sed -i commands"
    else
        log_fail "No BSD-style sed -i found (expected at least some)"
        log_detail "The script should use 'sed -i ''' for in-place edits"
    fi
}

# Test for Linux-only commands
test_no_linux_commands() {
    log_header "Testing for Linux-Only Commands"

    declare -A linux_cmds=(
        ["systemctl"]="Use 'service' or 'sysrc' on FreeBSD"
        ["apt-get"]="Use 'pkg' on FreeBSD"
        ["apt "]="Use 'pkg' on FreeBSD"
        ["dpkg"]="Use 'pkg' on FreeBSD"
        ["journalctl"]="Use syslog or /var/log/messages on FreeBSD"
        ["/etc/systemd"]="Use /usr/local/etc/rc.d/ on FreeBSD"
    )

    local found_linux=0

    for cmd in "${!linux_cmds[@]}"; do
        log_test "No usage of '$cmd'"

        # Skip comments when searching, trim whitespace from wc output
        local matches
        matches=$(grep -v '^\s*#' "$FREEBSD_SCRIPT" | grep -c "$cmd" 2>/dev/null || true)
        matches=$(echo "$matches" | tr -d '[:space:]')
        matches=${matches:-0}

        if [ "$matches" -gt 0 ]; then
            log_fail "Found $matches occurrences of '$cmd'"
            log_why "This command is Linux-specific and won't work on FreeBSD"
            log_fix "${linux_cmds[$cmd]}"
            found_linux=1

            if [ $VERBOSE -eq 1 ]; then
                grep -n "$cmd" "$FREEBSD_SCRIPT" | grep -v '^\s*#' | head -3 | while read -r line; do
                    echo "      Line: $line"
                done
            fi
        else
            log_pass "No '$cmd' found in script"
        fi
    done

    # Special check for useradd/groupadd (must NOT be preceded by 'pw ')
    log_test "No bare 'useradd' (without 'pw')"
    local bare_useradd
    bare_useradd=$(grep -v '^\s*#' "$FREEBSD_SCRIPT" | grep -E '(^|[^w])useradd' | grep -v 'pw useradd' | wc -l | tr -d ' ')
    if [ "$bare_useradd" -gt 0 ]; then
        log_fail "Found bare 'useradd' without 'pw' prefix"
        log_why "FreeBSD uses 'pw useradd', not 'useradd'"
        log_fix "Change 'useradd' to 'pw useradd'"
    else
        log_pass "All useradd calls use 'pw useradd'"
    fi

    log_test "No bare 'groupadd' (without 'pw')"
    local bare_groupadd
    bare_groupadd=$(grep -v '^\s*#' "$FREEBSD_SCRIPT" | grep -E '(^|[^w])groupadd' | grep -v 'pw groupadd' | wc -l | tr -d ' ')
    if [ "$bare_groupadd" -gt 0 ]; then
        log_fail "Found bare 'groupadd' without 'pw' prefix"
        log_why "FreeBSD uses 'pw groupadd', not 'groupadd'"
        log_fix "Change 'groupadd' to 'pw groupadd'"
    else
        log_pass "All groupadd calls use 'pw groupadd'"
    fi
}

# Test for required FreeBSD commands
test_freebsd_commands() {
    log_header "Testing for Required FreeBSD Commands"

    declare -A freebsd_cmds=(
        ["pkg "]="Package management"
        ["sysrc"]="RC configuration"
        ["pw "]="User/group management"
        ["service "]="Service management"
    )

    for cmd in "${!freebsd_cmds[@]}"; do
        log_test "Uses FreeBSD command: $cmd"

        if grep -q "$cmd" "$FREEBSD_SCRIPT"; then
            log_pass "Found '$cmd' (${freebsd_cmds[$cmd]})"
        else
            log_fail "Missing '$cmd'"
            log_why "FreeBSD requires this command for ${freebsd_cmds[$cmd]}"
            log_fix "Ensure the script uses FreeBSD-native commands"
        fi
    done
}

# Test RC script generation
test_rc_scripts() {
    log_header "Testing RC Script Generation"

    # Required RC script elements
    declare -a rc_elements=(
        "# PROVIDE:"
        "# REQUIRE:"
        ". /etc/rc.subr"
        "rcvar="
        "run_rc_command"
        "load_rc_config"
    )

    for element in "${rc_elements[@]}"; do
        log_test "RC scripts include: $element"

        if grep -q "$element" "$FREEBSD_SCRIPT"; then
            log_pass "Found '$element'"
        else
            log_fail "Missing '$element'"
            log_why "FreeBSD rc.d scripts require this element"
            log_fix "Add '$element' to the generated rc.d scripts"
        fi
    done

    # Test for required services
    log_test "All required services have rc.d scripts"
    local services=("dispatcharr" "dispatcharr_celery" "dispatcharr_celerybeat" "dispatcharr_daphne")
    local missing_services=()

    for svc in "${services[@]}"; do
        if ! grep -q "\"$svc\"" "$FREEBSD_SCRIPT" && ! grep -q "/$svc" "$FREEBSD_SCRIPT"; then
            missing_services+=("$svc")
        fi
    done

    if [ ${#missing_services[@]} -eq 0 ]; then
        log_pass "All service scripts are generated"
    else
        log_fail "Missing services: ${missing_services[*]}"
        log_fix "Add rc.d script generation for missing services"
    fi
}

# Test nginx configuration
test_nginx_config() {
    log_header "Testing Nginx Configuration"

    # Required locations
    log_test "Nginx config has required location blocks"
    local locations=("location /" "location /static/" "location /assets/" "location /media/" "location /ws/")
    local missing_locations=()

    for loc in "${locations[@]}"; do
        if ! grep -q "$loc" "$FREEBSD_SCRIPT"; then
            missing_locations+=("$loc")
        fi
    done

    if [ ${#missing_locations[@]} -eq 0 ]; then
        log_pass "All location blocks present"
    else
        log_fail "Missing locations: ${missing_locations[*]}"
        log_fix "Add missing location blocks to nginx configuration"
    fi

    # WebSocket headers
    log_test "WebSocket location has upgrade headers"
    local ws_headers=("proxy_set_header Upgrade" "proxy_set_header Connection" "proxy_http_version 1.1")
    local missing_headers=()

    for header in "${ws_headers[@]}"; do
        if ! grep -q "$header" "$FREEBSD_SCRIPT"; then
            missing_headers+=("$header")
        fi
    done

    if [ ${#missing_headers[@]} -eq 0 ]; then
        log_pass "WebSocket upgrade headers present"
    else
        log_fail "Missing headers: ${missing_headers[*]}"
        log_why "WebSocket connections require upgrade headers"
        log_fix "Add missing headers to /ws/ location block"
    fi

    # FreeBSD nginx path
    log_test "Uses FreeBSD nginx path"
    if grep -q "/usr/local/etc/nginx" "$FREEBSD_SCRIPT"; then
        log_pass "Correct nginx path: /usr/local/etc/nginx"
    else
        log_fail "Wrong nginx path"
        log_why "FreeBSD nginx is installed in /usr/local/etc/nginx"
        log_fix "Set NGINX_CONFD=\"/usr/local/etc/nginx\""
    fi
}

# Test directory creation
test_directories() {
    log_header "Testing Directory Creation"

    local required_dirs=(
        "/data/logos"
        "/data/recordings"
        "/data/uploads/m3us"
        "/data/uploads/epgs"
        "/data/m3us"
        "/data/epgs"
        "/data/plugins"
        "/var/run/dispatcharr"
    )

    for dir in "${required_dirs[@]}"; do
        log_test "Creates directory: $dir"
        if grep -q "$dir" "$FREEBSD_SCRIPT"; then
            log_pass "Directory $dir is created"
        else
            log_fail "Missing directory creation: $dir"
            log_fix "Add 'mkdir -p $dir' to create_directories()"
        fi
    done
}

# Test environment variables
test_environment() {
    log_header "Testing Environment Variables"

    local required_vars=(
        "DJANGO_SECRET_KEY"
        "POSTGRES_DB"
        "POSTGRES_USER"
        "POSTGRES_PASSWORD"
        "POSTGRES_HOST"
        "APP_DIR"
        "DISPATCH_USER"
    )

    for var in "${required_vars[@]}"; do
        log_test "Defines variable: $var"
        if grep -q "${var}=" "$FREEBSD_SCRIPT"; then
            log_pass "$var is defined"
        else
            log_fail "$var is not defined"
            log_why "This variable is required for proper operation"
            log_fix "Add $var= to configure_variables()"
        fi
    done
}

# Test placeholder substitution
test_placeholders() {
    log_header "Testing Placeholder Substitution"

    # Find all placeholders
    local placeholders
    placeholders=$(grep -oE '__[A-Z_]+__' "$FREEBSD_SCRIPT" | sort -u)

    log_test "All placeholders have substitutions"
    local unsubstituted=()

    for ph in $placeholders; do
        # Check if there's a sed substitution for this placeholder
        if ! grep -q "s|$ph|" "$FREEBSD_SCRIPT"; then
            unsubstituted+=("$ph")
        fi
    done

    if [ ${#unsubstituted[@]} -eq 0 ]; then
        log_pass "All placeholders are substituted"
    else
        log_fail "Unsubstituted placeholders: ${unsubstituted[*]}"
        log_fix "Add sed substitution for each placeholder"
    fi
}

# Test auto-confirm feature
test_features() {
    log_header "Testing Script Features"

    log_test "Supports DISPATCHARR_AUTO_CONFIRM"
    if grep -q "DISPATCHARR_AUTO_CONFIRM" "$FREEBSD_SCRIPT"; then
        log_pass "Auto-confirm feature present"
    else
        log_fail "Auto-confirm not supported"
        log_why "This allows automated installations without interaction"
        log_fix "Add check for DISPATCHARR_AUTO_CONFIRM=yes in show_disclaimer()"
    fi

    log_test "Has disclaimer/warning"
    if grep -qi "disclaimer\|warning" "$FREEBSD_SCRIPT"; then
        log_pass "Disclaimer present"
    else
        log_fail "No disclaimer found"
        log_why "Users should be warned this is unsupported"
        log_fix "Add show_disclaimer() function"
    fi

    log_test "Shows summary after installation"
    if grep -qi "summary" "$FREEBSD_SCRIPT"; then
        log_pass "Summary function present"
    else
        log_fail "No summary found"
        log_fix "Add show_summary() to display access URLs"
    fi
}

# Print final summary
print_summary() {
    echo ""
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${BLUE}                    FREEBSD COMPATIBILITY TEST SUMMARY                ${NC}"
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  Tests Run:    ${BOLD}$TESTS_RUN${NC}"
    echo -e "  ${GREEN}Passed:       $TESTS_PASSED${NC}"
    echo -e "  ${RED}Failed:       $TESTS_FAILED${NC}"
    echo ""

    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "${GREEN}${BOLD}  ✓ All tests passed! FreeBSD compatibility verified.${NC}"
        echo ""
        return 0
    else
        echo -e "${RED}${BOLD}  ✗ Some tests failed! Review the output above.${NC}"
        echo ""
        echo -e "${YELLOW}  Each failed test includes:${NC}"
        echo -e "    ${BLUE}WHY:${NC} Why this matters for FreeBSD"
        echo -e "    ${YELLOW}FIX:${NC} How to resolve the issue"
        echo ""
        echo -e "  Run with ${BOLD}--verbose${NC} for more details."
        echo ""
        return 1
    fi
}

# Main execution
main() {
    echo -e "${BOLD}FreeBSD Compatibility Test Suite${NC}"
    echo -e "Testing: ${FREEBSD_SCRIPT}"
    echo ""

    check_prerequisites || exit 1

    test_shell_syntax
    test_bsd_syntax
    test_no_linux_commands
    test_freebsd_commands
    test_rc_scripts
    test_nginx_config
    test_directories
    test_environment
    test_placeholders
    test_features

    print_summary
    exit $?
}

main "$@"
