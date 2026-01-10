#!/usr/bin/env bash
#
# FreeBSD Jail Test Runner for Dispatcharr
#
# This script creates a FreeBSD jail, pulls the latest changes from the repo,
# and runs freebsd_start.sh to test for breaking changes.
#
# Requirements:
#   - FreeBSD host with jail support
#   - Root privileges
#   - Internet access (for pkg and git)
#
# Usage:
#   ./test_in_jail.sh [OPTIONS]
#
# Options:
#   --jail-name NAME     Name of the jail (default: dispatcharr_test)
#   --jail-path PATH     Path for jail filesystem (default: /jails/dispatcharr_test)
#   --repo-url URL       Git repository URL (default: current origin)
#   --branch BRANCH      Git branch to test (default: current branch)
#   --keep-jail          Don't destroy jail after test
#   --rebuild            Force rebuild of jail even if it exists
#   --verbose            Show detailed output
#   --dry-run            Show what would be done without executing
#   --help               Show this help message
#

set -o pipefail

# Default configuration
JAIL_NAME="dispatcharr_test"
JAIL_PATH="/jails/dispatcharr_test"
JAIL_IP="192.168.1.200"  # Adjust for your network
REPO_URL=""
BRANCH=""
KEEP_JAIL=0
REBUILD=0
VERBOSE=0
DRY_RUN=0

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

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_step() {
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  $1${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

show_help() {
    cat << 'EOF'
FreeBSD Jail Test Runner for Dispatcharr

USAGE:
    ./test_in_jail.sh [OPTIONS]

OPTIONS:
    --jail-name NAME     Name of the jail (default: dispatcharr_test)
    --jail-path PATH     Path for jail filesystem (default: /jails/dispatcharr_test)
    --jail-ip IP         IP address for jail (default: 192.168.1.200)
    --repo-url URL       Git repository URL (default: auto-detect from .git)
    --branch BRANCH      Git branch to test (default: current branch)
    --keep-jail          Don't destroy jail after test
    --rebuild            Force rebuild of jail even if it exists
    --verbose            Show detailed output
    --dry-run            Show what would be done without executing
    --help               Show this help message

DESCRIPTION:
    This script automates testing of freebsd_start.sh by:
    1. Creating a fresh FreeBSD jail
    2. Cloning/pulling the repository
    3. Running the installation script with auto-confirm
    4. Validating that all services start correctly
    5. Running the compatibility test suite
    6. Reporting results

EXAMPLES:
    # Basic test with default settings
    sudo ./test_in_jail.sh

    # Test a specific branch
    sudo ./test_in_jail.sh --branch feature/new-feature

    # Keep jail for debugging
    sudo ./test_in_jail.sh --keep-jail --verbose

    # Test from a fork
    sudo ./test_in_jail.sh --repo-url https://github.com/user/Dispatcharr-freebsd.git

REQUIREMENTS:
    - FreeBSD 14.x or 15.x host
    - Root privileges
    - ZFS (recommended) or UFS for jail storage
    - Network connectivity

EXIT CODES:
    0    All tests passed
    1    Test failures detected
    2    Setup/configuration error

EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --jail-name)
                JAIL_NAME="$2"
                shift 2
                ;;
            --jail-path)
                JAIL_PATH="$2"
                shift 2
                ;;
            --jail-ip)
                JAIL_IP="$2"
                shift 2
                ;;
            --repo-url)
                REPO_URL="$2"
                shift 2
                ;;
            --branch)
                BRANCH="$2"
                shift 2
                ;;
            --keep-jail)
                KEEP_JAIL=1
                shift
                ;;
            --rebuild)
                REBUILD=1
                shift
                ;;
            --verbose)
                VERBOSE=1
                shift
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 2
                ;;
        esac
    done
}

# Run command (respects dry-run mode)
run_cmd() {
    if [ $DRY_RUN -eq 1 ]; then
        echo "[DRY-RUN] $*"
    else
        if [ $VERBOSE -eq 1 ]; then
            "$@"
        else
            "$@" >/dev/null 2>&1
        fi
    fi
}

# Run command in jail
jail_exec() {
    if [ $DRY_RUN -eq 1 ]; then
        echo "[DRY-RUN] jexec $JAIL_NAME $*"
    else
        if [ $VERBOSE -eq 1 ]; then
            jexec "$JAIL_NAME" "$@"
        else
            jexec "$JAIL_NAME" "$@" 2>&1
        fi
    fi
}

# Check prerequisites
check_prerequisites() {
    log_step "Checking Prerequisites"

    # Must be root
    if [ "$(id -u)" -ne 0 ]; then
        log_error "This script must be run as root"
        exit 2
    fi
    log_success "Running as root"

    # Must be FreeBSD
    if [ "$(uname -s)" != "FreeBSD" ]; then
        log_error "This script must be run on FreeBSD"
        exit 2
    fi
    log_success "Running on FreeBSD $(uname -r)"

    # Check for required tools
    local required_tools="jail jls jexec bsdinstall"
    for tool in $required_tools; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            log_error "Required tool not found: $tool"
            exit 2
        fi
    done
    log_success "Required tools available"

    # Auto-detect repo URL if not specified
    if [ -z "$REPO_URL" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
        if [ -d "$REPO_ROOT/.git" ]; then
            REPO_URL=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || echo "")
        fi
        if [ -z "$REPO_URL" ]; then
            REPO_URL="https://github.com/Dispatcharr/Dispatcharr.git"
            log_warn "Could not detect repo URL, using default: $REPO_URL"
        else
            log_info "Auto-detected repo URL: $REPO_URL"
        fi
    fi

    # Auto-detect branch if not specified
    if [ -z "$BRANCH" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
        if [ -d "$REPO_ROOT/.git" ]; then
            BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
        else
            BRANCH="main"
        fi
        log_info "Using branch: $BRANCH"
    fi
}

# Create or update the jail
setup_jail() {
    log_step "Setting Up Jail: $JAIL_NAME"

    # Check if jail already exists
    if jls -j "$JAIL_NAME" >/dev/null 2>&1; then
        if [ $REBUILD -eq 1 ]; then
            log_info "Stopping existing jail..."
            run_cmd jail -r "$JAIL_NAME" || true
            sleep 2
        else
            log_info "Jail already running, will reuse"
            return 0
        fi
    fi

    # Check if jail filesystem exists
    if [ -d "$JAIL_PATH" ]; then
        if [ $REBUILD -eq 1 ]; then
            log_info "Removing existing jail filesystem..."
            run_cmd rm -rf "$JAIL_PATH"
        else
            log_info "Jail filesystem exists, will reuse"
        fi
    fi

    # Create jail filesystem if needed
    if [ ! -d "$JAIL_PATH" ]; then
        log_info "Creating jail filesystem at $JAIL_PATH..."

        # Create directory
        run_cmd mkdir -p "$JAIL_PATH"

        # Fetch and extract base system
        FREEBSD_VERSION=$(freebsd-version -u | cut -d'-' -f1)
        ARCH=$(uname -m)

        log_info "Fetching FreeBSD $FREEBSD_VERSION base for $ARCH..."

        if [ $DRY_RUN -eq 0 ]; then
            # Try to fetch base.txz
            FETCH_URL="https://download.freebsd.org/releases/${ARCH}/${FREEBSD_VERSION}-RELEASE/base.txz"

            if ! fetch -o /tmp/base.txz "$FETCH_URL" 2>/dev/null; then
                # Try alternate URL format
                FETCH_URL="https://ftp.freebsd.org/pub/FreeBSD/releases/${ARCH}/${FREEBSD_VERSION}-RELEASE/base.txz"
                if ! fetch -o /tmp/base.txz "$FETCH_URL" 2>/dev/null; then
                    log_error "Failed to fetch base.txz from FreeBSD mirrors"
                    log_info "You may need to manually extract base.txz to $JAIL_PATH"
                    exit 2
                fi
            fi

            log_info "Extracting base system..."
            tar -xf /tmp/base.txz -C "$JAIL_PATH"
            rm -f /tmp/base.txz
        fi

        log_success "Jail filesystem created"
    fi

    # Create jail configuration
    log_info "Configuring jail..."

    if [ $DRY_RUN -eq 0 ]; then
        # Copy DNS resolution
        cp /etc/resolv.conf "$JAIL_PATH/etc/resolv.conf"

        # Create jail.conf entry if not exists
        if ! grep -q "^${JAIL_NAME} {" /etc/jail.conf 2>/dev/null; then
            cat >> /etc/jail.conf << EOF

${JAIL_NAME} {
    host.hostname = ${JAIL_NAME}.local;
    path = "${JAIL_PATH}";
    ip4.addr = "${JAIL_IP}";
    mount.devfs;
    allow.raw_sockets;
    exec.start = "/bin/sh /etc/rc";
    exec.stop = "/bin/sh /etc/rc.shutdown";
    exec.clean;
    persist;
}
EOF
        fi
    fi

    # Start the jail
    log_info "Starting jail..."
    if [ $DRY_RUN -eq 0 ]; then
        if ! jail -c "$JAIL_NAME" 2>/dev/null; then
            # Try starting with service
            service jail start "$JAIL_NAME" || {
                log_error "Failed to start jail"
                exit 2
            }
        fi
    fi

    # Wait for jail to be ready
    sleep 3

    # Verify jail is running
    if [ $DRY_RUN -eq 0 ]; then
        if ! jls -j "$JAIL_NAME" >/dev/null 2>&1; then
            log_error "Jail failed to start"
            exit 2
        fi
    fi

    log_success "Jail is running"

    # Bootstrap pkg in jail
    log_info "Bootstrapping pkg in jail..."
    jail_exec env ASSUME_ALWAYS_YES=yes pkg bootstrap || true
    jail_exec pkg update -f

    # Install git in jail
    log_info "Installing git in jail..."
    jail_exec pkg install -y git

    log_success "Jail setup complete"
}

# Clone/update repository in jail
setup_repo() {
    log_step "Setting Up Repository in Jail"

    local REPO_DIR="/root/Dispatcharr"

    # Check if repo exists
    if jail_exec test -d "$REPO_DIR/.git" 2>/dev/null; then
        log_info "Updating existing repository..."
        jail_exec sh -c "cd $REPO_DIR && git fetch origin && git checkout $BRANCH && git pull origin $BRANCH"
    else
        log_info "Cloning repository..."
        jail_exec rm -rf "$REPO_DIR" 2>/dev/null || true
        jail_exec git clone -b "$BRANCH" "$REPO_URL" "$REPO_DIR"
    fi

    log_success "Repository ready at $REPO_DIR"
}

# Run the installation script
run_installation() {
    log_step "Running Installation Script"

    local REPO_DIR="/root/Dispatcharr"

    log_info "Running freebsd_start.sh with auto-confirm..."

    # Set environment for auto-confirm
    local start_time=$(date +%s)

    if [ $DRY_RUN -eq 0 ]; then
        # Run the installation script
        jail_exec sh -c "cd $REPO_DIR && DISPATCHARR_AUTO_CONFIRM=yes bash freebsd_start.sh" 2>&1 | tee /tmp/install_output.log

        local exit_code=${PIPESTATUS[0]}
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))

        if [ $exit_code -eq 0 ]; then
            log_success "Installation completed in ${duration}s"
        else
            log_error "Installation failed with exit code $exit_code"
            log_error "Check /tmp/install_output.log for details"
            return 1
        fi
    else
        echo "[DRY-RUN] Would run: DISPATCHARR_AUTO_CONFIRM=yes bash freebsd_start.sh"
    fi
}

# Validate the installation
validate_installation() {
    log_step "Validating Installation"

    local failures=0

    # Check services are running
    log_info "Checking services..."

    local services=("dispatcharr" "dispatcharr_celery" "dispatcharr_celerybeat" "dispatcharr_daphne" "nginx" "postgresql" "redis")

    for svc in "${services[@]}"; do
        if jail_exec service "$svc" status >/dev/null 2>&1; then
            log_success "Service $svc is running"
        else
            log_error "Service $svc is NOT running"
            ((failures++))
        fi
    done

    # Check if nginx is responding
    log_info "Checking nginx response..."
    if jail_exec fetch -q -o /dev/null "http://localhost:9191/" 2>/dev/null; then
        log_success "Nginx is responding on port 9191"
    else
        log_warn "Nginx not responding (may need more time to start)"
    fi

    # Check if gunicorn socket exists
    log_info "Checking gunicorn socket..."
    if jail_exec test -S /var/run/dispatcharr/dispatcharr.sock 2>/dev/null; then
        log_success "Gunicorn socket exists"
    else
        log_error "Gunicorn socket not found"
        ((failures++))
    fi

    # Check directories
    log_info "Checking directories..."
    local dirs=("/data/logos" "/data/recordings" "/data/db" "/usr/local/dispatcharr")
    for dir in "${dirs[@]}"; do
        if jail_exec test -d "$dir" 2>/dev/null; then
            log_success "Directory $dir exists"
        else
            log_error "Directory $dir not found"
            ((failures++))
        fi
    done

    # Check database
    log_info "Checking PostgreSQL database..."
    if jail_exec su -l postgres -c "psql -lqt" 2>/dev/null | grep -q dispatcharr; then
        log_success "Database 'dispatcharr' exists"
    else
        log_error "Database 'dispatcharr' not found"
        ((failures++))
    fi

    return $failures
}

# Run the compatibility test suite
run_test_suite() {
    log_step "Running Compatibility Test Suite"

    local REPO_DIR="/root/Dispatcharr"

    # Run shell tests
    log_info "Running shell-based tests..."
    if jail_exec bash "$REPO_DIR/tests/freebsd/test_freebsd_compat.sh" 2>&1; then
        log_success "Shell tests passed"
    else
        log_error "Shell tests failed"
        return 1
    fi

    # Run Python tests if Python is available
    if jail_exec command -v python3 >/dev/null 2>&1; then
        log_info "Running Python tests..."
        if jail_exec python3 "$REPO_DIR/tests/freebsd/test_freebsd_script.py" 2>&1; then
            log_success "Python tests passed"
        else
            log_error "Python tests failed"
            return 1
        fi
    else
        log_warn "Python not available, skipping Python tests"
    fi

    return 0
}

# Cleanup jail
cleanup_jail() {
    log_step "Cleaning Up"

    if [ $KEEP_JAIL -eq 1 ]; then
        log_info "Keeping jail as requested"
        log_info "To access: jexec $JAIL_NAME /bin/sh"
        log_info "To stop: jail -r $JAIL_NAME"
        log_info "To remove: rm -rf $JAIL_PATH"
        return
    fi

    log_info "Stopping jail..."
    run_cmd jail -r "$JAIL_NAME" || true

    log_info "Removing jail filesystem..."
    run_cmd rm -rf "$JAIL_PATH"

    # Remove jail.conf entry
    if [ $DRY_RUN -eq 0 ]; then
        sed -i '' "/^${JAIL_NAME} {/,/^}/d" /etc/jail.conf 2>/dev/null || true
    fi

    log_success "Cleanup complete"
}

# Print final summary
print_summary() {
    local exit_code=$1

    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}                      JAIL TEST SUMMARY                               ${NC}"
    echo -e "${BOLD}══════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  Jail Name:    $JAIL_NAME"
    echo "  Branch:       $BRANCH"
    echo "  Repository:   $REPO_URL"
    echo ""

    if [ $exit_code -eq 0 ]; then
        echo -e "  ${GREEN}${BOLD}Result: ALL TESTS PASSED${NC}"
        echo ""
        echo "  The FreeBSD installation script is working correctly."
    else
        echo -e "  ${RED}${BOLD}Result: TESTS FAILED${NC}"
        echo ""
        echo "  Review the output above to identify failing components."
        echo "  Use --keep-jail --verbose for debugging."
    fi

    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════════════════════${NC}"
}

# Main execution
main() {
    parse_args "$@"

    echo ""
    echo -e "${BOLD}FreeBSD Jail Test Runner for Dispatcharr${NC}"
    echo ""

    local exit_code=0

    # Run test sequence
    check_prerequisites

    setup_jail || { exit_code=2; }

    if [ $exit_code -eq 0 ]; then
        setup_repo || { exit_code=2; }
    fi

    if [ $exit_code -eq 0 ]; then
        run_installation || { exit_code=1; }
    fi

    if [ $exit_code -eq 0 ]; then
        # Give services time to fully start
        log_info "Waiting for services to stabilize..."
        sleep 10

        validate_installation || { exit_code=1; }
    fi

    if [ $exit_code -eq 0 ]; then
        run_test_suite || { exit_code=1; }
    fi

    cleanup_jail

    print_summary $exit_code

    exit $exit_code
}

main "$@"
