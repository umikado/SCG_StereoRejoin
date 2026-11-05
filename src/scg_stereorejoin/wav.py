"""RIFF / RF64 / BW64 WAVE reader and writer.

Audio is raw PCM bytes. Nothing in this module resamples, dithers, or
changes bit depth. Channel count changes only in the ``fmt `` header of a
file this module writes.

RF64 and BW64 (EBU Tech 3306, ITU-R BS.2088) are used when a classic RIFF
size field cannot hold the file. The ``ds64`` chunk then stores the real
sizes. Small files stay RIFF/WAVE so older software can open them.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

RIFF = b"RIFF"
RF64 = b"RF64"
BW64 = b"BW64"
RIFX = b"RIFX"
WAVE = b"WAVE"
UINT32_MAX = 0xFFFFFFFF

FMT_PCM = 0x0001
FMT_FLOAT = 0x0003
FMT_EXTENSIBLE = 0xFFFE

# KSDATAFORMAT_SUBTYPE GUIDs, little-endian on disk.
SUBTYPE_PCM = bytes.fromhex("0100000000001000800000aa00389b71")
SUBTYPE_FLOAT = bytes.fromhex("0300000000001000800000aa00389b71")

SPEAKER_FRONT_LEFT = 0x1
SPEAKER_FRONT_RIGHT = 0x2
SPEAKER_STEREO = SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT

_SUPPORTED_WIDTHS = {
    (FMT_PCM, 16),
    (FMT_PCM, 24),
    (FMT_PCM, 32),
    (FMT_FLOAT, 32),
    (FMT_FLOAT, 64),
}


class WavError(Exception):
    """The file is not a WAVE we can read, or a value cannot be written."""


@dataclass
class Chunk:
    ident: bytes
    data: bytes

    def __post_init__(self) -> None:
        if len(self.ident) != 4:
            raise WavError(f"chunk id must be 4 bytes, got {self.ident!r}")


@dataclass
class Fmt:
    format_tag: int
    channels: int
    sample_rate: int
    byte_rate: int
    block_align: int
    bits_per_sample: int
    valid_bits: int
    channel_mask: int | None
    subformat: bytes | None
    extra: bytes
    raw: bytes

    @property
    def sample_width(self) -> int:
        return self.bits_per_sample // 8

    @property
    def is_extensible(self) -> bool:
        return self.format_tag == FMT_EXTENSIBLE

    @property
    def is_float(self) -> bool:
        if self.format_tag == FMT_FLOAT:
            return True
        return self.is_extensible and self.subformat == SUBTYPE_FLOAT

    @property
    def is_pcm(self) -> bool:
        if self.format_tag == FMT_PCM:
            return True
        return self.is_extensible and self.subformat == SUBTYPE_PCM

    @property
    def encoding_name(self) -> str:
        kind = "float" if self.is_float else "PCM" if self.is_pcm else f"tag-{self.format_tag}"
        label = f"{self.bits_per_sample}-bit {kind}"
        if self.is_extensible:
            label = f"extensible {label}"
        if self.valid_bits != self.bits_per_sample:
            label += f" ({self.valid_bits} valid)"
        return label

    def as_stereo(self) -> Fmt:
        width = self.sample_width
        channels = 2
        block_align = width * channels
        mask = SPEAKER_STEREO if self.is_extensible else self.channel_mask
        return Fmt(
            format_tag=self.format_tag,
            channels=channels,
            sample_rate=self.sample_rate,
            byte_rate=self.sample_rate * block_align,
            block_align=block_align,
            bits_per_sample=self.bits_per_sample,
            valid_bits=self.valid_bits,
            channel_mask=mask,
            subformat=self.subformat,
            extra=self.extra,
            raw=b"",
        )


@dataclass
class Ds64:
    riff_size: int
    data_size: int
    sample_count: int
    table: list[tuple[bytes, int]]


@dataclass
class WavInfo:
    path: Path
    container: bytes
    fmt: Fmt
    chunks: list[Chunk]
    data_offset: int
    data_size: int
    frames: int
    data_remainder: int
    ds64: Ds64 | None

    def chunk(self, ident: bytes) -> Chunk | None:
        for item in self.chunks:
            if item.ident == ident:
                return item
        return None


@dataclass
class WriteResult:
    container: bytes
    frames: int
    data_size: int


def make_fmt(
    encoding: str,
    sample_rate: int,
    channels: int = 1,
    *,
    valid_bits: int | None = None,
    channel_mask: int | None = None,
) -> Fmt:
    """Build a ``Fmt`` for the encodings this tool supports.

    ``encoding`` is one of ``pcm16``, ``pcm24``, ``pcm32``, ``float32``,
    ``float64``, or the same names prefixed with ``ext-`` for WAVE_FORMAT_EXTENSIBLE.
    """
    extensible = encoding.startswith("ext-")
    base = encoding[4:] if extensible else encoding
    table = {
        "pcm16": (FMT_PCM, 16, SUBTYPE_PCM),
        "pcm24": (FMT_PCM, 24, SUBTYPE_PCM),
        "pcm32": (FMT_PCM, 32, SUBTYPE_PCM),
        "float32": (FMT_FLOAT, 32, SUBTYPE_FLOAT),
        "float64": (FMT_FLOAT, 64, SUBTYPE_FLOAT),
    }
    if base not in table:
        raise WavError(f"unsupported encoding {encoding!r}")
    tag, bits, subtype = table[base]
    if extensible:
        tag = FMT_EXTENSIBLE
        subformat: bytes | None = subtype
    else:
        subformat = None
    width = bits // 8
    if channel_mask is None and extensible:
        if channels == 1:
            channel_mask = SPEAKER_FRONT_LEFT
        elif channels == 2:
            channel_mask = SPEAKER_STEREO
        else:
            channel_mask = 0
    return Fmt(
        format_tag=tag,
        channels=channels,
        sample_rate=sample_rate,
        byte_rate=sample_rate * width * channels,
        block_align=width * channels,
        bits_per_sample=bits,
        valid_bits=bits if valid_bits is None else valid_bits,
        channel_mask=channel_mask,
        subformat=subformat,
        extra=b"",
        raw=b"",
    )


def parse_fmt(data: bytes) -> Fmt:
    if len(data) < 16:
        raise WavError(f"fmt chunk is too small ({len(data)} bytes)")
    format_tag, channels, sample_rate, byte_rate, block_align, bits = struct.unpack_from(
        "<HHIIHH", data, 0
    )
    valid_bits = bits
    channel_mask: int | None = None
    subformat: bytes | None = None
    extra = b""
    if format_tag == FMT_EXTENSIBLE:
        if len(data) < 40:
            raise WavError("extensible fmt chunk is shorter than 40 bytes")
        cb_size, valid_bits, channel_mask = struct.unpack_from("<HHI", data, 16)
        subformat = data[24:40]
        extra = data[40 : 18 + cb_size] if cb_size > 22 else data[40:]
        if subformat not in (SUBTYPE_PCM, SUBTYPE_FLOAT):
            raise WavError(
                "unsupported extensible subformat " + subformat.hex()
            )
    elif len(data) >= 18:
        cb_size = struct.unpack_from("<H", data, 16)[0]
        extra = data[18 : 18 + cb_size]
    _check_encoding(format_tag, bits, subformat)
    if channels <= 0 or sample_rate <= 0 or block_align <= 0:
        raise WavError(
            f"fmt chunk has channels={channels}, rate={sample_rate}, block_align={block_align}"
        )
    if bits % 8 != 0:
        raise WavError(f"only whole-byte sample widths are supported (got {bits} bits)")
    return Fmt(
        format_tag=format_tag,
        channels=channels,
        sample_rate=sample_rate,
        byte_rate=byte_rate,
        block_align=block_align,
        bits_per_sample=bits,
        valid_bits=valid_bits,
        channel_mask=channel_mask,
        subformat=subformat,
        extra=extra,
        raw=data,
    )


def _check_encoding(format_tag: int, bits: int, subformat: bytes | None) -> None:
    if format_tag == FMT_EXTENSIBLE:
        if subformat == SUBTYPE_FLOAT:
            base = FMT_FLOAT
        elif subformat == SUBTYPE_PCM:
            base = FMT_PCM
        else:
            raise WavError("unsupported extensible subformat")
    else:
        base = format_tag
    if (base, bits) not in _SUPPORTED_WIDTHS:
        kind = "float" if base == FMT_FLOAT else "PCM" if base == FMT_PCM else hex(base)
        raise WavError(f"unsupported sample format {bits}-bit {kind}")


def build_fmt(fmt: Fmt) -> bytes:
    if fmt.byte_rate > UINT32_MAX or fmt.sample_rate > UINT32_MAX:
        raise WavError("sample rate or byte rate does not fit in the WAV fmt chunk")
    if not 0 < fmt.channels < 65536:
        raise WavError(f"channel count {fmt.channels} does not fit in fmt")
    basic = struct.pack(
        "<HHIIHH",
        fmt.format_tag,
        fmt.channels,
        fmt.sample_rate,
        fmt.byte_rate,
        fmt.block_align,
        fmt.bits_per_sample,
    )
    if fmt.format_tag == FMT_EXTENSIBLE:
        if fmt.subformat is None or len(fmt.subformat) != 16:
            raise WavError("extensible fmt requires a 16-byte subformat GUID")
        mask = SPEAKER_STEREO if fmt.channels == 2 else (fmt.channel_mask or 0)
        cb_size = 22 + len(fmt.extra)
        return basic + struct.pack("<HHI", cb_size, fmt.valid_bits, mask) + fmt.subformat + fmt.extra
    if fmt.extra or fmt.format_tag == FMT_FLOAT:
        return basic + struct.pack("<H", len(fmt.extra)) + fmt.extra
    return basic


def build_fact(sample_count: int) -> bytes:
    if sample_count < 0:
        raise WavError("sample count cannot be negative")
    stored = sample_count if sample_count <= UINT32_MAX else UINT32_MAX
    return struct.pack("<I", stored)


def chunk_disk_size(payload_len: int) -> int:
    return 8 + payload_len + (payload_len & 1)


def planned_file_size(chunks: list[Chunk], data_size: int, *, container_64: bool) -> int:
    total = 12
    if container_64:
        total += chunk_disk_size(28)
    for chunk in chunks:
        total += chunk_disk_size(len(chunk.data))
    total += chunk_disk_size(data_size)
    return total


def container_for(
    chunks: list[Chunk],
    data_size: int,
    *,
    large_container: bytes = RF64,
    force: bytes | None = None,
) -> bytes:
    """Choose RIFF, or RF64/BW64 when the file cannot fit in a 32-bit RIFF size."""
    if large_container not in (RF64, BW64):
        raise WavError("files over 4 GB must use RF64 or BW64")
    if data_size < 0:
        raise WavError("data size cannot be negative")
    if force is not None:
        if force not in (RIFF, RF64, BW64):
            raise WavError(f"unknown container {force!r}")
        if force == RIFF and not _fits_riff(chunks, data_size):
            raise WavError("file exceeds 4 GB and does not fit in a classic RIFF WAV")
        return force
    if _fits_riff(chunks, data_size):
        return RIFF
    return large_container


def _fits_riff(chunks: list[Chunk], data_size: int) -> bool:
    if data_size > UINT32_MAX:
        return False
    for chunk in chunks:
        if len(chunk.data) > UINT32_MAX:
            return False
    size = planned_file_size(chunks, data_size, container_64=False)
    return size - 8 <= UINT32_MAX


def container_label(container: bytes) -> str:
    if container == RIFF:
        return "WAV"
    return container.decode("ascii", errors="replace")


def interleave(left: bytes, right: bytes, width: int) -> bytes:
    """Interleave two equal-length mono streams.

    For width 2 and samples ``AB CD`` / ``EF GH`` the result is ``AB EF CD GH``.
    The copy is strided, so it stays in C rather than looping once per frame.
    """
    if width <= 0:
        raise WavError(f"invalid sample width {width}")
    if len(left) != len(right):
        raise WavError("interleave inputs must be the same length")
    if len(left) % width != 0:
        raise WavError("audio length is not a whole number of samples")
    frames = len(left) // width
    if frames == 0:
        return b""
    out = bytearray(frames * width * 2)
    step = width * 2
    for index in range(width):
        out[index::step] = left[index::width]
        out[width + index :: step] = right[index::width]
    return bytes(out)


def read_wav(path: Path | str) -> WavInfo:
    path = Path(path)
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        raise WavError(f"{path}: {exc.strerror}") from exc
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            raise WavError(f"{path}: file is too small to be a WAV")
        ident, size, form = struct.unpack("<4sI4s", header)
        if ident == RIFX:
            raise WavError(f"{path}: big-endian RIFX WAVE is not supported")
        if ident not in (RIFF, RF64, BW64) or form != WAVE:
            raise WavError(
                f"{path}: not a RIFF, RF64, or BW64 WAVE file (got {ident!r} / {form!r})"
            )
        limit = file_size
        if ident == RIFF and size != UINT32_MAX:
            limit = min(file_size, 8 + size)
        ds64: Ds64 | None = None
        chunks: list[Chunk] = []
        data_offset: int | None = None
        data_size: int | None = None
        first = True
        while handle.tell() + 8 <= limit:
            chunk_header = handle.read(8)
            if len(chunk_header) < 8:
                break
            cid, csize = struct.unpack("<4sI", chunk_header)
            if first and ident in (RF64, BW64) and cid != b"ds64":
                raise WavError(f"{path}: {ident.decode()} file must start with a ds64 chunk")
            first = False
            if cid == b"ds64":
                blob = _read_exact(handle, csize, path, cid)
                ds64 = _parse_ds64(blob, path)
                _consume_pad(handle, csize, limit)
                if ds64.riff_size:
                    limit = min(file_size, 8 + ds64.riff_size)
                continue
            actual = csize
            if csize == UINT32_MAX:
                actual = _resolve_sentinel(cid, ds64, path)
            if cid == b"data":
                data_offset = handle.tell()
                data_size = actual
                _skip(handle, actual, path, file_size)
                _consume_pad(handle, actual, limit)
                continue
            blob = _read_exact(handle, actual, path, cid)
            chunks.append(Chunk(cid, blob))
            _consume_pad(handle, actual, limit)
    if data_offset is None or data_size is None:
        raise WavError(f"{path}: WAVE file has no data chunk")
    fmt_chunk = next((item for item in chunks if item.ident == b"fmt "), None)
    if fmt_chunk is None:
        raise WavError(f"{path}: WAVE file has no fmt chunk")
    try:
        fmt = parse_fmt(fmt_chunk.data)
    except WavError as exc:
        raise WavError(f"{path}: {exc}") from exc
    remainder = data_size % fmt.block_align
    frames = data_size // fmt.block_align
    return WavInfo(
        path=path,
        container=ident,
        fmt=fmt,
        chunks=chunks,
        data_offset=data_offset,
        data_size=data_size,
        frames=frames,
        data_remainder=remainder,
        ds64=ds64,
    )


def read_audio(path: Path | str, info: WavInfo) -> bytes:
    path = Path(path)
    with path.open("rb") as handle:
        handle.seek(info.data_offset)
        blob = handle.read(info.data_size)
    if len(blob) != info.data_size:
        raise WavError(f"{path}: audio data is truncated")
    return blob


def write_wav(
    path: Path | str,
    *,
    fmt: Fmt,
    audio: bytes,
    chunks: list[Chunk],
    large_container: bytes = RF64,
    force_container: bytes | None = None,
) -> WriteResult:
    """Write ``audio`` as the data chunk. ``chunks`` is the chunk list before data.

    ``chunks`` must already contain ``fmt `` if the caller wants one there.
    This helper does not invent a ``fmt `` chunk; ``build_wav_chunks`` does.
    """
    path = Path(path)
    if fmt.block_align <= 0 or len(audio) % fmt.block_align != 0:
        raise WavError("audio length is not a whole number of frames")
    frames = len(audio) // fmt.block_align
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        container = _write_header(
            handle,
            chunks,
            data_size=len(audio),
            sample_count=frames,
            large_container=large_container,
            force_container=force_container,
        )
        handle.write(audio)
        if len(audio) & 1:
            handle.write(b"\x00")
    return WriteResult(container=container, frames=frames, data_size=len(audio))


def build_wav_chunks(
    fmt: Fmt,
    *,
    before_fmt: list[Chunk] | None = None,
    after_fmt: list[Chunk] | None = None,
    frames: int | None = None,
    include_fact: bool | None = None,
) -> list[Chunk]:
    """Chunk order used for files we create: bext, fmt, fact, then the rest."""
    chunks: list[Chunk] = []
    if before_fmt:
        chunks.extend(before_fmt)
    chunks.append(Chunk(b"fmt ", build_fmt(fmt)))
    want_fact = fmt.is_float if include_fact is None else include_fact
    if want_fact:
        if frames is None:
            raise WavError("a fact chunk needs a frame count")
        chunks.append(Chunk(b"fact", build_fact(frames)))
    if after_fmt:
        chunks.extend(after_fmt)
    return chunks


def write_interleaved_wav(
    path: Path | str,
    *,
    chunks: list[Chunk],
    sample_width: int,
    left_path: Path,
    left_offset: int,
    left_frames: int,
    right_path: Path,
    right_offset: int,
    right_frames: int,
    pad: bool = False,
    large_container: bytes = RF64,
    force_container: bytes | None = None,
    chunk_frames: int = 65536,
) -> WriteResult:
    """Stream two mono files into one interleaved stereo data chunk."""
    if chunk_frames < 1:
        raise WavError("chunk_frames must be positive")
    if sample_width <= 0:
        raise WavError(f"invalid sample width {sample_width}")
    if left_frames < 0 or right_frames < 0:
        raise WavError("frame count cannot be negative")
    if left_frames != right_frames and not pad:
        raise WavError(
            f"frame counts differ ({left_frames} vs {right_frames}) and pad is off"
        )
    frames = max(left_frames, right_frames)
    data_size = frames * sample_width * 2
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        container = _write_header(
            handle,
            chunks,
            data_size=data_size,
            sample_count=frames,
            large_container=large_container,
            force_container=force_container,
        )
        _stream_interleave(
            handle,
            left_path=left_path,
            left_offset=left_offset,
            left_frames=left_frames,
            right_path=right_path,
            right_offset=right_offset,
            right_frames=right_frames,
            width=sample_width,
            chunk_frames=chunk_frames,
        )
        if data_size & 1:
            handle.write(b"\x00")
    return WriteResult(container=container, frames=frames, data_size=data_size)


def _write_header(
    handle,
    chunks: list[Chunk],
    *,
    data_size: int,
    sample_count: int,
    large_container: bytes,
    force_container: bytes | None,
) -> bytes:
    container = container_for(
        chunks,
        data_size,
        large_container=large_container,
        force=force_container,
    )
    file_size = planned_file_size(chunks, data_size, container_64=container != RIFF)
    riff_size = file_size - 8
    if container == RIFF:
        handle.write(struct.pack("<4sI4s", RIFF, riff_size, WAVE))
    else:
        handle.write(struct.pack("<4sI4s", container, UINT32_MAX, WAVE))
        ds64 = struct.pack(
            "<IIIIIII",
            riff_size & UINT32_MAX,
            (riff_size >> 32) & UINT32_MAX,
            data_size & UINT32_MAX,
            (data_size >> 32) & UINT32_MAX,
            sample_count & UINT32_MAX,
            (sample_count >> 32) & UINT32_MAX,
            0,
        )
        _write_chunk(handle, b"ds64", ds64)
    for chunk in chunks:
        _write_chunk(handle, chunk.ident, chunk.data)
    data_field = UINT32_MAX if container != RIFF else data_size
    handle.write(struct.pack("<4sI", b"data", data_field))
    return container


def _write_chunk(handle, ident: bytes, data: bytes) -> None:
    if len(ident) != 4:
        raise WavError(f"bad chunk id {ident!r}")
    if len(data) > UINT32_MAX:
        raise WavError(f"chunk {ident!r} is larger than 4 GB")
    handle.write(struct.pack("<4sI", ident, len(data)))
    handle.write(data)
    if len(data) & 1:
        handle.write(b"\x00")


def _stream_interleave(
    handle,
    *,
    left_path: Path,
    left_offset: int,
    left_frames: int,
    right_path: Path,
    right_offset: int,
    right_frames: int,
    width: int,
    chunk_frames: int,
) -> None:
    frames = max(left_frames, right_frames)
    produced = 0
    left_left = left_frames
    right_left = right_frames
    with left_path.open("rb") as left_handle, right_path.open("rb") as right_handle:
        left_handle.seek(left_offset)
        right_handle.seek(right_offset)
        while produced < frames:
            count = min(chunk_frames, frames - produced)
            take_left = min(count, left_left)
            take_right = min(count, right_left)
            left_bytes = _read_frames(left_handle, take_left, width, left_path)
            right_bytes = _read_frames(right_handle, take_right, width, right_path)
            if take_left < count:
                left_bytes += bytes((count - take_left) * width)
            if take_right < count:
                right_bytes += bytes((count - take_right) * width)
            handle.write(interleave(left_bytes, right_bytes, width))
            left_left -= take_left
            right_left -= take_right
            produced += count


def _read_frames(handle, frames: int, width: int, path: Path) -> bytes:
    if frames == 0:
        return b""
    blob = handle.read(frames * width)
    if len(blob) != frames * width:
        raise WavError(f"{path}: audio data ended early")
    return blob


def _parse_ds64(blob: bytes, path: Path) -> Ds64:
    if len(blob) < 28:
        raise WavError(f"{path}: ds64 chunk is too small")
    low_riff, high_riff, low_data, high_data, low_samples, high_samples, table_len = struct.unpack_from(
        "<IIIIIII", blob, 0
    )
    table: list[tuple[bytes, int]] = []
    offset = 28
    for _ in range(table_len):
        if offset + 12 > len(blob):
            raise WavError(f"{path}: ds64 table is truncated")
        cid, low, high = struct.unpack_from("<4sII", blob, offset)
        table.append((cid, low + (high << 32)))
        offset += 12
    return Ds64(
        riff_size=low_riff + (high_riff << 32),
        data_size=low_data + (high_data << 32),
        sample_count=low_samples + (high_samples << 32),
        table=table,
    )


def _resolve_sentinel(cid: bytes, ds64: Ds64 | None, path: Path) -> int:
    if ds64 is None:
        raise WavError(f"{path}: chunk {cid!r} has size 0xFFFFFFFF but no ds64 chunk was found")
    if cid == b"data":
        return ds64.data_size
    for ident, size in ds64.table:
        if ident == cid:
            return size
    raise WavError(f"{path}: chunk {cid!r} has size 0xFFFFFFFF but ds64 has no size for it")


def _read_exact(handle, size: int, path: Path, cid: bytes) -> bytes:
    blob = handle.read(size)
    if len(blob) != size:
        raise WavError(f"{path}: chunk {cid!r} is truncated")
    return blob


def _skip(handle, size: int, path: Path, file_size: int) -> None:
    start = handle.tell()
    if size < 0 or start + size > file_size:
        raise WavError(f"{path}: audio data is truncated")
    handle.seek(start + size, os.SEEK_SET)


def _consume_pad(handle, size: int, limit: int) -> None:
    if size & 1 and handle.tell() < limit:
        handle.seek(1, os.SEEK_CUR)
