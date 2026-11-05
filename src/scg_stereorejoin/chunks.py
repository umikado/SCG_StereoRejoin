"""Builders and readers for BWF bext, cue, and LIST/INFO chunks.

The join path copies bext bytes unchanged. These builders exist so tests
and the demo generator can create realistic split-mono files.
"""

from __future__ import annotations

import struct

from scg_stereorejoin.wav import Chunk


class ChunkBuildError(ValueError):
    """A metadata helper was given a value that does not fit the BWF field."""


# EBU Tech 3285: 0x7FFF means "loudness value not used".
_LOUDNESS_UNUSED = 0x7FFF
_BEXT_FIXED = 602


def _fixed_text(text: str, size: int) -> bytes:
    raw = text.encode("ascii", errors="replace")[:size]
    return raw + b"\x00" * (size - len(raw))


def build_bext(
    *,
    description: str = "",
    originator: str = "",
    originator_reference: str = "",
    origination_date: str = "2026-11-05",
    origination_time: str = "12:00:00",
    time_reference: int = 0,
    version: int = 1,
    coding_history: bytes = b"",
    umid: bytes | None = None,
) -> bytes:
    """Build a version-1 bext payload, including the 180-byte reserved field.

    ``time_reference`` is the BWF sample offset (samples since midnight, or the
    timeline position the DAW stored). It is what Pro Tools, Cubase, and Nuendo
    read when they re-spot a file.
    """
    if len(origination_date) != 10:
        raise ChunkBuildError("origination date must be YYYY-MM-DD")
    if len(origination_time) != 8:
        raise ChunkBuildError("origination time must be HH:MM:SS")
    if time_reference < 0:
        raise ChunkBuildError("time reference cannot be negative")
    if umid is None:
        umid = bytes(64)
    if len(umid) != 64:
        raise ChunkBuildError("UMID field must be 64 bytes")
    low = time_reference & 0xFFFFFFFF
    high = (time_reference >> 32) & 0xFFFFFFFF
    head = b"".join(
        (
            _fixed_text(description, 256),
            _fixed_text(originator, 32),
            _fixed_text(originator_reference, 32),
            origination_date.encode("ascii"),
            origination_time.encode("ascii"),
            struct.pack("<II", low, high),
            struct.pack("<H", version),
            umid,
            struct.pack("<hhhhh", *([_LOUDNESS_UNUSED] * 5)),
            bytes(180),
        )
    )
    if len(head) != _BEXT_FIXED:
        raise ChunkBuildError(f"bext header is {len(head)} bytes, expected {_BEXT_FIXED}")
    history = coding_history
    if history and not history.endswith(b"\r\n"):
        history += b"\r\n"
    return head + history


def bext_time_reference(payload: bytes) -> int | None:
    """Return the 64-bit TimeReference, or None if the chunk is too short."""
    if len(payload) < 346:
        return None
    low, high = struct.unpack_from("<II", payload, 338)
    return low + (high << 32)


def bext_description(payload: bytes) -> str:
    if len(payload) < 256:
        return ""
    return payload[:256].split(b"\x00", 1)[0].decode("ascii", errors="replace")


def build_cue(sample_offset: int, *, name: int = 1) -> Chunk:
    """A single cue point. The chunk id is ``cue `` (with the trailing space)."""
    if sample_offset < 0:
        raise ChunkBuildError("cue offset cannot be negative")
    payload = struct.pack("<I", 1)
    payload += struct.pack("<II4sIII", name, sample_offset, b"data", 0, 0, sample_offset)
    return Chunk(b"cue ", payload)


def _info_item(tag: bytes, text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace") + b"\x00"
    pad = b"\x00" if len(raw) & 1 else b""
    return tag + struct.pack("<I", len(raw)) + raw + pad


def build_list_info(
    *,
    title: str | None = None,
    artist: str | None = None,
    comment: str | None = None,
    software: str | None = None,
) -> Chunk:
    """Build a LIST/INFO chunk. The payload starts with the ``INFO`` form id."""
    body = b"INFO"
    fields = (
        (b"INAM", title),
        (b"IART", artist),
        (b"ICMT", comment),
        (b"ISFT", software),
    )
    for tag, value in fields:
        if value:
            body += _info_item(tag, value)
    return Chunk(b"LIST", body)
