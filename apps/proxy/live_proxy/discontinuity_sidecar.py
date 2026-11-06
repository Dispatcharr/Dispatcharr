"""Redis sidecar of chunk indexes where a new buffer era begins.

Shared by the input ``StreamBuffer`` and the output ``OutputStreamBuffer``.
"""

from .utils import get_logger

logger = get_logger()

# Drop marks more than this many chunk indexes behind the newest. The key's TTL is separate.
_SIDECAR_WINDOW_CHUNKS = 10000


class DiscontinuitySidecarMixin:
    """The host provides ``redis_client``, ``discontinuities_key`` (empty disables this) and ``chunk_ttl``."""

    def _discontinuity_label(self) -> str:
        return f"channel {self.channel_id}"

    def _record_discontinuity_unlocked(self, chunk_index):
        if not self.redis_client or not self.discontinuities_key:
            return
        try:
            pipe = self.redis_client.pipeline(transaction=False)
            pipe.zadd(self.discontinuities_key, {str(chunk_index): float(chunk_index)})
            pipe.zremrangebyscore(
                self.discontinuities_key,
                '-inf',
                float(chunk_index) - _SIDECAR_WINDOW_CHUNKS,
            )
            pipe.expire(self.discontinuities_key, self.chunk_ttl)
            pipe.execute()
        except Exception as e:
            logger.error(
                f"Error recording discontinuity index {chunk_index} for "
                f"{self._discontinuity_label()}: {e}"
            )

    def discontinuities_in_range(self, start_index_exclusive, end_index_inclusive):
        """Sorted indexes D with start < D <= end. D is the first chunk of a new era."""
        if (
            not self.redis_client
            or not self.discontinuities_key
            or end_index_inclusive <= start_index_exclusive
        ):
            return []
        try:
            members = self.redis_client.zrangebyscore(
                self.discontinuities_key,
                float(start_index_exclusive) + 1e-9,
                float(end_index_inclusive),
            )
            out = []
            for m in members or []:
                try:
                    out.append(int(m))
                except (TypeError, ValueError):
                    continue
            return out
        except Exception as e:
            logger.debug(
                f"Error reading discontinuities for {self._discontinuity_label()}: {e}"
            )
            return []
