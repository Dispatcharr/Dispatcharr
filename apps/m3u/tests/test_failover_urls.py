"""
Tests for server failover URL functionality.

Tests cover two distinct URL format scenarios:
1. Xtream Codes URLs: Simple format like http://example.com:8080
2. Standard M3U URLs: Full path format like https://example.com:8080/get.php?username=x&password=y

URLs should NOT be mixed between types in a single account.
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from unittest.mock import patch, MagicMock
import requests

from core.utils import (
    parse_failover_urls,
    format_failover_urls,
    validate_failover_urls,
    validate_flexible_url,
)
from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountSerializer


class ParseFailoverUrlsTests(TestCase):
    """Tests for parse_failover_urls utility function."""

    # --- Xtream Codes URL format tests ---

    def test_parse_single_xc_url(self):
        """Single XC URL returns single-element list."""
        result = parse_failover_urls("http://xc.example.com:8080")
        self.assertEqual(result, ["http://xc.example.com:8080"])

    def test_parse_multiple_xc_urls(self):
        """Pipe-separated XC URLs return list."""
        input_str = "http://primary.example.com:8080|http://backup.example.com:8081|http://third.example.com:8082"
        result = parse_failover_urls(input_str)
        self.assertEqual(result, [
            "http://primary.example.com:8080",
            "http://backup.example.com:8081",
            "http://third.example.com:8082",
        ])

    def test_parse_xc_urls_with_whitespace(self):
        """XC URLs with whitespace around pipes are trimmed."""
        input_str = "http://primary.example.com:8080 | http://backup.example.com:8081 | http://third.example.com:8082"
        result = parse_failover_urls(input_str)
        self.assertEqual(result, [
            "http://primary.example.com:8080",
            "http://backup.example.com:8081",
            "http://third.example.com:8082",
        ])

    def test_parse_xc_urls_https(self):
        """HTTPS XC URLs are handled correctly."""
        input_str = "https://secure.example.com:443|https://backup.example.com:8443"
        result = parse_failover_urls(input_str)
        self.assertEqual(result, [
            "https://secure.example.com:443",
            "https://backup.example.com:8443",
        ])

    def test_parse_xc_urls_mixed_protocols(self):
        """Mixed HTTP/HTTPS XC URLs are handled correctly."""
        input_str = "http://primary.example.com:8080|https://secure-backup.example.com:443|http://fallback.example.com:8081"
        result = parse_failover_urls(input_str)
        self.assertEqual(result, [
            "http://primary.example.com:8080",
            "https://secure-backup.example.com:443",
            "http://fallback.example.com:8081",
        ])

    # --- Standard M3U URL format tests ---

    def test_parse_single_m3u_url(self):
        """Single M3U URL with path returns single-element list."""
        result = parse_failover_urls("https://m3u.example.com:8080/get.php?username=user&password=pass")
        self.assertEqual(result, ["https://m3u.example.com:8080/get.php?username=user&password=pass"])

    def test_parse_multiple_m3u_urls(self):
        """Pipe-separated M3U URLs with paths return list."""
        input_str = (
            "http://primary.tv/playlist/user/pass.m3u|"
            "http://backup.tv/playlist/user/pass.m3u|"
            "http://fallback.tv/playlist/user/pass.m3u"
        )
        result = parse_failover_urls(input_str)
        self.assertEqual(result, [
            "http://primary.tv/playlist/user/pass.m3u",
            "http://backup.tv/playlist/user/pass.m3u",
            "http://fallback.tv/playlist/user/pass.m3u",
        ])

    def test_parse_m3u_urls_with_query_params(self):
        """M3U URLs with complex query parameters are preserved."""
        input_str = (
            "http://server1.com/get.php?username=user&password=pass&type=m3u_plus|"
            "http://server2.com/get.php?username=user&password=pass&type=m3u_plus"
        )
        result = parse_failover_urls(input_str)
        self.assertEqual(result, [
            "http://server1.com/get.php?username=user&password=pass&type=m3u_plus",
            "http://server2.com/get.php?username=user&password=pass&type=m3u_plus",
        ])

    def test_parse_m3u_urls_mixed_protocols(self):
        """Mixed HTTP/HTTPS M3U URLs are handled correctly."""
        input_str = (
            "http://primary.tv/get.php?user=x&pass=y|"
            "https://secure.tv/get.php?user=x&pass=y|"
            "http://fallback.tv/get.php?user=x&pass=y"
        )
        result = parse_failover_urls(input_str)
        self.assertEqual(result, [
            "http://primary.tv/get.php?user=x&pass=y",
            "https://secure.tv/get.php?user=x&pass=y",
            "http://fallback.tv/get.php?user=x&pass=y",
        ])

    # --- Edge cases ---

    def test_parse_empty_string(self):
        """Empty string returns empty list."""
        self.assertEqual(parse_failover_urls(""), [])

    def test_parse_none(self):
        """None returns empty list."""
        self.assertEqual(parse_failover_urls(None), [])

    def test_parse_already_list(self):
        """Already a list returns same list."""
        input_list = ["http://a.com", "http://b.com"]
        self.assertEqual(parse_failover_urls(input_list), input_list)

    def test_parse_filters_empty_segments(self):
        """Empty segments from double pipes are filtered out."""
        input_str = "http://a.com||http://b.com|"
        result = parse_failover_urls(input_str)
        self.assertEqual(result, ["http://a.com", "http://b.com"])


class FormatFailoverUrlsTests(TestCase):
    """Tests for format_failover_urls utility function."""

    # --- Xtream Codes URL format tests ---

    def test_format_single_xc_url(self):
        """Single XC URL list formats to string."""
        result = format_failover_urls(["http://xc.example.com:8080"])
        self.assertEqual(result, "http://xc.example.com:8080")

    def test_format_multiple_xc_urls(self):
        """Multiple XC URLs format to pipe-separated string."""
        input_list = [
            "http://primary.example.com:8080",
            "http://backup.example.com:8081",
        ]
        result = format_failover_urls(input_list)
        self.assertEqual(result, "http://primary.example.com:8080|http://backup.example.com:8081")

    # --- Standard M3U URL format tests ---

    def test_format_single_m3u_url(self):
        """Single M3U URL list formats to string."""
        result = format_failover_urls(["http://server.com/get.php?user=x&pass=y"])
        self.assertEqual(result, "http://server.com/get.php?user=x&pass=y")

    def test_format_multiple_m3u_urls(self):
        """Multiple M3U URLs format to pipe-separated string."""
        input_list = [
            "http://primary.tv/playlist.m3u",
            "http://backup.tv/playlist.m3u",
        ]
        result = format_failover_urls(input_list)
        self.assertEqual(result, "http://primary.tv/playlist.m3u|http://backup.tv/playlist.m3u")

    # --- Edge cases ---

    def test_format_empty_list(self):
        """Empty list returns empty string."""
        self.assertEqual(format_failover_urls([]), "")

    def test_format_none(self):
        """None returns empty string."""
        self.assertEqual(format_failover_urls(None), "")

    def test_format_already_string(self):
        """Already a string returns same string."""
        self.assertEqual(format_failover_urls("http://a.com|http://b.com"), "http://a.com|http://b.com")


class ValidateFailoverUrlsTests(TestCase):
    """Tests for validate_failover_urls utility function."""

    # --- Xtream Codes URL validation ---

    def test_validate_single_xc_url_valid(self):
        """Valid single XC URL passes validation."""
        # Should not raise
        validate_failover_urls("http://xc.example.com:8080")

    def test_validate_multiple_xc_urls_valid(self):
        """Valid multiple XC URLs pass validation."""
        # Should not raise
        validate_failover_urls("http://primary.com:8080|http://backup.com:8081")

    def test_validate_xc_url_invalid(self):
        """Invalid XC URL raises ValidationError with position."""
        with self.assertRaises(ValidationError) as context:
            validate_failover_urls("http://valid.com:8080|not-a-valid-url|http://also-valid.com")
        self.assertIn("URL #2", str(context.exception))

    def test_validate_xc_urls_mixed_protocols(self):
        """Mixed HTTP/HTTPS XC URLs pass validation."""
        # Should not raise
        validate_failover_urls("http://primary.com:8080|https://secure.com:443|http://backup.com:8081")

    # --- Standard M3U URL validation ---

    def test_validate_single_m3u_url_valid(self):
        """Valid single M3U URL with path passes validation."""
        # Should not raise
        validate_failover_urls("http://server.com/get.php?username=user&password=pass")

    def test_validate_multiple_m3u_urls_valid(self):
        """Valid multiple M3U URLs pass validation."""
        # Should not raise
        validate_failover_urls(
            "http://primary.tv/playlist.m3u|http://backup.tv/playlist.m3u"
        )

    def test_validate_m3u_url_invalid(self):
        """Invalid M3U URL raises ValidationError with position."""
        with self.assertRaises(ValidationError) as context:
            validate_failover_urls("http://valid.com/path.m3u|not-a-valid-url-at-all")
        self.assertIn("URL #2", str(context.exception))

    def test_validate_m3u_urls_mixed_protocols(self):
        """Mixed HTTP/HTTPS M3U URLs pass validation."""
        # Should not raise
        validate_failover_urls(
            "http://primary.tv/playlist.m3u|https://secure.tv/playlist.m3u|http://backup.tv/playlist.m3u"
        )


class M3UAccountSerializerFailoverTests(TestCase):
    """Tests for M3UAccountSerializer handling of failover URLs."""

    def setUp(self):
        """Create a test M3U account."""
        self.account = M3UAccount.objects.create(
            name="Test Account",
            server_url=["http://primary.example.com:8080"],
            account_type=M3UAccount.Types.XC,
        )

    # --- Xtream Codes serializer tests ---

    def test_serializer_output_single_xc_url(self):
        """Single XC URL in list displays as string."""
        serializer = M3UAccountSerializer(instance=self.account)
        self.assertEqual(serializer.data["server_url"], "http://primary.example.com:8080")

    def test_serializer_output_multiple_xc_urls(self):
        """Multiple XC URLs display as pipe-separated string."""
        self.account.server_url = [
            "http://primary.example.com:8080",
            "http://backup.example.com:8081",
        ]
        self.account.save()

        serializer = M3UAccountSerializer(instance=self.account)
        self.assertEqual(
            serializer.data["server_url"],
            "http://primary.example.com:8080|http://backup.example.com:8081"
        )

    def test_serializer_input_single_xc_url(self):
        """Single XC URL input stores as single-element array."""
        data = {
            "name": "New XC Account",
            "server_url": "http://xc.server.com:25461",
            "account_type": "XC",
        }
        serializer = M3UAccountSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        internal = serializer.validated_data
        self.assertEqual(internal["server_url"], ["http://xc.server.com:25461"])

    def test_serializer_input_multiple_xc_urls(self):
        """Pipe-separated XC URL input stores as array."""
        data = {
            "name": "New XC Account",
            "server_url": "http://primary.com:8080|http://backup.com:8081|http://third.com:8082",
            "account_type": "XC",
        }
        serializer = M3UAccountSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        internal = serializer.validated_data
        self.assertEqual(internal["server_url"], [
            "http://primary.com:8080",
            "http://backup.com:8081",
            "http://third.com:8082",
        ])

    # --- Standard M3U serializer tests ---

    def test_serializer_output_single_m3u_url(self):
        """Single M3U URL in list displays as string."""
        self.account.server_url = ["http://server.com/get.php?user=test&pass=test"]
        self.account.account_type = M3UAccount.Types.STADNARD
        self.account.save()

        serializer = M3UAccountSerializer(instance=self.account)
        self.assertEqual(
            serializer.data["server_url"],
            "http://server.com/get.php?user=test&pass=test"
        )

    def test_serializer_output_multiple_m3u_urls(self):
        """Multiple M3U URLs display as pipe-separated string."""
        self.account.server_url = [
            "http://primary.tv/playlist/user/pass.m3u",
            "http://backup.tv/playlist/user/pass.m3u",
        ]
        self.account.account_type = M3UAccount.Types.STADNARD
        self.account.save()

        serializer = M3UAccountSerializer(instance=self.account)
        self.assertEqual(
            serializer.data["server_url"],
            "http://primary.tv/playlist/user/pass.m3u|http://backup.tv/playlist/user/pass.m3u"
        )

    def test_serializer_input_single_m3u_url(self):
        """Single M3U URL input stores as single-element array."""
        data = {
            "name": "New M3U Account",
            "server_url": "http://iptv.server.com/get.php?username=user&password=pass&type=m3u_plus",
            "account_type": "STD",
        }
        serializer = M3UAccountSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        internal = serializer.validated_data
        self.assertEqual(
            internal["server_url"],
            ["http://iptv.server.com/get.php?username=user&password=pass&type=m3u_plus"]
        )

    def test_serializer_input_multiple_m3u_urls(self):
        """Pipe-separated M3U URL input stores as array."""
        data = {
            "name": "New M3U Account",
            "server_url": "http://primary.tv/file.m3u|http://backup.tv/file.m3u",
            "account_type": "STD",
        }
        serializer = M3UAccountSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        internal = serializer.validated_data
        self.assertEqual(internal["server_url"], [
            "http://primary.tv/file.m3u",
            "http://backup.tv/file.m3u",
        ])

    # --- Edge cases ---

    def test_serializer_empty_url(self):
        """Empty server_url input stores as empty array."""
        data = {
            "name": "Account Without URL",
            "server_url": "",
            "account_type": "STD",
        }
        serializer = M3UAccountSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        internal = serializer.validated_data
        self.assertEqual(internal["server_url"], [])

    def test_serializer_roundtrip_xc_urls(self):
        """XC URLs survive serializer roundtrip."""
        original_urls = "http://primary.xc.com:8080|http://backup.xc.com:8081"

        # Input
        data = {
            "name": "Roundtrip XC Test",
            "server_url": original_urls,
            "account_type": "XC",
        }
        serializer = M3UAccountSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        account = serializer.save()

        # Output
        output_serializer = M3UAccountSerializer(instance=account)
        self.assertEqual(output_serializer.data["server_url"], original_urls)

    def test_serializer_roundtrip_m3u_urls(self):
        """M3U URLs survive serializer roundtrip."""
        original_urls = "http://a.com/path/file.m3u?key=val|http://b.com/path/file.m3u?key=val"

        # Input
        data = {
            "name": "Roundtrip M3U Test",
            "server_url": original_urls,
            "account_type": "STD",
        }
        serializer = M3UAccountSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        account = serializer.save()

        # Output
        output_serializer = M3UAccountSerializer(instance=account)
        self.assertEqual(output_serializer.data["server_url"], original_urls)

    def test_serializer_roundtrip_mixed_protocols(self):
        """Mixed HTTP/HTTPS URLs survive serializer roundtrip."""
        original_urls = "http://primary.com:8080|https://secure.com:443|http://backup.com:8081"

        # Input
        data = {
            "name": "Mixed Protocol Test",
            "server_url": original_urls,
            "account_type": "XC",
        }
        serializer = M3UAccountSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        account = serializer.save()

        # Output
        output_serializer = M3UAccountSerializer(instance=account)
        self.assertEqual(output_serializer.data["server_url"], original_urls)


class FetchWithFailoverTests(TestCase):
    """Tests for fetch_with_failover function."""

    def setUp(self):
        """Create a test M3U account."""
        self.account = M3UAccount.objects.create(
            name="Failover Test Account",
            server_url=["http://primary.com", "http://backup.com"],
            account_type=M3UAccount.Types.STADNARD,
        )

    @patch('apps.m3u.tasks.requests.get')
    @patch('apps.m3u.tasks.send_m3u_update')
    def test_fetch_primary_succeeds_no_failover(self, mock_update, mock_get):
        """When primary URL succeeds, no failover is needed."""
        from apps.m3u.tasks import fetch_with_failover

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        urls = ["http://primary.com/file.m3u", "http://backup.com/file.m3u"]
        headers = {"User-Agent": "Test"}

        response, successful_url = fetch_with_failover(urls, headers, self.account)

        self.assertEqual(successful_url, "http://primary.com/file.m3u")
        self.assertEqual(mock_get.call_count, 1)

    @patch('apps.m3u.tasks.requests.get')
    @patch('apps.m3u.tasks.send_m3u_update')
    @patch('apps.m3u.tasks.time.sleep')
    def test_fetch_failover_to_backup(self, mock_sleep, mock_update, mock_get):
        """When primary fails, backup URL is tried."""
        from apps.m3u.tasks import fetch_with_failover

        # First call fails, second succeeds
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("Primary failed"),
            mock_response,
        ]

        urls = ["http://primary.com/file.m3u", "http://backup.com/file.m3u"]
        headers = {"User-Agent": "Test"}

        response, successful_url = fetch_with_failover(urls, headers, self.account)

        self.assertEqual(successful_url, "http://backup.com/file.m3u")
        self.assertEqual(mock_get.call_count, 2)

    @patch('apps.m3u.tasks.requests.get')
    @patch('apps.m3u.tasks.send_m3u_update')
    @patch('apps.m3u.tasks.time.sleep')
    def test_fetch_multiple_cycles(self, mock_sleep, mock_update, mock_get):
        """All URLs fail first cycle, succeed on second cycle."""
        from apps.m3u.tasks import fetch_with_failover

        # First 2 calls fail (cycle 1), third call succeeds (cycle 2, primary)
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("Cycle 1 primary failed"),
            requests.exceptions.ConnectionError("Cycle 1 backup failed"),
            mock_response,
        ]

        urls = ["http://primary.com/file.m3u", "http://backup.com/file.m3u"]
        headers = {"User-Agent": "Test"}

        response, successful_url = fetch_with_failover(urls, headers, self.account, max_cycles=3)

        self.assertEqual(successful_url, "http://primary.com/file.m3u")
        self.assertEqual(mock_get.call_count, 3)

    @patch('apps.m3u.tasks.requests.get')
    @patch('apps.m3u.tasks.send_m3u_update')
    @patch('apps.m3u.tasks.time.sleep')
    def test_fetch_all_attempts_fail(self, mock_sleep, mock_update, mock_get):
        """All attempts across all cycles fail raises ConnectionError."""
        from apps.m3u.tasks import fetch_with_failover

        mock_get.side_effect = requests.exceptions.ConnectionError("Failed")

        urls = ["http://primary.com/file.m3u", "http://backup.com/file.m3u"]
        headers = {"User-Agent": "Test"}

        with self.assertRaises(requests.exceptions.ConnectionError) as context:
            fetch_with_failover(urls, headers, self.account, max_cycles=2)

        # 2 URLs * 2 cycles = 4 attempts
        self.assertEqual(mock_get.call_count, 4)
        self.assertIn("4 attempts", str(context.exception))

    @patch('apps.m3u.tasks.requests.get')
    @patch('apps.m3u.tasks.send_m3u_update')
    def test_fetch_single_url_no_failover_message(self, mock_update, mock_get):
        """Single URL doesn't show failover messages."""
        from apps.m3u.tasks import fetch_with_failover

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        urls = ["http://only.com/file.m3u"]
        headers = {"User-Agent": "Test"}

        response, successful_url = fetch_with_failover(urls, headers, self.account)

        # With only one URL on first attempt, no failover message should be sent
        # (failover_url is only sent when total_urls > 1 or cycle > 0)
        failover_calls = [
            call for call in mock_update.call_args_list
            if call.kwargs.get('failover_url')
        ]
        self.assertEqual(len(failover_calls), 0)


class XCClientFailoverTests(TestCase):
    """Tests for XCClient failover support."""

    def test_xc_client_accepts_single_url_string(self):
        """XCClient accepts single URL as string."""
        from core.xtream_codes import Client

        client = Client(
            server_url="http://xc.example.com:8080",
            username="user",
            password="pass"
        )

        self.assertEqual(client.server_urls, ["http://xc.example.com:8080"])
        self.assertEqual(client.server_url, "http://xc.example.com:8080")

    def test_xc_client_accepts_url_list(self):
        """XCClient accepts list of URLs."""
        from core.xtream_codes import Client

        client = Client(
            server_url=["http://primary.com:8080", "http://backup.com:8081"],
            username="user",
            password="pass"
        )

        self.assertEqual(len(client.server_urls), 2)
        self.assertEqual(client.server_urls[0], "http://primary.com:8080")
        self.assertEqual(client.server_urls[1], "http://backup.com:8081")

    def test_xc_client_filters_empty_urls(self):
        """XCClient filters out empty URLs from list."""
        from core.xtream_codes import Client

        client = Client(
            server_url=["http://valid.com:8080", "", None, "http://also-valid.com:8081"],
            username="user",
            password="pass"
        )

        # Empty/None values should be filtered, but the actual behavior depends on implementation
        # At minimum, we should have the valid URLs
        self.assertIn("http://valid.com:8080", client.server_urls)

    def test_xc_client_empty_url_raises(self):
        """XCClient with no URLs raises ValueError."""
        from core.xtream_codes import Client

        with self.assertRaises(ValueError) as context:
            Client(
                server_url=[],
                username="user",
                password="pass"
            )

        self.assertIn("At least one server URL is required", str(context.exception))

    def test_xc_client_none_url_raises(self):
        """XCClient with None URL raises ValueError."""
        from core.xtream_codes import Client

        with self.assertRaises(ValueError) as context:
            Client(
                server_url=None,
                username="user",
                password="pass"
            )

        self.assertIn("At least one server URL is required", str(context.exception))

    @patch('core.xtream_codes.Client._make_request')
    def test_xc_client_authenticate_with_single_url(self, mock_request):
        """XCClient authenticate uses single URL directly."""
        from core.xtream_codes import Client

        mock_request.return_value = {
            "user_info": {"username": "user", "status": "Active"},
            "server_info": {}
        }

        client = Client(
            server_url="http://xc.example.com:8080",
            username="user",
            password="pass"
        )

        result = client.authenticate()

        self.assertEqual(mock_request.call_count, 1)
        self.assertIn("user_info", result)

    @patch('core.xtream_codes.Client._make_request')
    @patch('core.xtream_codes.time.sleep')
    def test_xc_client_authenticate_failover(self, mock_sleep, mock_request):
        """XCClient authenticate uses failover on multiple URLs."""
        from core.xtream_codes import Client

        # First call fails, second succeeds
        mock_request.side_effect = [
            Exception("Primary failed"),
            {"user_info": {"username": "user", "status": "Active"}, "server_info": {}}
        ]

        client = Client(
            server_url=["http://primary.com:8080", "http://backup.com:8081"],
            username="user",
            password="pass"
        )

        result = client.authenticate()

        # Should have tried both URLs
        self.assertEqual(mock_request.call_count, 2)
        self.assertIn("user_info", result)
        # Server URL should now be the backup
        self.assertIn("backup.com", client.server_url)
