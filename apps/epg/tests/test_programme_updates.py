"""Public EPG updates preserve concurrent metadata and cache visibility."""

from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.epg.models import EPGData, EPGRevision, ProgramData
from apps.epg.services import (
    MISSING,
    ProgrammeUpdate,
    advance_epg_revision,
    get_epg_revision,
    update_programmes,
)


class ProgrammeUpdateTests(TestCase):
    def setUp(self):
        self.epg = EPGData.objects.create(name="Metadata updates", tvg_id="test")
        self.programme = ProgramData.objects.create(
            epg=self.epg,
            title="Original",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
            custom_properties={"category": "News", "rating": None},
        )
        self.revision = get_epg_revision()

    def update(self, expected=None, values=None, **kwargs):
        return update_programmes([
            ProgrammeUpdate(
                self.programme.pk,
                expected if expected is not None else {"title": "Original"},
                values if values is not None else {"title": "Updated"},
            )
        ], **kwargs)

    def test_changed_batch_advances_once_and_preserves_identity(self):
        original_identity = (
            self.programme.epg_id, self.programme.start_time,
            self.programme.end_time, self.programme.tvg_id,
        )
        with patch("apps.epg.services.advance_epg_revision", wraps=advance_epg_revision) as advance:
            result = self.update()
        self.programme.refresh_from_db()
        self.assertEqual(result.changed, (self.programme.pk,))
        self.assertEqual(self.programme.title, "Updated")
        self.assertNotEqual(get_epg_revision(), self.revision)
        advance.assert_called_once_with()
        self.assertEqual(original_identity, (
            self.programme.epg_id, self.programme.start_time,
            self.programme.end_time, self.programme.tvg_id,
        ))

    def test_top_level_merge_keeps_unrelated_properties(self):
        self.update(
            {"custom_properties": {"language": MISSING}},
            {"custom_properties": {"language": "en"}},
        )
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.custom_properties, {
            "category": "News", "rating": None, "language": "en",
        })

    def test_missing_null_and_delete_are_distinct(self):
        result = self.update(
            {"custom_properties": {"rating": MISSING}},
            {"custom_properties": {"rating": "PG"}},
        )
        self.assertEqual(result.conflicts, (self.programme.pk,))
        self.update(
            {"custom_properties": {"rating": None, "language": MISSING}},
            {"custom_properties": {"rating": MISSING, "language": None}},
        )
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.custom_properties, {"category": "News", "language": None})

    def test_stale_expected_value_does_not_overwrite_new_data(self):
        ProgramData.objects.filter(pk=self.programme.pk).update(title="Concurrent edit")
        result = self.update()
        self.assertEqual(result.conflicts, (self.programme.pk,))
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.title, "Concurrent edit")
        self.assertEqual(get_epg_revision(), self.revision)

    def test_optional_identity_condition_prevents_wrong_programme_update(self):
        result = self.update(
            {"title": "Original", "start_time": self.programme.start_time + timedelta(days=1)},
            {"title": "Updated"},
        )
        self.assertEqual(result.conflicts, (self.programme.pk,))

    def test_deleted_row_is_missing_and_never_recreated(self):
        programme_id = self.programme.pk
        self.programme.delete()
        result = update_programmes([ProgrammeUpdate(programme_id, {"title": "Original"}, {"title": "Updated"})])
        self.assertEqual(result.missing, (programme_id,))
        self.assertFalse(ProgramData.objects.filter(pk=programme_id).exists())
        self.assertEqual(get_epg_revision(), self.revision)

    def test_replacement_row_is_not_changed_by_stale_id(self):
        old_id = self.programme.pk
        self.programme.delete()
        replacement = ProgramData.objects.create(
            epg=self.epg, title="Original", start_time=timezone.now(), end_time=timezone.now(),
        )
        result = update_programmes([ProgrammeUpdate(old_id, {"title": "Original"}, {"title": "Updated"})])
        self.assertEqual(result.missing, (old_id,))
        replacement.refresh_from_db()
        self.assertEqual(replacement.title, "Original")

    def test_noop_and_empty_batch_leave_revision_unchanged(self):
        result = self.update(values={"title": "Original"})
        self.assertEqual(result.unchanged, (self.programme.pk,))
        self.assertEqual(update_programmes([]).changed, ())
        self.assertEqual(get_epg_revision(), self.revision)

    def test_preview_reports_would_change_without_writes(self):
        result = self.update(preview=True)
        self.assertEqual(result.changed, (self.programme.pk,))
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.title, "Original")
        self.assertEqual(get_epg_revision(), self.revision)

    def test_outer_rollback_reverts_data_and_revision(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.update()
                self.assertNotEqual(get_epg_revision(), self.revision)
                raise RuntimeError("roll back caller transaction")
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.title, "Original")
        self.assertEqual(get_epg_revision(), self.revision)

    def test_malformed_stored_properties_are_conflicts(self):
        for value in (None, [], "legacy", 5):
            with self.subTest(value=value):
                ProgramData.objects.filter(pk=self.programme.pk).update(custom_properties=value)
                result = self.update(
                    {"custom_properties": {"language": MISSING}},
                    {"custom_properties": {"language": "en"}},
                )
                self.assertEqual(result.conflicts, (self.programme.pk,))
                self.programme.refresh_from_db()
                self.assertEqual(self.programme.custom_properties, value)

    def test_boolean_and_number_expected_properties_are_not_equal(self):
        ProgramData.objects.filter(pk=self.programme.pk).update(custom_properties={"nested": {"flag": True}})
        result = self.update(
            {"custom_properties": {"nested": {"flag": 1}}},
            {"custom_properties": {"nested": {"flag": False}}},
        )
        self.assertEqual(result.conflicts, (self.programme.pk,))

    def test_entire_batch_validated_before_any_write(self):
        with self.assertRaises(ValidationError):
            update_programmes([
                ProgrammeUpdate(self.programme.pk, {"title": "Original"}, {"title": "Updated"}),
                ProgrammeUpdate(self.programme.pk + 1, {"title": "Original"}, {"title": "x" * 256}),
            ])
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.title, "Original")
        self.assertEqual(get_epg_revision(), self.revision)

    def test_invalid_fields_types_and_missing_preconditions_rejected(self):
        cases = [
            ({}, {"title": "Updated"}),
            ({"title": "Original"}, {"title": 123}),
            ({"title": "Original"}, {"title": None}),
            ({"title": "Original"}, {"title": ""}),
            ({"start_time": self.programme.start_time}, {"start_time": timezone.now()}),
            ({"epg_id": self.epg.pk}, {"epg_id": self.epg.pk}),
            ({"unknown": None}, {}),
            ({"custom_properties": {}}, {"custom_properties": {"language": "en"}}),
            ({"custom_properties": None}, {"custom_properties": {}}),
            ({"custom_properties": {"key": MISSING}}, {"custom_properties": {"key": float("nan")}}),
            ({"custom_properties": {"key": MISSING}}, {"custom_properties": {"key": {1: "bad key"}}}),
            ({"custom_properties": {"key": MISSING}}, {"custom_properties": {"key": (1, 2)}}),
            ({"custom_properties": {"key": MISSING}}, {"custom_properties": {"key": {"nested": MISSING}}}),
        ]
        for expected, values in cases:
            with self.subTest(expected=expected, values=values):
                with self.assertRaises(ValidationError):
                    self.update(expected, values)
        self.assertEqual(get_epg_revision(), self.revision)

    def test_positive_unique_ids_and_limit_are_enforced(self):
        for programme_id in (0, -1, True, "1"):
            with self.subTest(programme_id=programme_id):
                with self.assertRaises(ValidationError):
                    update_programmes([ProgrammeUpdate(programme_id, {}, {})])
        update = ProgrammeUpdate(self.programme.pk, {}, {})
        with self.assertRaises(ValidationError):
            update_programmes([update, update])
        with self.assertRaises(ValidationError):
            update_programmes(ProgrammeUpdate(i, {}, {}) for i in range(1, 502))

    def test_revision_recreation_uses_new_namespace(self):
        EPGRevision.objects.all().delete()
        self.assertNotEqual(get_epg_revision(), self.revision)

    def test_multiple_changes_share_one_revision_advance(self):
        second = ProgramData.objects.create(
            epg=self.epg, title="Second", start_time=timezone.now(), end_time=timezone.now(),
        )
        with patch("apps.epg.services.advance_epg_revision", wraps=advance_epg_revision) as advance:
            result = update_programmes([
                ProgrammeUpdate(second.pk, {"title": "Second"}, {"title": "Revised second"}),
                ProgrammeUpdate(self.programme.pk, {"title": "Original"}, {"title": "Revised first"}),
            ])
        self.assertEqual(set(result.changed), {self.programme.pk, second.pk})
        advance.assert_called_once_with()

    def test_conflict_does_not_prevent_other_valid_updates(self):
        second = ProgramData.objects.create(
            epg=self.epg, title="Second", start_time=timezone.now(), end_time=timezone.now(),
        )
        result = update_programmes([
            ProgrammeUpdate(self.programme.pk, {"title": "Stale"}, {"title": "Ignored"}),
            ProgrammeUpdate(second.pk, {"title": "Second"}, {"title": "Updated"}),
        ])
        self.assertEqual(result.conflicts, (self.programme.pk,))
        self.assertEqual(result.changed, (second.pk,))

    def test_deleted_missing_property_is_unchanged(self):
        result = self.update(
            {"custom_properties": {"absent": MISSING}},
            {"custom_properties": {"absent": MISSING}},
        )
        self.assertEqual(result.unchanged, (self.programme.pk,))
        self.assertEqual(get_epg_revision(), self.revision)

    def test_nullable_text_fields_accept_null_and_empty_string(self):
        result = self.update(
            {"sub_title": None, "description": None},
            {"sub_title": "", "description": "Details"},
        )
        self.assertEqual(result.changed, (self.programme.pk,))
        self.update({"description": "Details"}, {"description": None})
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.sub_title, "")
        self.assertIsNone(self.programme.description)

    def test_revision_failure_rolls_back_programme_changes(self):
        with patch("apps.epg.services.advance_epg_revision", side_effect=RuntimeError("database failure")):
            with self.assertRaises(RuntimeError):
                self.update()
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.title, "Original")
        self.assertEqual(get_epg_revision(), self.revision)


    def test_circular_properties_are_validation_errors(self):
        circular = {}
        circular["self"] = circular
        with self.assertRaises(ValidationError):
            self.update(
                {"custom_properties": {"new": MISSING}},
                {"custom_properties": {"new": circular}},
            )

    def test_out_of_range_ids_are_rejected_before_querying(self):
        with self.assertRaises(ValidationError):
            update_programmes([ProgrammeUpdate(2**100, {}, {})])

    def test_preview_with_no_revision_row_does_not_initialize_it(self):
        EPGRevision.objects.all().delete()
        self.update(preview=True)
        self.assertFalse(EPGRevision.objects.exists())


class ConcurrentProgrammeUpdateTests(TransactionTestCase):
    """Separate database connections exercise the row-lock/CAS boundary."""

    def test_competing_writers_only_apply_one_expected_value(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections, connection

        if not connection.features.has_select_for_update:
            self.skipTest("Requires database row locks")
        epg = EPGData.objects.create(name="Concurrent updates")
        programme = ProgramData.objects.create(
            epg=epg, title="Original", start_time=timezone.now(), end_time=timezone.now(),
        )
        get_epg_revision()
        start = Barrier(2)

        def write(title):
            close_old_connections()
            try:
                start.wait(timeout=10)
                return update_programmes([
                    ProgrammeUpdate(programme.pk, {"title": "Original"}, {"title": title})
                ])
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, title) for title in ("First", "Second")]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sum(len(result.changed) for result in results), 1)
        self.assertEqual(sum(len(result.conflicts) for result in results), 1)
        programme.refresh_from_db()
        self.assertIn(programme.title, ("First", "Second"))
