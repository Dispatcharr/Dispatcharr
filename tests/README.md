# EPG Program Search API - Test Suite

Comprehensive test suite for the EPG Program Search API endpoint. Tests can be run against any Dispatcharr instance with configurable credentials and server settings.

## Features Tested

### Text Search Capabilities
- ✅ Simple text search
- ✅ AND operator (`premier AND league`)
- ✅ OR operator (`Newcastle OR Villa`)
- ✅ Nested parentheses (`(Newcastle OR NEW) AND (Villa OR AST)`)
- ✅ Whole word matching (prevent "NEW" from matching "News")
- ✅ Regex pattern matching (`^Premier` for titles starting with "Premier")
- ✅ Case-insensitive searching
- ✅ Description field searching

### Time Filtering
- ✅ `airing_at` - programs airing at specific time
- ✅ `start_after` / `start_before` - time range filtering
- ✅ `end_after` / `end_before` - end time filtering

### Channel & Stream Filtering
- ✅ Channel name filtering
- ✅ Channel ID filtering
- ✅ Stream name filtering
- ✅ Group name filtering (channel or stream groups)

### Response Features
- ✅ Field selection (customize response fields)
- ✅ Pagination (page number and page size)
- ✅ Response structure validation
- ✅ Nested channel and stream data

### Edge Cases
- ✅ Invalid datetime formats
- ✅ Empty search terms
- ✅ Special characters
- ✅ Maximum page size enforcement
- ✅ Empty result sets

## Installation

### Install Test Dependencies

```bash
cd tests
pip install -r requirements.txt
```

Or install globally:
```bash
pip install pytest requests python-dotenv
```

## Running Tests

### Quick Start (Local Development)

Run tests against localhost with default credentials:

```bash
cd tests
pytest test_epg_search_api.py -v
```

### Production/Remote Server Testing

Set environment variables for your Dispatcharr instance:

```bash
# Configure server
export DISPATCHARR_HOST=192.168.1.180
export DISPATCHARR_PORT=9191
export DISPATCHARR_USERNAME=admin
export DISPATCHARR_PASSWORD=your_password

# Run tests
pytest test_epg_search_api.py -v
```

### Using .env File

Create a `.env` file in the `tests/` directory:

```env
DISPATCHARR_HOST=192.168.1.180
DISPATCHARR_PORT=9191
DISPATCHARR_USERNAME=admin
DISPATCHARR_PASSWORD=your_password
DISPATCHARR_HTTPS=false
TEST_TIMESTAMP=2026-02-14T20:00:00Z
```

Then run:
```bash
pytest test_epg_search_api.py -v
```

### Run Specific Tests

Run a single test:
```bash
pytest test_epg_search_api.py::TestEPGSearchAPI::test_text_search_or_operator -v
```

Run a test class:
```bash
pytest test_epg_search_api.py::TestEPGSearchAPI -v
```

Run tests matching a pattern:
```bash
pytest test_epg_search_api.py -k "text_search" -v
```

### Run with Different Verbosity

```bash
# Verbose output
pytest test_epg_search_api.py -v

# Very verbose (show all output)
pytest test_epg_search_api.py -vv

# Quiet (minimal output)
pytest test_epg_search_api.py -q

# Show print statements
pytest test_epg_search_api.py -v -s
```

### Generate Test Report

```bash
# Generate HTML report
pytest test_epg_search_api.py -v --html=report.html --self-contained-html

# Generate JUnit XML (for CI/CD)
pytest test_epg_search_api.py -v --junitxml=report.xml
```

## Configuration Options

All configuration is via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DISPATCHARR_HOST` | Server hostname or IP | `localhost` |
| `DISPATCHARR_PORT` | Server port | `9191` |
| `DISPATCHARR_USERNAME` | API username | `admin` |
| `DISPATCHARR_PASSWORD` | API password | `admin` |
| `DISPATCHARR_HTTPS` | Use HTTPS (true/false) | `false` |
| `TEST_TIMESTAMP` | ISO 8601 timestamp for time-based tests | Current time |

## Test Results Interpretation

### Success Example
```
tests/test_epg_search_api.py::TestEPGSearchAPI::test_basic_search PASSED
tests/test_epg_search_api.py::TestEPGSearchAPI::test_text_search_and_operator PASSED
tests/test_epg_search_api.py::TestEPGSearchAPI::test_airing_at_filter PASSED
================================ 32 passed in 15.23s =================================
```

### Failure Example
```
tests/test_epg_search_api.py::TestEPGSearchAPI::test_basic_search FAILED

FAILED test_epg_search_api.py::TestEPGSearchAPI::test_basic_search - AssertionError: ...
```

### Skip Example (when server unavailable)
```
tests/test_epg_search_api.py::TestEPGSearchAPI SKIPPED (Could not authenticate...)
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: EPG Search API Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r tests/requirements.txt
      
      - name: Run tests
        env:
          DISPATCHARR_HOST: ${{ secrets.DISPATCHARR_HOST }}
          DISPATCHARR_PORT: ${{ secrets.DISPATCHARR_PORT }}
          DISPATCHARR_USERNAME: ${{ secrets.DISPATCHARR_USERNAME }}
          DISPATCHARR_PASSWORD: ${{ secrets.DISPATCHARR_PASSWORD }}
        run: |
          pytest tests/test_epg_search_api.py -v --junitxml=report.xml
      
      - name: Publish Test Results
        uses: EnricoMi/publish-unit-test-result-action@v2
        if: always()
        with:
          files: report.xml
```

## Troubleshooting

### Authentication Failures

If tests skip with "Could not authenticate":

1. **Check credentials**:
   ```bash
   curl -X POST "http://localhost:9191/api/accounts/token/" \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"admin"}'
   ```

2. **Verify server is running**:
   ```bash
   curl http://localhost:9191/api/swagger/
   ```

3. **Check environment variables**:
   ```bash
   env | grep DISPATCHARR
   ```

### Connection Timeouts

If tests timeout:

1. Check network connectivity
2. Verify firewall rules allow connections
3. Increase timeout in `DispatcharrAPIClient` class (edit `test_epg_search_api.py`)

### Test Data Issues

Some tests verify specific program data exists. If your EPG database is empty or has limited data:

- Tests may skip or have fewer results
- Time-based tests may fail if no programs match the test timestamp
- Solution: Import EPG data before running tests or adjust `TEST_TIMESTAMP`

### HTTPS/SSL Issues

For self-signed certificates:

```python
# Add to DispatcharrAPIClient.__init__()
self.session.verify = False  # Disable SSL verification (not recommended for production)
```

Or set environment variable:
```bash
export PYTHONHTTPSVERIFY=0
```

## Development

### Adding New Tests

1. Add test method to `TestEPGSearchAPI` class:
   ```python
   def test_my_new_feature(self, api_client):
       """Test description"""
       result = api_client.search_programs({"param": "value"})
       assert "results" in result
   ```

2. Run your new test:
   ```bash
   pytest test_epg_search_api.py::TestEPGSearchAPI::test_my_new_feature -v
   ```

### Debugging Tests

Enable verbose output and print statements:
```bash
pytest test_epg_search_api.py -vv -s --tb=long
```

Add debug logging in test:
```python
def test_debug_example(self, api_client):
    result = api_client.search_programs({"title": "test"})
    print(f"Result: {result}")  # Will show with -s flag
    assert "results" in result
```

## Test Coverage

Current test coverage includes:

- **32+ test cases** covering all major features
- **Text search**: 8 tests
- **Time filtering**: 2 tests
- **Channel/stream filtering**: 2 tests
- **Response features**: 3 tests
- **Edge cases**: 5+ tests
- **Response validation**: 2 tests

## Performance Benchmarking

Run with performance timing:
```bash
pytest test_epg_search_api.py -v --durations=10
```

This shows the 10 slowest tests, helping identify performance bottlenecks.

## Support

For issues or questions:
- Check the [API Documentation](../docs/EPG_PROGRAM_SEARCH_API.md)
- Review test output with `-vv` flag for detailed errors
- Check Dispatcharr logs for server-side issues

## License

Same as the main Dispatcharr project.
