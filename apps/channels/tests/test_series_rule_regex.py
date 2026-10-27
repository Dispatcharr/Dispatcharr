"""Series rules in Regex title mode with lookaheads and non-capturing groups.

Regex mode runs the title through the shared text query parser. A `(?...)`
group must reach the database as part of the pattern, not be split into
fragments that are invalid regular expressions.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import Recording
from apps.channels.tests.test_series_rule_dedup import (
    SeriesRuleDedupBaseTestCase,
    _set_series_rules,
)

User = get_user_model()

PREVIEW_URL = "/api/channels/series-rules/preview/"
RULES_URL = "/api/channels/series-rules/"
LOOKAHEAD = r"^(?!.*upcoming).*Devils"
# Postgres rejects Python-style named groups. Used to exercise invalid-query paths.
INVALID_REGEX = r"(?<league>x)"


@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class SeriesRuleRegexEvaluationTests(SeriesRuleDedupBaseTestCase):
    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_lookahead_rule_records_only_matching_programs(
        self, mock_release, mock_lock, mock_schedule, mock_artwork
    ):
        from apps.channels.tasks import evaluate_series_rules_impl

        _set_series_rules([{
            "tvg_id": "test.channel.1",
            "mode": "all",
            "title": LOOKAHEAD,
            "title_mode": "regex",
        }])
        self._create_program(2, title="Devils at the Garden", sub_title="Game 1")
        self._create_program(4, title="upcoming Devils preview", sub_title="Game 2")

        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        recording = Recording.objects.get()
        self.assertEqual(
            recording.custom_properties["program"]["title"], "Devils at the Garden"
        )

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_invalid_regex_rule_does_not_block_later_rules(
        self, mock_release, mock_lock, mock_schedule, mock_artwork
    ):
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(2, title="Good Show", sub_title="E1")
        _set_series_rules([
            {
                "tvg_id": "test.channel.1",
                "mode": "all",
                "title": INVALID_REGEX,
                "title_mode": "regex",
            },
            {
                "tvg_id": "test.channel.1",
                "mode": "all",
                "title": "Good Show",
                "title_mode": "exact",
            },
        ])

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)
        statuses = {d.get("title"): d.get("status") for d in result["details"]}
        self.assertEqual(statuses[INVALID_REGEX], "invalid_query")
        self.assertEqual(statuses["Good Show"], "ok")

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_unbalanced_paren_rule_schedules_nothing(
        self, mock_release, mock_lock, mock_schedule, mock_artwork
    ):
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(2, title="Good Show", sub_title="E1")
        self._create_program(4, title="Other Show", sub_title="E2")
        _set_series_rules([{
            "tvg_id": "test.channel.1",
            "mode": "all",
            "title": "Good (",
            "title_mode": "contains",
        }])

        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 0)


class SeriesRuleRegexPreviewTests(SeriesRuleDedupBaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient(REMOTE_ADDR="127.0.0.1")
        self.client.force_authenticate(
            user=User.objects.create_user(
                username="dvr-admin",
                password="pass",
                user_level=User.UserLevel.ADMIN,
            )
        )

    def _preview(self, title, title_mode="regex"):
        return self.client.post(
            PREVIEW_URL,
            {"tvg_id": "test.channel.1", "title": title, "title_mode": title_mode},
            format="json",
        )

    def test_lookahead_preview_returns_matches_instead_of_an_error(self):
        self._create_program(2, title="Devils at the Garden", sub_title="Game 1")
        self._create_program(4, title="upcoming Devils preview", sub_title="Game 2")

        response = self._preview(LOOKAHEAD)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [m["title"] for m in response.json()["matches"]]
        self.assertEqual(titles, ["Devils at the Garden"])

    def test_escaped_parens_and_optional_group_preview_returns_matches(self):
        self._create_program(2, title="Show (2024)", sub_title="E1")
        self._create_program(4, title="The Daily Show", sub_title="E2")
        self._create_program(6, title="Late Night Daily Show", sub_title="E3")

        escaped = self._preview(r"Show \(2024\)")
        optional = self._preview(r"^(The )?Daily Show")

        self.assertEqual(escaped.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [m["title"] for m in escaped.json()["matches"]], ["Show (2024)"]
        )
        self.assertEqual(optional.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [m["title"] for m in optional.json()["matches"]], ["The Daily Show"]
        )

    def test_or_between_regex_terms_still_matches_either(self):
        self._create_program(2, title="Devils at the Garden", sub_title="Game 1")
        self._create_program(4, title="Rangers at home", sub_title="Game 2")
        self._create_program(6, title="Islanders", sub_title="Game 3")

        response = self._preview("^Devils OR ^Rangers")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = {m["title"] for m in response.json()["matches"]}
        self.assertEqual(titles, {"Devils at the Garden", "Rangers at home"})

    def test_invalid_regex_preview_returns_400(self):
        response = self._preview(INVALID_REGEX)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid search pattern", response.json()["error"])

    def test_invalid_regex_save_returns_400(self):
        response = self.client.post(
            RULES_URL,
            {
                "tvg_id": "test.channel.1",
                "title": INVALID_REGEX,
                "title_mode": "regex",
                "mode": "all",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid title pattern", response.json()["error"])

    def test_quoted_phrase_next_to_text_preview_does_not_return_500(self):
        self._create_program(2, title="Devils at the Garden", sub_title="Game 1")
        response = self._preview('"Devils at" the', title_mode="contains")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [m["title"] for m in response.json()["matches"]]
        self.assertEqual(titles, ["Devils at the Garden"])
