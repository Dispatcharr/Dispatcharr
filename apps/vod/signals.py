# apps/vod/signals.py

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Movie, Series, Episode
from core import events

import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────
# Movie Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=Movie)
def emit_movie_created_event(sender, instance, created, **kwargs):
    """Emit vod.movie_added when a new movie is added."""
    if created:
        events.emit("vod.movie_added", instance)


@receiver(post_delete, sender=Movie)
def emit_movie_deleted_event(sender, instance, **kwargs):
    """Emit vod.movie_removed when a movie is removed."""
    events.emit("vod.movie_removed", instance)


# ─────────────────────────────
# Series Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=Series)
def emit_series_created_event(sender, instance, created, **kwargs):
    """Emit vod.series_added when a new series is added."""
    if created:
        events.emit("vod.series_added", instance)


@receiver(post_delete, sender=Series)
def emit_series_deleted_event(sender, instance, **kwargs):
    """Emit vod.series_removed when a series is removed."""
    events.emit("vod.series_removed", instance)


# ─────────────────────────────
# Episode Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=Episode)
def emit_episode_created_event(sender, instance, created, **kwargs):
    """Emit vod.episode_added when a new episode is added."""
    if created:
        events.emit("vod.episode_added", instance)


@receiver(post_delete, sender=Episode)
def emit_episode_deleted_event(sender, instance, **kwargs):
    """Emit vod.episode_removed when an episode is removed."""
    events.emit("vod.episode_removed", instance)
