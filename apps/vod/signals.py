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
    """Emit vod.movie_created when a new movie is created."""
    if created:
        events.emit("vod.movie_created", instance)


@receiver(post_delete, sender=Movie)
def emit_movie_deleted_event(sender, instance, **kwargs):
    """Emit vod.movie_deleted when a movie is deleted."""
    events.emit("vod.movie_deleted", instance)


# ─────────────────────────────
# Series Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=Series)
def emit_series_created_event(sender, instance, created, **kwargs):
    """Emit vod.series_created when a new series is created."""
    if created:
        events.emit("vod.series_created", instance)


@receiver(post_delete, sender=Series)
def emit_series_deleted_event(sender, instance, **kwargs):
    """Emit vod.series_deleted when a series is deleted."""
    events.emit("vod.series_deleted", instance)


# ─────────────────────────────
# Episode Plugin Event Emissions
# ─────────────────────────────
@receiver(post_save, sender=Episode)
def emit_episode_created_event(sender, instance, created, **kwargs):
    """Emit vod.episode_created when a new episode is created."""
    if created:
        events.emit("vod.episode_created", instance)


@receiver(post_delete, sender=Episode)
def emit_episode_deleted_event(sender, instance, **kwargs):
    """Emit vod.episode_deleted when an episode is deleted."""
    events.emit("vod.episode_deleted", instance)
