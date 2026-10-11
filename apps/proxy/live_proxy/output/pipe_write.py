"""Encoder stdin writes shared by the output profile and fMP4 writers."""

import select

from ..constants import TS_PACKET_SIZE


def write_all(stdin, data, is_running, stop_check=None):
    """Write all bytes to an encoder's stdin, looping on partial writes.

    stop_check is polled when the pipe is full. A stop abandons the rest only at a
    TS packet boundary, so the encoder never gets a partial packet. Chunk starts are
    packet-aligned (BUFFER_CHUNK_SIZE is a multiple of 188), so offsets from the
    start of data are packet boundaries.
    """
    view = memoryview(data)
    offset = 0
    total = len(view)
    stop = False
    while offset < total:
        if not is_running():
            return
        if stop:
            if offset % TS_PACKET_SIZE == 0:
                return
            # Offer only up to the next packet boundary: the pipe takes pieces of
            # its own size, so an unaligned offset would otherwise run to the end.
            end = min(total, offset + TS_PACKET_SIZE - offset % TS_PACKET_SIZE)
        else:
            end = total
        n = stdin.write(view[offset:end])
        if n is None:
            # Pipe full (EAGAIN on non-blocking FD); yield cooperatively
            if not stop and stop_check is not None and stop_check():
                stop = True
                if offset % TS_PACKET_SIZE == 0:
                    return
                continue  # finish the packet now; the pipe may take it
            select.select([], [stdin], [], 1.0)
        elif n <= 0:
            raise OSError("stdin write returned no bytes")
        else:
            offset += n
