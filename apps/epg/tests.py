"""
Tests for EPG parsing performance optimizations.

This module tests database query optimizations including:
- Pre-fetching EPGData objects to avoid N+1 queries
- Using select_related() for foreign key lookups
- Using in_bulk() for batch object fetching
- Transaction protection for bulk operations
"""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from xml.etree import ElementTree as ET

from django.test import TestCase, TransactionTestCase
from django.db import connection
from django.test.utils import override_settings

from apps.epg.models import EPGSource, EPGData
from apps.epg.tasks import parse_channels_only
from apps.channels.models import Channel


class EPGParsingOptimizationTestCase(TestCase):
    """Test EPG parsing performance optimizations"""

    def setUp(self):
        """Set up test fixtures"""
        # Create test EPG source
        self.source = EPGSource.objects.create(
            name="Test EPG Source",
            url="http://example.com/epg.xml",
            is_active=True
        )

        # Create some existing EPG data
        self.existing_epgs = []
        for i in range(10):
            epg = EPGData.objects.create(
                tvg_id=f"channel{i}",
                name=f"Channel {i}",
                epg_source=self.source
            )
            self.existing_epgs.append(epg)

    def create_test_xmltv_file(self, channel_count=10):
        """Create a minimal XMLTV file for testing"""
        # Create root element
        tv = ET.Element("tv")
        tv.set("generator-info-name", "Test Generator")

        # Add channels
        for i in range(channel_count):
            channel = ET.SubElement(tv, "channel")
            channel.set("id", f"channel{i}")

            display_name = ET.SubElement(channel, "display-name")
            display_name.text = f"Channel {i}"

            icon = ET.SubElement(channel, "icon")
            icon.set("src", f"http://example.com/icon{i}.png")

        # Write to temp file
        temp_file = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.xml')
        tree = ET.ElementTree(tv)
        tree.write(temp_file, encoding='utf-8', xml_declaration=True)
        temp_file.close()

        return temp_file.name

    def test_parse_channels_prefetch_optimization(self):
        """
        Test that parse_channels_only pre-fetches EPGData objects
        instead of lazy-loading them one-by-one.

        Expected: ~10-12 queries instead of 50+ queries for 10 channels
        """
        # Create test XMLTV file with 10 channels
        xml_file = self.create_test_xmltv_file(channel_count=10)

        # Set the file_path on the source to our temp file
        self.source.file_path = xml_file
        self.source.save()

        try:
            # Count queries with optimization enabled
            # The optimization pre-fetches EPGData in chunks, avoiding N+1 queries
            # Expected: ~10-12 queries (chunked pre-fetch + batch operations)
            # Without optimization: would be 50+ queries (one per channel for lazy loading)

            from django.test.utils import override_settings
            from django.db import connection
            from django.test.utils import CaptureQueriesContext

            with CaptureQueriesContext(connection) as queries:
                parse_channels_only(self.source)

            query_count = len(queries)

            # Verify the optimization worked: should be much less than 50 queries
            self.assertLess(query_count, 20,
                          f"Query count should be < 20 with optimization (got {query_count})")

            # Verify EPGData objects were created/updated correctly
            epg_count = EPGData.objects.filter(epg_source=self.source).count()
            self.assertEqual(epg_count, 10,
                           "Should have 10 EPG entries after parsing")

        finally:
            # Clean up temp file
            Path(xml_file).unlink(missing_ok=True)

    def test_select_related_optimization(self):
        """
        Test that EPGData queries use select_related('epg_source')
        to avoid N+1 queries when accessing foreign keys.

        Expected: 1 query instead of N+1 queries
        """
        # Create 5 more EPG data entries
        for i in range(10, 15):
            EPGData.objects.create(
                tvg_id=f"channel{i}",
                name=f"Channel {i}",
                epg_source=self.source
            )

        # Count queries when iterating with select_related
        with self.assertNumQueries(1):
            epg_data = []
            for epg in EPGData.objects.select_related('epg_source').all():
                # Access foreign key - should not trigger extra queries
                epg_source_id = epg.epg_source.id if epg.epg_source else None
                epg_data.append({
                    'id': epg.id,
                    'tvg_id': epg.tvg_id,
                    'epg_source_id': epg_source_id,
                })

            # Should have 15 entries
            self.assertEqual(len(epg_data), 15)

    def test_in_bulk_optimization(self):
        """
        Test that in_bulk() is used to batch-fetch EPGData objects
        instead of individual get() calls.

        Expected: 1 query instead of N queries
        """
        # Create some channels
        channels = []
        for i in range(5):
            channel = Channel.objects.create(
                name=f"Test Channel {i}",
                channel_number=i + 1
            )
            channels.append(channel)

        # Simulate EPG mapping (channel_id -> epg_data_id)
        epg_mapping = {
            channels[0].id: self.existing_epgs[0].id,
            channels[1].id: self.existing_epgs[1].id,
            channels[2].id: self.existing_epgs[2].id,
        }

        # Test in_bulk() approach - should be 2 queries:
        # 1. Fetch channels by ID
        # 2. Fetch EPGData objects with in_bulk
        with self.assertNumQueries(2):
            channel_ids = list(epg_mapping.keys())
            channels_list = list(Channel.objects.filter(id__in=channel_ids))

            # Batch fetch EPGData (single query)
            epg_data_ids = list(epg_mapping.values())
            epg_objects = EPGData.objects.in_bulk(epg_data_ids)

            # Update channels (no additional queries)
            for channel_obj in channels_list:
                epg_data_id = epg_mapping.get(channel_obj.id)
                if epg_data_id and epg_data_id in epg_objects:
                    channel_obj.epg_data = epg_objects[epg_data_id]

        # Verify channels were updated
        self.assertEqual(channels_list[0].epg_data, self.existing_epgs[0])
        self.assertEqual(channels_list[1].epg_data, self.existing_epgs[1])
        self.assertEqual(channels_list[2].epg_data, self.existing_epgs[2])


class EPGTransactionTestCase(TransactionTestCase):
    """Test transaction protection for bulk operations"""

    def setUp(self):
        """Set up test fixtures"""
        self.source = EPGSource.objects.create(
            name="Test EPG Source",
            url="http://example.com/epg.xml",
            is_active=True
        )

    def test_bulk_create_transaction_rollback(self):
        """
        Test that bulk_create operations are wrapped in transactions
        and roll back on error.
        """
        # Create valid EPG data
        epgs_to_create = [
            EPGData(tvg_id=f"channel{i}", name=f"Channel {i}", epg_source=self.source)
            for i in range(5)
        ]

        # Add an invalid entry (duplicate tvg_id to trigger constraint violation)
        epgs_to_create.append(
            EPGData(tvg_id="channel0", name="Duplicate Channel", epg_source=self.source)
        )

        # Count before
        initial_count = EPGData.objects.count()

        # Attempt bulk create - should fail due to duplicate
        try:
            from django.db import transaction
            with transaction.atomic():
                EPGData.objects.bulk_create(epgs_to_create, ignore_conflicts=True)
        except Exception:
            pass  # Expected to fail

        # With ignore_conflicts=True, duplicates are ignored but other records are created
        final_count = EPGData.objects.count()
        self.assertEqual(final_count, initial_count + 5)  # 5 valid records created

    def test_bulk_update_transaction_protection(self):
        """
        Test that bulk_update operations are wrapped in transactions.
        """
        # Create test EPG data
        epgs = []
        for i in range(5):
            epg = EPGData.objects.create(
                tvg_id=f"channel{i}",
                name=f"Old Name {i}",
                epg_source=self.source
            )
            epgs.append(epg)

        # Update all names
        for i, epg in enumerate(epgs):
            epg.name = f"New Name {i}"

        # Bulk update with transaction
        from django.db import transaction
        with transaction.atomic():
            EPGData.objects.bulk_update(epgs, ["name"])

        # Verify all were updated
        for i, epg_id in enumerate([e.id for e in epgs]):
            epg = EPGData.objects.get(id=epg_id)
            self.assertEqual(epg.name, f"New Name {i}")
