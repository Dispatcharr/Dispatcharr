"""Cached UUID recovery must not guess across account-scoped provider IDs."""

import uuid

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.views import _get_content_and_relation
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    Movie,
    Series,
)


class StreamIdFallbackTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(name="Synthetic provider")
        self.other = M3UAccount.objects.create(name="Other synthetic provider")

    def source(self, kind, account, stream_id):
        if kind == "movie":
            content = Movie.objects.create(name=f"Movie {account.pk}")
            source = M3UMovieRelation.objects.create(
                movie=content,
                m3u_account=account,
                stream_id=stream_id,
            )
        else:
            series = Series.objects.create(name=f"Series {account.pk}")
            content = Episode.objects.create(series=series, name="Episode")
            source = M3UEpisodeRelation.objects.create(
                episode=content,
                m3u_account=account,
                stream_id=stream_id,
            )
        return content, source

    def test_uuid_hit_keeps_the_requested_content(self):
        for kind in ("movie", "episode"):
            content, source = self.source(kind, self.account, kind)
            found, selected, candidates = _get_content_and_relation(
                kind,
                content.uuid,
                preferred_stream_id=kind,
            )
            self.assertEqual(found.pk, content.pk)
            self.assertEqual(selected.pk, source.pk)
            self.assertEqual([item.pk for item in candidates], [source.pk])

    def test_missing_uuid_recovers_an_unambiguous_source(self):
        for kind in ("movie", "episode"):
            content, source = self.source(kind, self.account, kind)
            with self.assertLogs("apps.proxy.vod_proxy.views", level="WARNING"):
                found, selected, _ = _get_content_and_relation(
                    kind,
                    uuid.uuid4(),
                    preferred_stream_id=kind,
                )
            self.assertEqual(found.pk, content.pk)
            self.assertEqual(selected.pk, source.pk)

    def test_colliding_provider_ids_require_an_account(self):
        for kind in ("movie", "episode"):
            self.source(kind, self.account, "same-id")
            content, source = self.source(kind, self.other, "same-id")
            self.assertEqual(
                _get_content_and_relation(
                    kind,
                    uuid.uuid4(),
                    preferred_stream_id="same-id",
                ),
                (None, None, []),
            )
            found, selected, _ = _get_content_and_relation(
                kind,
                uuid.uuid4(),
                self.other.pk,
                "same-id",
            )
            self.assertEqual(found.pk, content.pk)
            self.assertEqual(selected.pk, source.pk)

    def test_missing_uuid_without_a_source_is_not_guessed(self):
        for kind in ("movie", "episode"):
            self.source(kind, self.account, kind)
            for stream_id in (None, "not-present"):
                self.assertEqual(
                    _get_content_and_relation(
                        kind,
                        uuid.uuid4(),
                        preferred_stream_id=stream_id,
                    ),
                    (None, None, []),
                )

    def test_inactive_provider_is_not_recovered(self):
        _, source = self.source("movie", self.account, "inactive")
        self.account.is_active = False
        self.account.save(update_fields=["is_active"])
        self.assertEqual(
            _get_content_and_relation(
                "movie",
                uuid.uuid4(),
                preferred_stream_id=source.stream_id,
            ),
            (None, None, []),
        )
