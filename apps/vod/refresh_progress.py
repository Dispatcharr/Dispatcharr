"""Coarse progress events for the existing VOD import pipeline."""

import logging
import time

logger = logging.getLogger(__name__)


class VODRefreshProgress:
    def __init__(self, account_id):
        self.account_id = account_id
        self.started_at = time.monotonic()

    def send(self, phase, progress, *, processed=None, total=None):
        from apps.m3u.tasks import send_m3u_update

        elapsed = max(time.monotonic() - self.started_at, 0)
        progress = max(0, min(int(progress), 99))
        remaining = elapsed * (100 - progress) / progress if progress > 10 else None
        try:
            send_m3u_update(
                self.account_id,
                "vod_refresh",
                progress,
                status="processing",
                message=f"VOD refresh: {phase}",
                phase=phase,
                elapsed_time=elapsed,
                time_remaining=remaining,
                items_processed=processed,
                items_total=total,
                provider_items_total=total,
            )
        except Exception:
            # An unavailable WebSocket must not interrupt a catalog import.
            logger.warning("Could not report VOD refresh progress", exc_info=True)
