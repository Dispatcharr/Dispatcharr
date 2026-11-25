"""Find PAT and PMT packets without walking the media packets around them.

The two PID bytes of every packet are matched together, and the result is
cached per input chunk so each output of a channel does not scan it again.
"""

import functools
import threading
from collections import OrderedDict

from apps.proxy.ts_psi import TS_PACKET_SIZE

_SYNC_BYTE = 0x47
_PUSI_BIT = 0x40
_PAT_PID = 0


@functools.lru_cache(maxsize=64)
def _high_byte_table(pid_high, require_pusi):
    return bytes(
        1 if (b & 0x1F) == pid_high and (not require_pusi or b & _PUSI_BIT) else 0
        for b in range(256)
    )


@functools.lru_cache(maxsize=256)
def _low_byte_table(pid_low):
    return bytes(1 if b == pid_low else 0 for b in range(256))


def _packet_offsets(high, low, pid, require_pusi):
    """Offsets of packets with this PID. The two header-byte masks are ANDed as one integer."""
    high_hits = int.from_bytes(
        high.translate(_high_byte_table(pid >> 8, require_pusi)), "little"
    )
    low_hits = int.from_bytes(low.translate(_low_byte_table(pid & 0xFF)), "little")
    hits = (high_hits & low_hits).to_bytes(len(high), "little")
    offsets = []
    index = hits.find(1)
    while index >= 0:
        offsets.append(index * TS_PACKET_SIZE)
        index = hits.find(1, index + 1)
    return offsets


def locate_psi_packets(data, pmt_pid):
    """``((offset, is_pat), ...)`` in order, or None when ``data`` is not packet-aligned.

    ``is_pat`` is a PAT packet (PID 0 with the payload-start flag). The others
    are packets on ``pmt_pid``. With ``pmt_pid`` None only PATs are reported.
    None means the caller has to walk packets: strided reads would land mid-packet.
    """
    count, remainder = divmod(len(data), TS_PACKET_SIZE)
    if remainder or not count:
        return None
    end = count * TS_PACKET_SIZE
    if data[0:end:TS_PACKET_SIZE].count(_SYNC_BYTE) != count:
        return None

    high = data[1:end:TS_PACKET_SIZE]
    low = data[2:end:TS_PACKET_SIZE]
    pats = _packet_offsets(high, low, _PAT_PID, True)
    if pmt_pid is None or pmt_pid == _PAT_PID:
        return tuple((offset, True) for offset in pats)
    pmts = _packet_offsets(high, low, pmt_pid, False)
    return tuple(sorted(
        [(offset, True) for offset in pats] + [(offset, False) for offset in pmts]
    ))


class PsiScanCache:
    """Memo of locate results for one channel.

    A chunk's bytes do not change once written, so a result stays valid.
    The key includes the chunk length and PMT PID, so a reader that has
    learned a different PMT PID does not reuse another's answer.
    """

    def __init__(self, capacity=128):
        self._capacity = capacity
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def locate(self, chunk_index, data, pmt_pid):
        key = (chunk_index, len(data), pmt_pid)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        # Outside the lock. Two readers of one chunk both compute the same answer.
        located = locate_psi_packets(data, pmt_pid)
        with self._lock:
            self._items[key] = located
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)
        return located
