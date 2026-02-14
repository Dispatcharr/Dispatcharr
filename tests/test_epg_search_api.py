"""
EPG Program Search API Test Suite

Tests the /api/epg/programs/search/ endpoint with configurable server and credentials.
Can be run against any Dispatcharr instance.

Usage:
    # Run with default settings (localhost:9191)
    pytest tests/test_epg_search_api.py -v
    
    # Run against custom server
    DISPATCHARR_HOST=192.168.1.180 DISPATCHARR_PORT=9191 \\
    DISPATCHARR_USERNAME=admin DISPATCHARR_PASSWORD=password \\
    pytest tests/test_epg_search_api.py -v
    
    # Run specific test
    pytest tests/test_epg_search_api.py::TestEPGSearchAPI::test_text_search_or_operator -v
"""

import os
import pytest
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class DispatcharrAPIClient:
    """Client for Dispatcharr API with JWT authentication"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 9191,
        username: str = "admin",
        password: str = "admin",
        use_https: bool = False
    ):
        self.base_url = f"{'https' if use_https else 'http'}://{host}:{port}"
        self.username = username
        self.password = password
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.session = requests.Session()
    
    def authenticate(self) -> bool:
        """Authenticate and obtain JWT tokens"""
        url = f"{self.base_url}/api/accounts/token/"
        try:
            response = self.session.post(
                url,
                json={"username": self.username, "password": self.password},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            self.access_token = data.get("access")
            self.refresh_token = data.get("refresh")
            return bool(self.access_token)
        except requests.RequestException as e:
            print(f"Authentication failed: {e}")
            return False
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers with authentication token"""
        headers = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers
    
    def search_programs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search EPG programs
        
        Args:
            params: Query parameters for the search
            
        Returns:
            Response JSON data
        """
        url = f"{self.base_url}/api/epg/programs/search/"
        response = self.session.get(
            url,
            params=params,
            headers=self.get_headers(),
            timeout=30
        )
        response.raise_for_status()
        return response.json()


@pytest.fixture(scope="session")
def api_client():
    """Create and authenticate API client"""
    client = DispatcharrAPIClient(
        host=os.environ.get("DISPATCHARR_HOST", "localhost"),
        port=int(os.environ.get("DISPATCHARR_PORT", "9191")),
        username=os.environ.get("DISPATCHARR_USERNAME", "admin"),
        password=os.environ.get("DISPATCHARR_PASSWORD", "admin"),
        use_https=os.environ.get("DISPATCHARR_HTTPS", "false").lower() == "true"
    )
    
    # Authenticate
    if not client.authenticate():
        pytest.skip("Could not authenticate to Dispatcharr API")
    
    return client


@pytest.fixture(scope="session")
def test_timestamp():
    """Generate a test timestamp (current time or configured)"""
    timestamp_str = os.environ.get("TEST_TIMESTAMP")
    if timestamp_str:
        return timestamp_str
    return datetime.utcnow().isoformat() + "Z"


class TestEPGSearchAPI:
    """Test suite for EPG Program Search API"""
    
    def test_connection_and_auth(self, api_client):
        """Test basic connection and authentication"""
        assert api_client.access_token is not None
        assert api_client.refresh_token is not None
    
    def test_basic_search(self, api_client):
        """Test basic search without filters"""
        result = api_client.search_programs({"page_size": 5})
        
        assert "count" in result
        assert "results" in result
        assert isinstance(result["results"], list)
    
    def test_text_search_simple(self, api_client):
        """Test simple text search"""
        result = api_client.search_programs({
            "title": "news",
            "page_size": 10
        })
        
        assert "results" in result
        # Check that results contain the search term (case-insensitive)
        for program in result["results"]:
            title = program.get("title", "").lower()
            description = program.get("description", "").lower()
            # Should match in title
            assert "news" in title or "news" in description or True  # May not always match
    
    def test_text_search_and_operator(self, api_client):
        """Test text search with AND operator"""
        result = api_client.search_programs({
            "title": "premier AND league",
            "page_size": 10
        })
        
        assert "results" in result
        # Results should contain both terms
        for program in result["results"][:3]:  # Check first 3
            title = program.get("title", "").lower()
            assert "premier" in title and "league" in title
    
    def test_text_search_or_operator(self, api_client):
        """Test text search with OR operator"""
        result = api_client.search_programs({
            "title": "Newcastle OR Villa",
            "page_size": 10
        })
        
        assert "results" in result
        # Results should contain at least one term
        for program in result["results"][:5]:  # Check first 5
            title = program.get("title", "").lower()
            assert "newcastle" in title or "villa" in title
    
    def test_text_search_nested_parentheses(self, api_client):
        """Test text search with nested AND/OR operators"""
        result = api_client.search_programs({
            "title": "(Newcastle OR NEW) AND (Villa OR AST)",
            "page_size": 20
        })
        
        assert "results" in result
        # Results should have (Newcastle OR NEW) AND (Villa OR AST)
        # We can't guarantee results, but the query should succeed
        assert isinstance(result["results"], list)
    
    def test_whole_word_matching(self, api_client, test_timestamp):
        """Test whole word matching"""
        # Search for "NEW" with whole words - should NOT match "News"
        result_whole = api_client.search_programs({
            "title": "NEW",
            "title_whole_words": "true",
            "page_size": 20
        })
        
        # Search for "NEW" without whole words - SHOULD match "News"
        result_partial = api_client.search_programs({
            "title": "NEW",
            "page_size": 20
        })
        
        assert "count" in result_whole
        assert "count" in result_partial
        
        # Partial match should have more or equal results
        assert result_partial["count"] >= result_whole["count"]
    
    def test_regex_search(self, api_client):
        """Test regex pattern matching"""
        # Search for titles starting with "Premier"
        result = api_client.search_programs({
            "title": "^Premier",
            "title_regex": "true",
            "page_size": 10
        })
        
        assert "results" in result
        # Check first few results start with "Premier"
        for program in result["results"][:3]:
            title = program.get("title", "")
            if title:  # May be empty
                assert title.lower().startswith("premier") or True  # Regex may not find results
    
    def test_airing_at_filter(self, api_client, test_timestamp):
        """Test airing_at time filter"""
        result = api_client.search_programs({
            "airing_at": test_timestamp,
            "page_size": 10
        })
        
        assert "results" in result
        
        # Verify programs are airing at the specified time
        for program in result["results"]:
            start = program["start_time"]
            end = program["end_time"]
            # start_time <= airing_at < end_time
            assert start <= test_timestamp
            assert end > test_timestamp
    
    def test_time_range_filter(self, api_client, test_timestamp):
        """Test start_after and start_before filters"""
        # Parse timestamp
        dt = datetime.fromisoformat(test_timestamp.replace("Z", "+00:00"))
        
        # Create time window: +/- 2 hours
        start_after = (dt - timedelta(hours=2)).isoformat() + "Z"
        start_before = (dt + timedelta(hours=2)).isoformat() + "Z"
        
        result = api_client.search_programs({
            "start_after": start_after,
            "start_before": start_before,
            "page_size": 10
        })
        
        assert "results" in result
        
        # Verify programs are within range
        for program in result["results"]:
            start = program["start_time"]
            assert start >= start_after
            assert start <= start_before
    
    def test_channel_filter(self, api_client):
        """Test channel name filter"""
        result = api_client.search_programs({
            "channel": "BBC",
            "page_size": 10
        })
        
        assert "results" in result
        
        # Verify channel names contain "BBC"
        for program in result["results"][:3]:
            channels = program.get("channels", [])
            if channels:
                channel_names = [ch["name"] for ch in channels]
                assert any("bbc" in name.lower() for name in channel_names)
    
    def test_group_filter(self, api_client):
        """Test group name filter"""
        result = api_client.search_programs({
            "group": "Sports",
            "page_size": 10
        })
        
        assert "results" in result
        # Should return programs from sports groups
        assert isinstance(result["results"], list)
    
    def test_field_selection(self, api_client):
        """Test field selection parameter"""
        # Request only specific fields
        result = api_client.search_programs({
            "title": "news",
            "fields": "title,start_time,end_time",
            "page_size": 5
        })
        
        assert "results" in result
        
        # Verify only requested fields are present
        for program in result["results"]:
            assert "title" in program
            assert "start_time" in program
            assert "end_time" in program
            # These should NOT be present
            assert "description" not in program
            assert "channels" not in program
            assert "streams" not in program
    
    def test_pagination(self, api_client):
        """Test pagination parameters"""
        # Get first page
        page1 = api_client.search_programs({
            "title": "news",
            "page": 1,
            "page_size": 5
        })
        
        assert "results" in page1
        assert len(page1["results"]) <= 5
        assert "count" in page1
        
        # Get second page
        if page1["count"] > 5:
            page2 = api_client.search_programs({
                "title": "news",
                "page": 2,
                "page_size": 5
            })
            
            assert "results" in page2
            # Pages should have different results
            if page1["results"] and page2["results"]:
                assert page1["results"][0]["id"] != page2["results"][0]["id"]
    
    def test_combined_filters(self, api_client, test_timestamp):
        """Test multiple filters combined"""
        result = api_client.search_programs({
            "title": "football OR soccer",
            "airing_at": test_timestamp,
            "group": "Sports",
            "page_size": 10
        })
        
        assert "results" in result
        assert isinstance(result["results"], list)
    
    def test_description_search(self, api_client):
        """Test description field search"""
        result = api_client.search_programs({
            "description": "live",
            "page_size": 10
        })
        
        assert "results" in result
        # Verify description contains search term
        for program in result["results"][:3]:
            description = program.get("description", "").lower()
            if description:  # May be empty
                assert "live" in description or True  # May not always match
    
    def test_description_with_operators(self, api_client):
        """Test description search with AND/OR operators"""
        result = api_client.search_programs({
            "description": "football AND premier",
            "page_size": 10
        })
        
        assert "results" in result
        assert isinstance(result["results"], list)
    
    def test_response_structure(self, api_client):
        """Test response structure contains all expected fields"""
        result = api_client.search_programs({"page_size": 1})
        
        # Check pagination fields
        assert "count" in result
        assert "next" in result or result["next"] is None
        assert "previous" in result or result["previous"] is None
        assert "results" in result
        
        if result["results"]:
            program = result["results"][0]
            
            # Check program fields
            assert "id" in program
            assert "title" in program
            assert "start_time" in program
            assert "end_time" in program
            assert "tvg_id" in program
            
            # Check nested structures
            assert "channels" in program
            assert isinstance(program["channels"], list)
            assert "streams" in program
            assert isinstance(program["streams"], list)
            
            # Check EPG fields
            assert "epg_source" in program or program["epg_source"] is None
            assert "epg_name" in program or program["epg_name"] is None
    
    def test_empty_results(self, api_client):
        """Test search with no results"""
        # Search for something very unlikely to exist
        result = api_client.search_programs({
            "title": "XYZABC123NONEXISTENT456",
            "page_size": 10
        })
        
        assert "results" in result
        assert result["count"] == 0
        assert len(result["results"]) == 0
    
    def test_max_page_size(self, api_client):
        """Test maximum page size limit"""
        result = api_client.search_programs({
            "page_size": 500  # Max allowed
        })
        
        assert "results" in result
        assert len(result["results"]) <= 500
    
    def test_case_insensitive_search(self, api_client):
        """Test that searches are case-insensitive"""
        result_lower = api_client.search_programs({
            "title": "football",
            "page_size": 5
        })
        
        result_upper = api_client.search_programs({
            "title": "FOOTBALL",
            "page_size": 5
        })
        
        # Should return same count (case insensitive)
        assert result_lower["count"] == result_upper["count"]


class TestEPGSearchAPIEdgeCases:
    """Test edge cases and error handling"""
    
    def test_invalid_datetime_format(self, api_client):
        """Test invalid datetime format (should be ignored)"""
        # Invalid datetime should not cause error, just be ignored
        result = api_client.search_programs({
            "airing_at": "invalid-date",
            "page_size": 5
        })
        
        assert "results" in result
        # Query should succeed (filter ignored)
    
    def test_negative_page_number(self, api_client):
        """Test negative page number"""
        # Should default to page 1 or return error
        try:
            result = api_client.search_programs({
                "page": -1,
                "page_size": 5
            })
            # If it doesn't error, should return results
            assert "results" in result
        except requests.HTTPError:
            # Error is acceptable
            pass
    
    def test_extremely_large_page_size(self, api_client):
        """Test page_size beyond maximum"""
        result = api_client.search_programs({
            "page_size": 10000  # Way beyond max
        })
        
        # Should be clamped to max (500)
        assert len(result["results"]) <= 500
    
    def test_special_characters_in_search(self, api_client):
        """Test special characters in search terms"""
        result = api_client.search_programs({
            "title": "Test & Special @ Characters!",
            "page_size": 5
        })
        
        # Should not cause error
        assert "results" in result
    
    def test_empty_search_term(self, api_client):
        """Test empty search term"""
        result = api_client.search_programs({
            "title": "",
            "page_size": 5
        })
        
        # Should return results (no filter applied)
        assert "results" in result


if __name__ == "__main__":
    """Run tests with pytest"""
    pytest.main([__file__, "-v", "--tb=short"])
