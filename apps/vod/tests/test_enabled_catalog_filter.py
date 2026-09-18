from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.vod.tasks import _provider_vod_fingerprint, _retain_enabled_vod_rows


class EnabledCatalogFilterTests(SimpleTestCase):
    def test_catalog_fingerprint_is_order_independent_and_change_sensitive(self):
        first = [
            {"stream_id": 1, "category_id": "10", "name": "Movie A"},
            {"stream_id": 2, "category_id": "11", "name": "Movie B"},
        ]

        self.assertEqual(
            _provider_vod_fingerprint(first),
            _provider_vod_fingerprint(list(reversed(first))),
        )
        self.assertNotEqual(
            _provider_vod_fingerprint(first),
            _provider_vod_fingerprint(
                [{**first[0], "name": "Movie A remastered"}, first[1]]
            ),
        )

    def test_retains_only_enabled_categories_and_enabled_uncategorized(self):
        enabled = SimpleNamespace(id=1)
        disabled = SimpleNamespace(id=2)
        uncategorized = SimpleNamespace(id=3)
        rows = [
            {"stream_id": 10, "category_id": "enabled"},
            {"stream_id": 11, "category_id": "disabled"},
            {"stream_id": 12, "category_id": "ignored"},
            {"stream_id": 13, "category_id": None},
            {"stream_id": 14, "category_id": "  enabled  "},
            "malformed",
        ]

        counts = _retain_enabled_vod_rows(
            rows,
            {
                "enabled": enabled,
                "disabled": disabled,
                "__uncategorized__": uncategorized,
            },
            {
                enabled.id: SimpleNamespace(enabled=True),
                disabled.id: SimpleNamespace(enabled=False),
                uncategorized.id: SimpleNamespace(enabled=True),
            },
        )

        self.assertEqual(
            [row["stream_id"] for row in rows],
            [10, 13, 14],
        )
        self.assertEqual(
            counts,
            {
                "provider_total": 6,
                "eligible_total": 3,
                "skipped_total": 3,
            },
        )

    def test_drops_uncategorized_rows_when_relation_is_disabled(self):
        uncategorized = SimpleNamespace(id=3)
        rows = [{"series_id": 20, "category_id": ""}]

        counts = _retain_enabled_vod_rows(
            rows,
            {"__uncategorized__": uncategorized},
            {uncategorized.id: SimpleNamespace(enabled=False)},
        )

        self.assertEqual(rows, [])
        self.assertEqual(counts["provider_total"], 1)
        self.assertEqual(counts["eligible_total"], 0)

    def test_drops_rows_when_category_relation_is_missing(self):
        category = SimpleNamespace(id=1)
        rows = [{"stream_id": 10, "category_id": "known"}]

        counts = _retain_enabled_vod_rows(
            rows,
            {"known": category},
            {},
        )

        self.assertEqual(rows, [])
        self.assertEqual(counts["skipped_total"], 1)
