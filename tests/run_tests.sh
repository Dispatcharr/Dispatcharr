#!/bin/bash
# Quick test runner for EPG Search API tests
# Usage: ./run_tests.sh [options]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default values
HOST=${DISPATCHARR_HOST:-localhost}
PORT=${DISPATCHARR_PORT:-9191}
USERNAME=${DISPATCHARR_USERNAME:-admin}
PASSWORD=${DISPATCHARR_PASSWORD:-admin}
HTTPS=${DISPATCHARR_HTTPS:-false}
VERBOSE="-v"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host)
            HOST="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -u|--username)
            USERNAME="$2"
            shift 2
            ;;
        -P|--password)
            PASSWORD="$2"
            shift 2
            ;;
        --https)
            HTTPS="true"
            shift
            ;;
        -q|--quiet)
            VERBOSE="-q"
            shift
            ;;
        -vv|--very-verbose)
            VERBOSE="-vv"
            shift
            ;;
        -k|--keyword)
            KEYWORD="$2"
            shift 2
            ;;
        --help)
            echo "EPG Search API Test Runner"
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  -h, --host HOST           Dispatcharr host (default: localhost)"
            echo "  -p, --port PORT           Dispatcharr port (default: 9191)"
            echo "  -u, --username USER       API username (default: admin)"
            echo "  -P, --password PASS       API password (default: admin)"
            echo "  --https                   Use HTTPS"
            echo "  -q, --quiet               Quiet output"
            echo "  -vv, --very-verbose       Very verbose output"
            echo "  -k, --keyword KEYWORD     Run tests matching keyword"
            echo "  --help                    Show this help"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Run all tests (localhost)"
            echo "  $0 -h 192.168.1.180 -u joe -P pass   # Remote server"
            echo "  $0 -k text_search                     # Only text search tests"
            echo "  $0 -vv                                # Very verbose output"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest is not installed${NC}"
    echo "Install with: pip install -r requirements.txt"
    exit 1
fi

# Display test configuration
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  EPG Program Search API - Test Suite${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "Server:     ${YELLOW}$( [ "$HTTPS" = "true" ] && echo "https" || echo "http" )://${HOST}:${PORT}${NC}"
echo -e "Username:   ${YELLOW}${USERNAME}${NC}"
echo -e "Password:   ${YELLOW}$(echo $PASSWORD | sed 's/./*/g')${NC}"
echo ""

# Set environment variables
export DISPATCHARR_HOST="$HOST"
export DISPATCHARR_PORT="$PORT"
export DISPATCHARR_USERNAME="$USERNAME"
export DISPATCHARR_PASSWORD="$PASSWORD"
export DISPATCHARR_HTTPS="$HTTPS"

# Build pytest command
PYTEST_CMD="pytest test_epg_search_api.py $VERBOSE"

if [ -n "$KEYWORD" ]; then
    PYTEST_CMD="$PYTEST_CMD -k $KEYWORD"
    echo -e "Filter:     ${YELLOW}$KEYWORD${NC}"
    echo ""
fi

# Run tests
echo -e "${GREEN}Running tests...${NC}"
echo ""

if $PYTEST_CMD; then
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ All tests passed!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}═══════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  ✗ Some tests failed${NC}"
    echo -e "${RED}═══════════════════════════════════════════════════════${NC}"
    exit 1
fi
