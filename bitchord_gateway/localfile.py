"""Serving a file that lives on this server with HTTP Range support.

The Mornye backend downloads a track into a cache directory; `/audio/{token}`
then has to behave like the upstream proxy does for remote sources: answer
`206 Partial Content` so BitChord can seek, and `Accept-Ranges: bytes` so it
knows it may.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator

CHUNK = 64 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")

CONTENT_TYPES = {
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
}


class RangeNotSatisfiable(ValueError):
    pass


def content_type(path: str) -> str:
    return CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "audio/flac")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return the inclusive (start, end) a Range header asks for.

    None means "send everything" (no header, or one we do not understand: a
    server may ignore a Range it cannot parse). Multi-range requests are not
    supported and are treated the same way. RangeNotSatisfiable is raised for a
    well-formed range that lies outside the file.
    """
    if not header:
        return None
    m = _RANGE.match(header.strip())
    if not m or (not m[1] and not m[2]):
        return None
    if size == 0:
        raise RangeNotSatisfiable("empty file")
    if not m[1]:  # suffix range: the last N bytes
        n = int(m[2])
        if n == 0:
            raise RangeNotSatisfiable("zero-length suffix")
        return max(size - n, 0), size - 1
    start = int(m[1])
    end = min(int(m[2]), size - 1) if m[2] else size - 1
    if start >= size or end < start:
        raise RangeNotSatisfiable(f"{start}-{end} outside {size}")
    return start, end


async def iter_file(path: str, start: int, end: int) -> AsyncIterator[bytes]:
    """Yield bytes start..end (inclusive) without blocking the event loop."""
    loop = asyncio.get_running_loop()
    remaining = end - start + 1
    fh = await loop.run_in_executor(None, open, path, "rb")
    try:
        await loop.run_in_executor(None, fh.seek, start)
        while remaining > 0:
            chunk = await loop.run_in_executor(None, fh.read, min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        fh.close()
