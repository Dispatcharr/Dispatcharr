"""
Regression test for empty VOD category API responses wiping group selections.

When a provider transiently returns no movie/series categories, batch_create_categories
used to treat every existing relation as orphaned and delete them. On the next
successful refresh, groups were recreated disabled when auto_enable_new_groups_vod
is false.
"""
from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase

from apps.m3u.models import M3UAccount
from apps.vod.models import M3UVODCategoryRelation, VODCategory
from apps.vod.tasks import refresh_categories, refresh_vod_content

USER_AGENT_PATCH = patch(
    "apps.m3u.models.M3UAccount.get_user_agent",
    return_value=MagicMock(user_agent="Test/1.0"),
)


class EmptyVODCategoriesGuardTests(TransactionTestCase):
    def _setup_xc_account_with_movie_category(self):
        account = M3UAccount.objects.create(
            name="Test XC Provider",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        category = VODCategory.objects.create(
            name="NETFLIX MOVIES",
            category_type="movie",
        )
        relation = M3UVODCategoryRelation.objects.create(
            category=category,
            m3u_account=account,
            enabled=True,
        )
        return account, category, relation

    def test_empty_movie_categories_with_existing_relations_aborts(self):
        account, _category, _relation = self._setup_xc_account_with_movie_category()
        client = MagicMock()
        client.get_vod_categories.return_value = []

        result = refresh_categories(account.id, client=client)

        self.assertIsNone(result)
        client.get_series_categories.assert_not_called()

    def test_empty_movie_categories_without_existing_relations_allowed(self):
        account = M3UAccount.objects.create(
            name="New XC Provider",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        client = MagicMock()
        client.get_vod_categories.return_value = []
        client.get_series_categories.return_value = []

        movies, series = refresh_categories(account.id, client=client)

        self.assertEqual(movies, {})
        self.assertEqual(series, {})

    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.vod.tasks.cleanup_orphaned_vod_content")
    @patch("apps.vod.tasks.refresh_series")
    @patch("apps.vod.tasks.refresh_movies")
    @USER_AGENT_PATCH
    def test_refresh_vod_content_aborts_before_cleanup(
        self,
        _mock_user_agent,
        mock_refresh_movies,
        mock_refresh_series,
        mock_cleanup,
        _mock_ws,
    ):
        account, _category, relation = self._setup_xc_account_with_movie_category()
        mock_client = MagicMock()
        mock_client.get_vod_categories.return_value = []

        with patch("apps.vod.tasks.XtreamCodesClient") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client
            result = refresh_vod_content(account.id)

        self.assertIn("aborting VOD refresh to preserve existing category selections", result)
        mock_refresh_movies.assert_not_called()
        mock_refresh_series.assert_not_called()
        mock_cleanup.assert_not_called()
        self.assertTrue(
            M3UVODCategoryRelation.objects.filter(pk=relation.pk, enabled=True).exists()
        )

    @patch("apps.vod.tasks.batch_create_categories")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.vod.tasks.cleanup_orphaned_vod_content", return_value="ok")
    @patch("apps.vod.tasks.refresh_series")
    @patch("apps.vod.tasks.refresh_movies")
    @USER_AGENT_PATCH
    def test_non_empty_categories_proceed_normally(
        self,
        _mock_user_agent,
        mock_refresh_movies,
        mock_refresh_series,
        mock_cleanup,
        _mock_ws,
        mock_batch_create,
    ):
        account, category, relation = self._setup_xc_account_with_movie_category()
        mock_client = MagicMock()
        mock_client.get_vod_categories.return_value = [
            {"category_id": "1", "category_name": "NETFLIX MOVIES"},
        ]
        mock_client.get_series_categories.return_value = []
        mock_batch_create.side_effect = [
            {category.name: category},
            {},
        ]

        with patch("apps.vod.tasks.XtreamCodesClient") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client
            result = refresh_vod_content(account.id)

        self.assertIn("completed", result)
        mock_refresh_movies.assert_called_once()
        mock_refresh_series.assert_called_once()
        mock_cleanup.assert_called_once()
        self.assertTrue(
            M3UVODCategoryRelation.objects.filter(pk=relation.pk, enabled=True).exists()
        )
