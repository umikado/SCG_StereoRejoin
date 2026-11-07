"""Independent safety regressions for single-active-channel stereo carriers."""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from scg_stereorejoin import rejoin as rejoin_mod
from scg_stereorejoin.pairing import default_patterns
from scg_stereorejoin.wav import build_wav_chunks, make_fmt, read_audio, read_wav, write_wav


def _interleave(left: bytes, right: bytes, width: int) -> bytes:
    assert len(left) == len(right)
    return b"".join(left[i:i + width] + right[i:i + width] for i in range(0, len(left), width))


def _write(path: Path, first: bytes, second: bytes | None = None, encoding="pcm16") -> None:
    fmt = make_fmt(encoding, 48000, 1 if second is None else 2)
    data = first if second is None else _interleave(first, second, fmt.sample_width)
    write_wav(path, fmt=fmt, audio=data, chunks=build_wav_chunks(fmt, frames=len(data) // fmt.block_align))


def _join(root: Path, **kwargs):
    return rejoin_mod.process([root], output_dir=root / "out", patterns=default_patterns(), **kwargs)


def _audio(root: Path) -> bytes:
    path = root / "out" / "Take.wav"
    return read_audio(path, read_wav(path))


def _assert_refused(root: Path, report):
    assert not report.ok
    assert not report.joined
    assert report.refused or report.errors
    assert (root / "Take.L.wav").exists()
    assert (root / "Take.R.wav").exists()
    assert not list(root.rglob("*.partial"))


@pytest.mark.parametrize("left_stereo,right_stereo", [(True, True), (True, False), (False, True)])
def test_filename_side_controls_output_not_internal_active_channel(tmp_path, left_stereo, right_stereo):
    left = struct.pack("<7h", 10, -11, 0, 0, 12, -13, 14)
    right = struct.pack("<7h", -20, 21, 0, 22, 0, 23, -24)
    # Deliberately reverse physical channels: filename L uses channel 2.
    _write(tmp_path / "Take.L.wav", bytes(len(left)) if left_stereo else left, left if left_stereo else None)
    _write(tmp_path / "Take.R.wav", right, bytes(len(right)) if right_stereo else None)
    report = _join(tmp_path, chunk_frames=3)
    assert report.ok, report.refused
    assert _audio(tmp_path) == _interleave(left, right, 2)


@pytest.mark.parametrize("both_active", [False, True])
def test_activity_beyond_block_boundary_is_scanned(tmp_path, both_active):
    frames = 65536 + 3
    late = bytes((frames - 1) * 2) + b"\x01\x00"
    early = b"\x02\x00" + bytes((frames - 1) * 2) if both_active else bytes(frames * 2)
    _write(tmp_path / "Take.L.wav", early, late)
    _write(tmp_path / "Take.R.wav", late)
    report = _join(tmp_path, chunk_frames=17)
    if both_active:
        _assert_refused(tmp_path, report)
        assert not (tmp_path / "out" / "Take.wav").exists()
    else:
        assert report.ok, report.refused
        assert _audio(tmp_path) == _interleave(late, late, 2)


@pytest.mark.parametrize("encoding,width,code", [("float32", 4, "f"), ("float64", 8, "d")])
def test_signed_float_zeros_are_silent_and_active_bits_are_preserved(tmp_path, encoding, width, code):
    active = struct.pack("<" + code * 4, 0.25, -0.5, 0.0, -0.0)
    zeros = struct.pack("<" + code * 4, -0.0, 0.0, -0.0, 0.0)
    _write(tmp_path / "Take.L.wav", zeros, active, encoding)
    _write(tmp_path / "Take.R.wav", active, zeros, encoding)
    report = _join(tmp_path, chunk_frames=1)
    assert report.ok, report.refused
    assert _audio(tmp_path) == _interleave(active, active, width)


@pytest.mark.parametrize("encoding,width,code", [("float32", 4, "f"), ("float64", 8, "d")])
@pytest.mark.parametrize("kind", ["subnormal", "nan", "positive_inf", "negative_inf"])
def test_no_float_nonzero_is_mistaken_for_silence(tmp_path, encoding, width, code, kind):
    odd = (1).to_bytes(width, "little") if kind == "subnormal" else struct.pack("<" + code, {"nan": float("nan"), "positive_inf": float("inf"), "negative_inf": -float("inf")}[kind])
    ordinary = struct.pack("<" + code, 0.5)
    _write(tmp_path / "Take.L.wav", ordinary, odd, encoding)
    _write(tmp_path / "Take.R.wav", ordinary, None, encoding)
    report = _join(tmp_path, delete_sources=True)
    _assert_refused(tmp_path, report)
    assert not (tmp_path / "out" / "Take.wav").exists()


@pytest.mark.parametrize("side", ["L", "R"])
def test_ignored_channel_rewrite_cannot_replace_output_or_retire_sources(tmp_path, monkeypatch, side):
    active = struct.pack("<8h", *range(1, 9))
    for name in ("L", "R"):
        _write(tmp_path / f"Take.{name}.wav", active, bytes(len(active)))
    dest = tmp_path / "out" / "Take.wav"
    dest.parent.mkdir()
    dest.write_bytes(b"existing output must survive")
    source = tmp_path / f"Take.{side}.wav"
    offset = read_wav(source).data_offset
    original_write = rejoin_mod.write_interleaved_wav
    calls = []

    def write_after_mutating_ignored_channel(path, **kwargs):
        stamp = source.stat()
        with source.open("r+b") as handle:
            handle.seek(offset + 2)
            handle.write(b"\x01\x00")
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        calls.append(True)
        return original_write(path, **kwargs)

    # Emulate coarse timestamp resolution: full raw-channel hashes must detect this.
    monkeypatch.setattr(rejoin_mod, "_ctime_ns", lambda stat: 123)
    monkeypatch.setattr(rejoin_mod, "write_interleaved_wav", write_after_mutating_ignored_channel)
    report = _join(tmp_path, overwrite=True, delete_sources=True, chunk_frames=3)
    assert calls, "test must reach the writer after valid carrier analysis"
    _assert_refused(tmp_path, report)
    assert dest.read_bytes() == b"existing output must survive"
    assert read_audio(source, read_wav(source))[2:4] == b"\x01\x00"
    assert not list(tmp_path.rglob(".scg_stereorejoin_trash"))


@pytest.mark.parametrize("damage", ["block_align", "truncated"])
def test_malformed_stereo_carrier_is_refused(tmp_path, damage):
    active = b"\x01\x00" * 8
    source = tmp_path / "Take.L.wav"
    _write(source, active, bytes(len(active)))
    _write(tmp_path / "Take.R.wav", active)
    blob = bytearray(source.read_bytes())
    if damage == "block_align":
        fmt_start = blob.index(b"fmt ") + 8
        struct.pack_into("<H", blob, fmt_start + 12, 2)
    else:
        del blob[-1:]
    source.write_bytes(blob)
    report = _join(tmp_path, delete_sources=True)
    _assert_refused(tmp_path, report)
    assert not (tmp_path / "out" / "Take.wav").exists()


def test_dryrun_scans_carriers_but_does_not_create_or_retire(tmp_path):
    active = b"\x01\x00" * 10
    _write(tmp_path / "Take.L.wav", bytes(len(active)), active)
    _write(tmp_path / "Take.R.wav", active, bytes(len(active)))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    report = _join(tmp_path, dry_run=True, delete_sources=True, chunk_frames=3)
    assert report.ok, report.refused
    assert len(report.joined) == 1 and not report.joined[0].wrote
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_carrier_success_retires_full_original_files(tmp_path):
    active = b"\x01\x00" * 10
    for side in ("L", "R"):
        _write(tmp_path / f"Take.{side}.wav", active, bytes(len(active)))
    originals = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    report = _join(tmp_path, delete_sources=True, chunk_frames=3)
    assert report.ok, report.refused
    assert _audio(tmp_path) == _interleave(active, active, 2)
    for name, original in originals.items():
        assert not (tmp_path / name).exists()
        retired = list((tmp_path / ".scg_stereorejoin_trash").rglob(name))
        assert len(retired) == 1 and retired[0].read_bytes() == original


def test_concurrent_output_is_not_clobbered_for_carriers(tmp_path, monkeypatch):
    active = b"\x01\x00" * 10
    for side in ("L", "R"):
        _write(tmp_path / f"Take.{side}.wav", active, bytes(len(active)))
    original_write = rejoin_mod.write_interleaved_wav
    dest = tmp_path / "out" / "Take.wav"
    calls = []

    def concurrent_writer(path, **kwargs):
        result = original_write(path, **kwargs)
        dest.write_bytes(b"concurrent output")
        calls.append(True)
        return result

    monkeypatch.setattr(rejoin_mod, "write_interleaved_wav", concurrent_writer)
    report = _join(tmp_path, delete_sources=True)
    assert calls
    _assert_refused(tmp_path, report)
    assert dest.read_bytes() == b"concurrent output"


def test_long_carriers_use_bounded_source_reads(tmp_path, monkeypatch):
    frames = 300001
    active = bytes((frames - 1) * 2) + b"\x01\x00"
    for side in ("L", "R"):
        _write(tmp_path / f"Take.{side}.wav", bytes(len(active)), active)
    sources = {tmp_path / "Take.L.wav", tmp_path / "Take.R.wav"}
    real_open = Path.open
    sizes = []

    class BoundedReader:
        def __init__(self, handle):
            self.handle = handle
        def __getattr__(self, name):
            return getattr(self.handle, name)
        def read(self, size=-1):
            assert 0 <= size <= 1048576, f"unbounded source read: {size}"
            sizes.append(size)
            return self.handle.read(size)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()

    def guarded_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        return BoundedReader(handle) if path in sources and mode == "rb" else handle

    monkeypatch.setattr(Path, "open", guarded_open)
    report = _join(tmp_path, chunk_frames=4093)
    assert report.ok, report.refused
    assert sizes
    assert _audio(tmp_path) == _interleave(active, active, 2)


def test_post_publish_ignored_channel_rewrite_is_not_retired(tmp_path, monkeypatch):
    active = b"\x01\x00" * 10
    left = tmp_path / "Take.L.wav"
    right = tmp_path / "Take.R.wav"
    _write(left, active, bytes(len(active)))
    _write(right, bytes(len(active)), active)
    offset = read_wav(left).data_offset
    verify = rejoin_mod._verify_published
    calls = []

    def verify_then_rewrite(path, **kwargs):
        verify(path, **kwargs)
        stamp = left.stat()
        with left.open("r+b") as handle:
            handle.seek(offset + 2)
            handle.write(b"\x02\x00")
        os.utime(left, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        calls.append(True)

    monkeypatch.setattr(rejoin_mod, "_verify_published", verify_then_rewrite)
    report = _join(tmp_path, delete_sources=True, chunk_frames=3)
    assert calls
    assert report.ok, report.refused
    assert _audio(tmp_path) == _interleave(active, active, 2)
    assert left.exists(), "full carrier hash must protect a changed formerly silent channel"
    assert read_audio(left, read_wav(left))[2:4] == b"\x02\x00"
    assert any("changed" in warning for warning in report.joined[0].warnings)
    assert not right.exists(), "unchanged stereo source can still be safely retired"
