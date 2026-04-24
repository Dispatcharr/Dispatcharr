from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.epg.models import EPGData, EPGSource, ProgramData

User = get_user_model()

SEARCH_URL = "/api/epg/programs/search/"


class ProgramSearchAPIViewTests(TestCase):
    """Tests for the /api/epg/programs/search/ endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.epg_source = EPGSource.objects.create(name="Test Source", source_type="xmltv")
        cls.epg = EPGData.objects.create(
            tvg_id="test-tvg", name="Test EPG", epg_source=cls.epg_source
        )

        now = timezone.now().replace(microsecond=0)

        # Premier League Football — airing now
        cls.prog_football = ProgramData.objects.create(
            epg=cls.epg,
            title="Premier League Football",
            description="Live coverage of the Premier League match.",
            start_time=now - timedelta(minutes=30),
            end_time=now + timedelta(hours=1),
        )

        # Newcastle vs Villa — also airing now
        cls.prog_newcastle = ProgramData.objects.create(
            epg=cls.epg,
            title="Newcastle vs Villa",
            description="Match highlights.",
            start_time=now - timedelta(minutes=15),
            end_time=now + timedelta(hours=2),
        )

        # BBC News — starts in 3 hours
        cls.prog_news = ProgramData.objects.create(
            epg=cls.epg,
            title="BBC News at Ten",
            description="The latest news from around the world.",
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=4),
        )

        # Nature Documentary — starts in 5 hours
        cls.prog_doc = ProgramData.objects.create(
            epg=cls.epg,
            title="Nature Documentary",
            description="Exploring wildlife in the Amazon.",
            start_time=now + timedelta(hours=5),
            end_time=now + timedelta(hours=6),
        )

        cls.now = now
        cls.user = User.objects.create_user(username="testuser", password="pass", user_level=1)

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR="127.0.0.1")
        self.client.force_authenticate(user=self.user)

    # ------------------------------------------------------------------
    # Response structure
    # ------------------------------------------------------------------

    def test_response_structure(self):
        """Response includes pagination envelope and all expected program fields."""
        response = self.client.get(SEARCH_URL, {"page_size": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)

        program = data["results"][0]
        for field in ("id", "title", "start_time", "end_time", "tvg_id", "channels", "streams"):
            self.assertIn(field, program)

    # ------------------------------------------------------------------
    # No filter — returns all programs
    # ------------------------------------------------------------------

    def test_no_filters_returns_all(self):
        """Omitting filters returns all seeded programs."""
        response = self.client.get(SEARCH_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 4)

    # ------------------------------------------------------------------
    # Title search
    # ------------------------------------------------------------------

    def test_title_simple_match(self):
        """Simple title search returns matching programs."""
        response = self.client.get(SEARCH_URL, {"title": "football"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["title"], "Premier League Football")

    def test_title_case_insensitive(self):
        """Title search is case-insensitive."""
        lower = self.client.get(SEARCH_URL, {"title": "football"}).json()
        upper = self.client.get(SEARCH_URL, {"title": "FOOTBALL"}).json()
        self.assertEqual(lower["count"], 1)
        self.assertEqual(upper["count"], 1)
        self.assertEqual(lower["results"][0]["title"], upper["results"][0]["title"])

    def test_title_and_operator(self):
        """AND operator requires both terms to be present in the title."""
        response = self.client.get(SEARCH_URL, {"title": "Premier AND League"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertIn("Premier", data["results"][0]["title"])

    def test_title_or_operator(self):
        """OR operator returns programs matching either term."""
        response = self.client.get(SEARCH_URL, {"title": "Newcastle OR Football"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [r["title"] for r in response.json()["results"]]
        self.assertIn("Premier League Football", titles)
        self.assertIn("Newcastle vs Villa", titles)

    def test_title_no_match_returns_empty(self):
        """Search with no matching title returns empty results."""
        response = self.client.get(SEARCH_URL, {"title": "XYZNONEXISTENT999"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])

    def test_title_whole_word_matching(self):
        """title_whole_words=true does not match partial words."""
        # 'new' as substring matches both 'Newcastle vs Villa' and 'BBC News at Ten'
        partial = self.client.get(SEARCH_URL, {"title": "new"}).json()
        whole = self.client.get(SEARCH_URL, {"title": "new", "title_whole_words": "true"}).json()
        # icontains matches 'new' inside 'Newcastle' and 'News'
        self.assertEqual(partial["count"], 2)
        # Whole-word \bnew\b matches neither 'Newcastle' nor 'News'
        self.assertEqual(whole["count"], 0)

    def test_title_regex(self):
        """title_regex=true applies the query as a regex pattern."""
        response = self.client.get(
            SEARCH_URL, {"title": "^Premier", "title_regex": "true"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for program in response.json()["results"]:
            self.assertTrue(program["title"].startswith("Premier"))

    def test_title_parenthetical_grouping(self):
        """Parenthetical groups with AND/OR are evaluated correctly."""
        # (Newcastle OR Football) AND (Villa OR League) should match both seeded programs:
        # "Premier League Football" matches Football AND League
        # "Newcastle vs Villa" matches Newcastle AND Villa
        response = self.client.get(
            SEARCH_URL, {"title": "(Newcastle OR Football) AND (Villa OR League)"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = {r["title"] for r in response.json()["results"]}
        self.assertIn("Premier League Football", titles)
        self.assertIn("Newcastle vs Villa", titles)
        self.assertNotIn("BBC News at Ten", titles)
        self.assertNotIn("Nature Documentary", titles)

    # ------------------------------------------------------------------
    # Description search
    # ------------------------------------------------------------------

    def test_description_simple_match(self):
        """Description search returns programs whose description contains the term."""
        response = self.client.get(SEARCH_URL, {"description": "Premier League"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["title"], "Premier League Football")

    def test_description_and_operator(self):
        """AND operator in description requires both terms."""
        response = self.client.get(SEARCH_URL, {"description": "latest AND news"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["title"], "BBC News at Ten")

    # ------------------------------------------------------------------
    # Time filters
    # ------------------------------------------------------------------

    def test_airing_at_returns_current_programs(self):
        """airing_at returns programs where start_time <= t < end_time."""
        ts = self.now.isoformat()
        response = self.client.get(SEARCH_URL, {"airing_at": ts})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [r["title"] for r in response.json()["results"]]
        self.assertIn("Premier League Football", titles)
        self.assertIn("Newcastle vs Villa", titles)
        self.assertNotIn("BBC News at Ten", titles)

    def test_start_after_filter(self):
        """start_after excludes programs that start before the given time."""
        cutoff = (self.now + timedelta(hours=4)).isoformat()
        response = self.client.get(SEARCH_URL, {"start_after": cutoff})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [r["title"] for r in response.json()["results"]]
        self.assertIn("Nature Documentary", titles)
        self.assertNotIn("Premier League Football", titles)
        self.assertNotIn("BBC News at Ten", titles)

    def test_start_before_filter(self):
        """start_before excludes programs that start after the given time."""
        cutoff = (self.now + timedelta(hours=1)).isoformat()
        response = self.client.get(SEARCH_URL, {"start_before": cutoff})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [r["title"] for r in response.json()["results"]]
        self.assertIn("Premier League Football", titles)
        self.assertIn("Newcastle vs Villa", titles)
        self.assertNotIn("Nature Documentary", titles)

    def test_invalid_datetime_returns_400(self):
        """An unparseable datetime value returns a 400 error."""
        response = self.client.get(SEARCH_URL, {"airing_at": "not-a-date"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    # ------------------------------------------------------------------
    # Field selection
    # ------------------------------------------------------------------

    def test_field_selection_limits_response_keys(self):
        """fields param restricts the keys present in each result."""
        response = self.client.get(SEARCH_URL, {"fields": "title,start_time,end_time"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for program in response.json()["results"]:
            self.assertIn("title", program)
            self.assertIn("start_time", program)
            self.assertIn("end_time", program)
            self.assertNotIn("description", program)
            self.assertNotIn("channels", program)
            self.assertNotIn("streams", program)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def test_pagination_page_size(self):
        """page_size limits the number of results returned."""
        response = self.client.get(SEARCH_URL, {"page_size": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["count"], 4)
        self.assertIsNotNone(data["next"])

    def test_pagination_second_page(self):
        """Page 2 returns different results from page 1."""
        page1 = self.client.get(SEARCH_URL, {"page": 1, "page_size": 2}).json()
        page2 = self.client.get(SEARCH_URL, {"page": 2, "page_size": 2}).json()
        ids_p1 = {r["id"] for r in page1["results"]}
        ids_p2 = {r["id"] for r in page2["results"]}
        self.assertTrue(ids_p1.isdisjoint(ids_p2))

    def test_page_size_capped_at_maximum(self):
        """page_size beyond the 500 maximum is clamped, not rejected."""
        response = self.client.get(SEARCH_URL, {"page_size": 10000})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # All 4 seeded programs are returned — request was accepted and clamped
        self.assertEqual(data["count"], 4)
        self.assertEqual(len(data["results"]), 4)
