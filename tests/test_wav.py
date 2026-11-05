import struct
from pathlib import Path

import pytest

from scg_stereorejoin.chunks import bext_time_reference, build_bext
from scg_stereorejoin.wav import (
    BW64,
    RF64,
    RIFF,
    UINT32_MAX,
    Chunk,
    WavError,
    build_fmt,
    build_wav_chunks,
    container_for,
    interleave,
    make_fmt,
    parse_fmt,
    read_audio,
    read_wav,
    write_wav,
)
from tests.support import naive_chunks, pattern_bytes, reference_interleave


@pytest.mark.parametrize("width", [2, 3, 4, 8])
@pytest.mark.parametrize("frames", [0, 1, 2, 10])
def test_interleave_matches_reference(width: int, frames: int):
    left = pattern_bytes(width, frames, 5)
    right = pattern_bytes(width, frames, 9)
    assert interleave(left, right, width) == reference_interleave(left, right, width)


def test_fmt_stereo_extensible_keeps_guid_and_sets_mask():
    fmt = make_fmt("ext-pcm24", 48_000, 1, channel_mask=0x1, valid_bits=20)
    parsed = parse_fmt(build_fmt(fmt))
    assert parsed.channels == 1
    assert parsed.channel_mask == 0x1
    assert parsed.valid_bits == 20
    assert parsed.subformat == fmt.subformat
    stereo = parse_fmt(build_fmt(parsed.as_stereo()))
    assert stereo.channels == 2
    assert stereo.block_align == 6
    assert stereo.byte_rate == 48_000 * 6
    assert stereo.bits_per_sample == 24
    assert stereo.channel_mask == 0x3
    assert stereo.subformat == fmt.subformat
    assert stereo.valid_bits == 20


def test_float_fmt_roundtrip_and_unsupported_depth():
    parsed = parse_fmt(build_fmt(make_fmt("float64", 96_000)))
    assert parsed.is_float
    assert parsed.bits_per_sample == 64
    assert parsed.channels == 1
    with pytest.raises(WavError, match="unsupported"):
        parse_fmt(struct.pack("<HHIIHH", 1, 1, 48_000, 48_000, 1, 8))


def test_bext_time_reference_is_64_bit():
    value = (12 << 32) + 230_400_000
    payload = build_bext(description="spot", time_reference=value, originator="Pro Tools")
    assert len(payload) >= 602
    assert bext_time_reference(payload) == value


def test_handbuilt_riff_with_odd_chunk(tmp_path: Path):
    fmt = struct.pack("<HHIIHH", 1, 1, 44_100, 88_200, 2, 16)
    audio = struct.pack("<hh", 1000, -1000)

    def chunk(cid: bytes, payload: bytes) -> bytes:
        pad = b"\x00" if len(payload) & 1 else b""
        return cid + struct.pack("<I", len(payload)) + payload + pad

    body = chunk(b"fmt ", fmt) + chunk(b"xyz ", b"abc") + chunk(b"data", audio)
    blob = b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body
    path = tmp_path / "hand.wav"
    path.write_bytes(blob)
    info = read_wav(path)
    assert info.container == RIFF
    assert info.fmt.sample_rate == 44_100
    assert info.fmt.channels == 1
    assert info.frames == 2
    assert info.chunk(b"xyz ").data == b"abc"
    assert read_audio(path, info) == audio


def test_rifx_is_rejected(tmp_path: Path):
    path = tmp_path / "bigendian.wav"
    path.write_bytes(b"RIFX" + struct.pack("<I", 4) + b"WAVE")
    with pytest.raises(WavError, match="big-endian"):
        read_wav(path)


def test_container_switches_past_four_gigabytes():
    chunks = [Chunk(b"fmt ", b"\x00" * 16)]
    assert container_for(chunks, 1000) == RIFF
    assert container_for(chunks, 0x100000000) == RF64
    assert container_for(chunks, 0x100000000, large_container=BW64) == BW64
    with pytest.raises(WavError):
        container_for(chunks, 0x100000000, force=RIFF)


def test_rf64_and_bw64_roundtrip_small_file(tmp_path: Path):
    audio = pattern_bytes(3, 5, 4)
    fmt = make_fmt("pcm24", 48_000)
    bext = build_bext(description="wide", time_reference=99, coding_history=b"X")
    chunks = build_wav_chunks(fmt, before_fmt=[Chunk(b"bext", bext)], frames=5)
    for fourcc in (RF64, BW64):
        path = tmp_path / f"{fourcc.decode()}.wav"
        write_wav(path, fmt=fmt, audio=audio, chunks=chunks, force_container=fourcc)
        blob = path.read_bytes()
        assert blob[:4] == fourcc
        assert struct.unpack_from("<I", blob, 4)[0] == UINT32_MAX
        assert blob[8:12] == b"WAVE"
        assert blob[12:16] == b"ds64"
        info = read_wav(path)
        assert info.container == fourcc
        assert info.ds64 is not None
        assert info.ds64.riff_size == len(blob) - 8
        assert info.ds64.data_size == len(audio)
        assert info.ds64.sample_count == 5
        assert info.chunk(b"bext").data == bext
        assert read_audio(path, info) == audio
        data_at = blob.rfind(b"data")
        assert struct.unpack_from("<I", blob, data_at + 4)[0] == UINT32_MAX


def test_classic_wav_size_field_and_odd_metadata(tmp_path: Path):
    audio = pattern_bytes(2, 4, 3)
    fmt = make_fmt("pcm16", 48_000)
    chunks = build_wav_chunks(fmt, after_fmt=[Chunk(b"xyz ", b"abc")], frames=4)
    path = tmp_path / "odd.wav"
    write_wav(path, fmt=fmt, audio=audio, chunks=chunks)
    blob = path.read_bytes()
    found = naive_chunks(blob)
    assert found[-1] == (b"data", audio)
    odd = next(data for cid, data in found if cid == b"xyz ")
    assert odd == b"abc"
    info = read_wav(path)
    assert read_audio(path, info) == audio


def test_stdlib_wave_reads_pcm16(tmp_path: Path):
    import wave

    audio = struct.pack("<hhhh", 1, -2, 3, -4)
    fmt = make_fmt("pcm16", 48_000, 2)
    chunks = build_wav_chunks(fmt, frames=2)
    path = tmp_path / "stereo.wav"
    write_wav(path, fmt=fmt, audio=audio, chunks=chunks)
    with wave.open(str(path)) as handle:
        assert handle.getnchannels() == 2
        assert handle.getframerate() == 48_000
        assert handle.getsampwidth() == 2
        assert handle.readframes(handle.getnframes()) == audio
