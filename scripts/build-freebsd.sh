#!/usr/bin/env bash
#
# Dispatcharr FreeBSD Build Script
#
# Creates a release package for FreeBSD containing:
# - Pre-built frontend assets
# - Python application code
# - Installation scripts
# - RC.d service templates
#
# Usage:
#   ./build-freebsd.sh [OPTIONS]
#
# Options:
#   --version <ver>     Version string (default: from version.py or 0.0.0-dev)
#   --output <path>     Output directory (default: ./build)
#   --skip-frontend     Skip frontend build (use existing dist/)
#   --skip-tests        Skip compatibility tests
#   --clean             Clean build directory before building
#   --help              Show this help message
#
# Requirements:
#   - Node.js and npm (for frontend build)
#   - Python 3.x (for syntax validation)
#   - tar, gzip (for packaging)
#
# This script can run on FreeBSD, Linux, or macOS.
#

set -e
set -o pipefail

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default configuration
VERSION=""
OUTPUT_DIR="${PROJECT_ROOT}/build"
SKIP_FRONTEND=0
SKIP_TESTS=0
CLEAN_BUILD=0
PROJECT_NAME="dispatcharr"

# Colors (disabled if not a terminal)
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
    echo -e "${BOLD}━━━ $1 ━━━${NC}"
}

show_help() {
    cat << 'EOF'
Dispatcharr FreeBSD Build Script

USAGE:
    ./build-freebsd.sh [OPTIONS]

OPTIONS:
    --version <ver>     Version string to embed in package
                        Default: extracted from version.py or "0.0.0-dev"

    --output <path>     Output directory for build artifacts
                        Default: ./build

    --skip-frontend     Skip frontend build, use existing frontend/dist/
                        Useful for faster rebuilds when frontend hasn't changed

    --skip-tests        Skip FreeBSD compatibility tests
                        Not recommended for release builds

    --clean             Remove existing build directory before building

    --help              Show this help message

EXAMPLES:
    # Standard build
    ./build-freebsd.sh

    # Build specific version
    ./build-freebsd.sh --version 1.0.0

    # Quick rebuild (skip frontend)
    ./build-freebsd.sh --skip-frontend

    # Clean build to custom directory
    ./build-freebsd.sh --clean --output /tmp/dispatcharr-build

OUTPUT:
    Creates a tarball: dispatcharr-<version>-freebsd.tar.gz
    With checksums:    dispatcharr-<version>-freebsd.tar.gz.sha256
                       dispatcharr-<version>-freebsd.tar.gz.md5

REQUIREMENTS:
    - Node.js 18+ and npm (for frontend build)
    - Python 3.9+ (for syntax validation)
    - bash, tar, gzip, sha256sum/shasum

EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --version)
                VERSION="$2"
                shift 2
                ;;
            --output)
                OUTPUT_DIR="$2"
                shift 2
                ;;
            --skip-frontend)
                SKIP_FRONTEND=1
                shift
                ;;
            --skip-tests)
                SKIP_TESTS=1
                shift
                ;;
            --clean)
                CLEAN_BUILD=1
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
}

# Check for required tools
check_dependencies() {
    log_step "Checking Dependencies"

    local missing=()

    # Check Node.js (only if building frontend)
    if [ $SKIP_FRONTEND -eq 0 ]; then
        if command -v node >/dev/null 2>&1; then
            log_success "Node.js $(node --version)"
        else
            missing+=("node")
        fi

        if command -v npm >/dev/null 2>&1; then
            log_success "npm $(npm --version)"
        else
            missing+=("npm")
        fi
    fi

    # Check Python
    if command -v python3 >/dev/null 2>&1; then
        log_success "Python $(python3 --version 2>&1 | cut -d' ' -f2)"
    else
        missing+=("python3")
    fi

    # Check tar
    if command -v tar >/dev/null 2>&1; then
        log_success "tar available"
    else
        missing+=("tar")
    fi

    # Check checksum tools
    if command -v sha256sum >/dev/null 2>&1; then
        SHA256_CMD="sha256sum"
        log_success "sha256sum available"
    elif command -v shasum >/dev/null 2>&1; then
        SHA256_CMD="shasum -a 256"
        log_success "shasum available"
    else
        missing+=("sha256sum or shasum")
    fi

    if command -v md5sum >/dev/null 2>&1; then
        MD5_CMD="md5sum"
    elif command -v md5 >/dev/null 2>&1; then
        MD5_CMD="md5 -r"
    else
        MD5_CMD=""
        log_warn "md5sum not available, skipping MD5 checksum"
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Missing required tools: ${missing[*]}"
        echo ""
        echo "Please install the missing tools and try again."
        exit 1
    fi
}

# Determine version
determine_version() {
    log_step "Determining Version"

    if [ -n "$VERSION" ]; then
        log_info "Using specified version: $VERSION"
        return
    fi

    # Try to extract from version.py
    if [ -f "${PROJECT_ROOT}/version.py" ]; then
        VERSION=$(grep -oP "(?<=version = ['\"])[^'\"]*" "${PROJECT_ROOT}/version.py" 2>/dev/null || true)
        if [ -n "$VERSION" ]; then
            log_info "Extracted version from version.py: $VERSION"
            return
        fi
    fi

    # Try git tag
    if command -v git >/dev/null 2>&1 && [ -d "${PROJECT_ROOT}/.git" ]; then
        VERSION=$(git -C "${PROJECT_ROOT}" describe --tags --abbrev=0 2>/dev/null | sed 's/^v//' || true)
        if [ -n "$VERSION" ]; then
            log_info "Extracted version from git tag: $VERSION"
            return
        fi
    fi

    # Default version
    VERSION="0.0.0-dev"
    log_warn "Could not determine version, using: $VERSION"
}

# Build frontend
build_frontend() {
    log_step "Building Frontend"

    if [ $SKIP_FRONTEND -eq 1 ]; then
        if [ -d "${PROJECT_ROOT}/frontend/dist" ]; then
            log_info "Skipping frontend build (--skip-frontend)"
            log_success "Using existing frontend/dist/"
            return
        else
            log_error "frontend/dist/ does not exist. Cannot skip frontend build."
            exit 1
        fi
    fi

    cd "${PROJECT_ROOT}/frontend"

    log_info "Installing npm dependencies..."
    npm ci --legacy-peer-deps 2>&1 | tail -5

    log_info "Building frontend..."
    npm run build 2>&1 | tail -10

    if [ -d "dist" ]; then
        log_success "Frontend built successfully"
        log_info "Output size: $(du -sh dist | cut -f1)"
    else
        log_error "Frontend build failed - dist/ not created"
        exit 1
    fi

    cd "${PROJECT_ROOT}"
}

# Validate Python code
validate_python() {
    log_step "Validating Python Code"

    cd "${PROJECT_ROOT}"

    log_info "Checking Python syntax..."
    local errors=0

    # Check manage.py
    if python3 -m py_compile manage.py 2>/dev/null; then
        log_success "manage.py"
    else
        log_error "manage.py has syntax errors"
        ((errors++))
    fi

    # Check apps, core, dispatcharr directories
    for dir in apps core dispatcharr; do
        if [ -d "$dir" ]; then
            local count=$(find "$dir" -name "*.py" | wc -l | tr -d ' ')
            local failed=0
            while IFS= read -r -d '' file; do
                if ! python3 -m py_compile "$file" 2>/dev/null; then
                    log_error "Syntax error: $file"
                    ((failed++))
                fi
            done < <(find "$dir" -name "*.py" -print0)

            if [ $failed -eq 0 ]; then
                log_success "${dir}/ (${count} files)"
            else
                ((errors += failed))
            fi
        fi
    done

    if [ $errors -gt 0 ]; then
        log_error "Python validation failed with $errors errors"
        exit 1
    fi

    log_success "All Python files validated"
}

# Run compatibility tests
run_tests() {
    log_step "Running FreeBSD Compatibility Tests"

    if [ $SKIP_TESTS -eq 1 ]; then
        log_warn "Skipping tests (--skip-tests)"
        return
    fi

    cd "${PROJECT_ROOT}"

    if [ -x "scripts/ci_test.sh" ]; then
        if ./scripts/ci_test.sh; then
            log_success "All compatibility tests passed"
        else
            log_error "Compatibility tests failed"
            exit 1
        fi
    elif [ -x "tests/freebsd/test_freebsd_compat.sh" ]; then
        if bash tests/freebsd/test_freebsd_compat.sh; then
            log_success "All compatibility tests passed"
        else
            log_error "Compatibility tests failed"
            exit 1
        fi
    else
        log_warn "No test scripts found, skipping tests"
    fi
}

# Create the release package
create_package() {
    log_step "Creating Release Package"

    PACKAGE_NAME="${PROJECT_NAME}-${VERSION}-freebsd"
    BUILD_DIR="${OUTPUT_DIR}/${PACKAGE_NAME}"

    # Clean if requested
    if [ $CLEAN_BUILD -eq 1 ] && [ -d "${OUTPUT_DIR}" ]; then
        log_info "Cleaning build directory..."
        rm -rf "${OUTPUT_DIR}"
    fi

    # Create build directory
    mkdir -p "${BUILD_DIR}"

    log_info "Copying application code..."

    # Copy Python application
    cp -r "${PROJECT_ROOT}/apps" "${BUILD_DIR}/"
    cp -r "${PROJECT_ROOT}/core" "${BUILD_DIR}/"
    cp -r "${PROJECT_ROOT}/dispatcharr" "${BUILD_DIR}/"
    cp "${PROJECT_ROOT}/manage.py" "${BUILD_DIR}/"
    cp "${PROJECT_ROOT}/requirements.txt" "${BUILD_DIR}/"
    [ -f "${PROJECT_ROOT}/version.py" ] && cp "${PROJECT_ROOT}/version.py" "${BUILD_DIR}/"

    # Copy pre-built frontend
    log_info "Copying frontend assets..."
    mkdir -p "${BUILD_DIR}/frontend"
    cp -r "${PROJECT_ROOT}/frontend/dist" "${BUILD_DIR}/frontend/"
    cp "${PROJECT_ROOT}/frontend/package.json" "${BUILD_DIR}/frontend/"

    # Copy FreeBSD-specific files
    log_info "Copying FreeBSD files..."
    cp "${PROJECT_ROOT}/freebsd_start.sh" "${BUILD_DIR}/"
    cp -r "${PROJECT_ROOT}/scripts" "${BUILD_DIR}/"

    # Copy tests
    mkdir -p "${BUILD_DIR}/tests/freebsd"
    cp -r "${PROJECT_ROOT}/tests/freebsd/"* "${BUILD_DIR}/tests/freebsd/" 2>/dev/null || true

    # Copy documentation
    log_info "Copying documentation..."
    [ -f "${PROJECT_ROOT}/README.md" ] && cp "${PROJECT_ROOT}/README.md" "${BUILD_DIR}/"
    [ -f "${PROJECT_ROOT}/LICENSE" ] && cp "${PROJECT_ROOT}/LICENSE" "${BUILD_DIR}/"
    [ -f "${PROJECT_ROOT}/CHANGELOG.md" ] && cp "${PROJECT_ROOT}/CHANGELOG.md" "${BUILD_DIR}/"
    [ -f "${PROJECT_ROOT}/BUILD.md" ] && cp "${PROJECT_ROOT}/BUILD.md" "${BUILD_DIR}/"

    # Create BUILD_INFO
    log_info "Creating build info..."
    cat > "${BUILD_DIR}/BUILD_INFO" << EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Build Date: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Build Host: $(hostname)
Build OS: $(uname -s) $(uname -r)
Target: FreeBSD 14.x/15.x (amd64)
EOF

    # Add git info if available
    if command -v git >/dev/null 2>&1 && [ -d "${PROJECT_ROOT}/.git" ]; then
        echo "Git Commit: $(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || echo 'unknown')" >> "${BUILD_DIR}/BUILD_INFO"
        echo "Git Branch: $(git -C "${PROJECT_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')" >> "${BUILD_DIR}/BUILD_INFO"
    fi

    # Create installation wrapper
    log_info "Creating install wrapper..."
    cat > "${BUILD_DIR}/install.sh" << 'EOF'
#!/bin/sh
# Dispatcharr FreeBSD Installation Wrapper
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "Dispatcharr FreeBSD Installation"
echo "=========================================="
cat "${SCRIPT_DIR}/BUILD_INFO"
echo "=========================================="
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This script must be run as root"
    exit 1
fi

if [ "$(uname -s)" != "FreeBSD" ]; then
    echo "Error: This package is for FreeBSD only"
    exit 1
fi

exec "${SCRIPT_DIR}/freebsd_start.sh" "$@"
EOF
    chmod +x "${BUILD_DIR}/install.sh"
    chmod +x "${BUILD_DIR}/freebsd_start.sh"

    # Create tarball
    log_info "Creating tarball..."
    cd "${OUTPUT_DIR}"
    tar -czvf "${PACKAGE_NAME}.tar.gz" "${PACKAGE_NAME}" 2>&1 | tail -3

    # Generate checksums
    log_info "Generating checksums..."
    ${SHA256_CMD} "${PACKAGE_NAME}.tar.gz" > "${PACKAGE_NAME}.tar.gz.sha256"
    if [ -n "$MD5_CMD" ]; then
        ${MD5_CMD} "${PACKAGE_NAME}.tar.gz" > "${PACKAGE_NAME}.tar.gz.md5"
    fi

    log_success "Package created successfully"
}

# Print summary
print_summary() {
    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}                    BUILD COMPLETE                            ${NC}"
    echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  Package:   ${PACKAGE_NAME}.tar.gz"
    echo "  Version:   ${VERSION}"
    echo "  Location:  ${OUTPUT_DIR}/"
    echo ""
    echo "  Files created:"
    ls -lh "${OUTPUT_DIR}/${PACKAGE_NAME}.tar.gz"*
    echo ""
    echo "  Package size: $(du -sh "${OUTPUT_DIR}/${PACKAGE_NAME}.tar.gz" | cut -f1)"
    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "To install on FreeBSD:"
    echo ""
    echo "  tar -xzf ${PACKAGE_NAME}.tar.gz"
    echo "  cd ${PACKAGE_NAME}"
    echo "  sudo ./install.sh"
    echo ""
}

# Main execution
main() {
    echo ""
    echo -e "${BOLD}Dispatcharr FreeBSD Build Script${NC}"
    echo ""

    parse_args "$@"

    cd "${PROJECT_ROOT}"

    check_dependencies
    determine_version
    build_frontend
    validate_python
    run_tests
    create_package
    print_summary
}

main "$@"
