"""Bit-exact joins, metadata, and mismatch policy."""

from __future__ import annotations

import os
import struct
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scg_stereorejoin.chunks import bext_time_reference
from scg_stereorejoin.pairing import Pair, load_patterns
from scg_stereorejoin.rejoin import process, rejoin_pair
from scg_stereorejoin.samples import make_samples
from scg_stereorejoin.wav import RF64, read_audio, read_wav, write_interleaved_wav
from tests.support import (
    demo_bext,
    demo_ixml,
    join_folder,
    naive_chunks,
    pattern_bytes,
    reference_interleave,
    rich_pair,
    write_mono,
)


def _local(tag: str) -> str:
    if tag.startswith("{"):
        tag = tag.split("}", 1)[1]
    return tag.upper()


def element_texts(blob: bytes) -> dict[str, list[str]]:
    payload = blob.split(b"?>", 1)[-1]
    root = ET.fromstring(payload)
    found: dict[str, list[str]] = {}
    for element in root.iter():
        if isinstance(element.tag, str) and element.text and element.text.strip():
            found.setdefault(_local(element.tag), []).append(element.text.strip())
    return found


@pytest.mark.parametrize(
    ("encoding", "width"),
    [("pcm16", 2), ("pcm24", 3), ("pcm32", 4), ("float32", 4), ("float64", 8)],
)
def test_bit_exact_for_every_supported_encoding(tmp_path: Path, encoding: str, width: int):
    frames = 10
    left = pattern_bytes(width, frames, 7)
    right = pattern_bytes(width, frames, 13)
    write_mono(tmp_path / "Take.L.wav", left, encoding=encoding)
    write_mono(tmp_path / "Take.R.wav", right, encoding=encoding)
    report = join_folder(tmp_path, tmp_path / "out", chunk_frames=3)
    assert report.ok
    assert len(report.joined) == 1
    item = report.joined[0]
    info = read_wav(item.output)
    assert info.fmt.channels == 2
    assert info.fmt.sample_rate == 48_000
    assert info.fmt.bits_per_sample == width * 8
    assert info.frames == frames
    assert read_audio(item.output, info) == reference_interleave(left, right, width)
    if encoding.startswith("float"):
        fact = info.chunk(b"fact")
        assert fact is not None
        assert struct.unpack("<I", fact.data)[0] == frames
    else:
        assert info.chunk(b"fact") is None
    blob = item.output.read_bytes()
    found = dict(naive_chunks(blob))
    fmt = found[b"fmt "]
    _tag, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", fmt)
    assert (channels, rate, bits, align) == (2, 48_000, width * 8, width * 2)
    assert byte_rate == 48_000 * width * 2
    assert found[b"data"] == reference_interleave(left, right, width)


def test_extensible_masks_become_stereo_and_samples_stay_put(tmp_path: Path):
    left = pattern_bytes(3, 6, 2)
    right = pattern_bytes(3, 6, 4)
    write_mono(tmp_path / "A.L.wav", left, encoding="ext-pcm24", channel_mask=0x1, valid_bits=24)
    write_mono(tmp_path / "A.R.wav", right, encoding="ext-pcm24", channel_mask=0x2, valid_bits=24)
    report = join_folder(tmp_path, tmp_path / "out")
    assert report.ok
    info = read_wav(report.joined[0].output)
    assert info.fmt.channels == 2
    assert info.fmt.channel_mask == 0x3
    assert info.fmt.is_extensible
    assert info.fmt.is_pcm
    assert read_audio(report.joined[0].output, info) == reference_interleave(left, right, 3)


def test_metadata_is_preserved_and_ixml_describes_two_channels(tmp_path: Path):
    frames = 8
    left, right = rich_pair(tmp_path, frames=frames, width=3)
    report = join_folder(tmp_path, tmp_path / "out")
    assert report.ok, report.refused
    item = report.joined[0]
    info = read_wav(item.output)
    source = read_wav(tmp_path / "Dialogue.L.wav")
    assert info.chunk(b"bext").data == source.chunk(b"bext").data
    assert bext_time_reference(info.chunk(b"bext").data) == 230_400_000
    assert info.chunk(b"cue ").data == source.chunk(b"cue ").data
    assert info.chunk(b"LIST").data == source.chunk(b"LIST").data
    body = element_texts(info.chunk(b"iXML").data)
    assert body["PROJECT"] == ["Tom & Jerry"]
    assert body["TRACK_COUNT"] == ["2"]
    assert body["FUNCTION"] == ["LEFT", "RIGHT"]
    assert body["NAME"] == ["Dialogue.L", "Dialogue.R"]
    assert body["TOTAL_FILES"] == ["1"]
    assert body["TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_LO"] == ["230400000"]
    assert body["STUDIO"] == ["Nightshift"]
    assert read_audio(item.output, info) == reference_interleave(left, right, 3)
    assert item.time_reference == 230_400_000
    assert "bext" in item.chunks
    assert "iXML" in item.chunks


def test_time_reference_mismatch_keeps_the_left_bext(tmp_path: Path):
    audio = pattern_bytes(2, 4, 1)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16", bext=demo_bext("L", time_reference=100))
    write_mono(tmp_path / "A.R.wav", audio, encoding="pcm16", bext=demo_bext("R", time_reference=200))
    report = join_folder(tmp_path, tmp_path / "out")
    assert report.ok
    warning = " ".join(report.joined[0].warnings)
    assert "TimeReference differs" in warning
    info = read_wav(report.joined[0].output)
    assert bext_time_reference(info.chunk(b"bext").data) == 100


def test_missing_bext_warns_and_still_joins(tmp_path: Path):
    audio = pattern_bytes(2, 4, 8)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", audio, encoding="pcm16")
    report = join_folder(tmp_path, tmp_path / "out")
    assert report.ok
    assert any("no bext" in warning for warning in report.joined[0].warnings)
    info = read_wav(report.joined[0].output)
    assert info.chunk(b"bext") is None
    assert read_audio(report.joined[0].output, info) == reference_interleave(audio, audio, 2)


def test_invalid_ixml_does_not_block_the_audio(tmp_path: Path):
    audio = pattern_bytes(2, 4, 6)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16", ixml=b"<not xml")
    write_mono(tmp_path / "A.R.wav", audio, encoding="pcm16", ixml=b"<not xml")
    report = join_folder(tmp_path, tmp_path / "out")
    assert report.ok
    assert any("not valid XML" in warning for warning in report.joined[0].warnings)
    info = read_wav(report.joined[0].output)
    assert info.chunk(b"iXML").data == b"<not xml"
    assert read_audio(report.joined[0].output, info) == reference_interleave(audio, audio, 2)


def test_sample_rate_and_format_mismatch_are_refused(tmp_path: Path):
    write_mono(tmp_path / "A.L.wav", pattern_bytes(2, 4, 1), encoding="pcm16", rate=48_000)
    write_mono(tmp_path / "A.R.wav", pattern_bytes(2, 4, 1), encoding="pcm16", rate=44_100)
    report = join_folder(tmp_path, tmp_path / "out")
    assert not report.ok
    assert "sample rate mismatch" in report.refused[0].reason
    assert not (tmp_path / "out" / "A.wav").exists()
    assert not (tmp_path / "out" / "A.wav.partial").exists()

    other = tmp_path / "fmt"
    write_mono(other / "B.L.wav", pattern_bytes(4, 4, 1), encoding="pcm32")
    write_mono(other / "B.R.wav", pattern_bytes(4, 4, 1), encoding="float32")
    refused = join_folder(other, other / "out")
    assert "sample format mismatch" in refused.refused[0].reason
    assert refused.joined == []


def test_length_mismatch_refuses_unless_pad_is_set(tmp_path: Path):
    left = pattern_bytes(2, 4, 3)
    right = pattern_bytes(2, 6, 9)
    write_mono(tmp_path / "A.L.wav", left, encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", right, encoding="pcm16")
    refused = join_folder(tmp_path, tmp_path / "nope")
    assert "length mismatch" in refused.refused[0].reason
    assert "--pad" in refused.refused[0].reason
    assert not (tmp_path / "nope" / "A.wav").exists()

    padded = join_folder(tmp_path, tmp_path / "out", pad=True, chunk_frames=3)
    assert padded.ok
    assert padded.joined[0].padded_left == 2
    info = read_wav(padded.joined[0].output)
    silence = bytes(2 * 2)
    expected = reference_interleave(left + silence, right, 2)
    assert read_audio(padded.joined[0].output, info) == expected
    assert any("padded the left" in warning for warning in padded.joined[0].warnings)


def test_stereo_source_is_refused(tmp_path: Path):
    from scg_stereorejoin.wav import build_wav_chunks, make_fmt, write_wav

    fmt = make_fmt("pcm16", 48_000, 2)
    audio = pattern_bytes(4, 4, 1)
    chunks = build_wav_chunks(fmt, frames=4)
    write_wav(tmp_path / "Song.L.wav", fmt=fmt, audio=audio, chunks=chunks)
    write_mono(tmp_path / "Song.R.wav", pattern_bytes(2, 4, 2), encoding="pcm16")
    report = join_folder(tmp_path, tmp_path / "out")
    assert "channels" in report.refused[0].reason
    assert report.joined == []


def test_overwrite_delete_and_dry_run(tmp_path: Path):
    audio = pattern_bytes(2, 4, 5)
    other = pattern_bytes(2, 4, 8)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", audio, encoding="pcm16")
    output = tmp_path / "out"
    first = join_folder(tmp_path, output)
    assert first.ok
    dest = output / "A.wav"
    original = dest.read_bytes()

    write_mono(tmp_path / "A.L.wav", other, encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", other, encoding="pcm16")
    blocked = join_folder(tmp_path, output)
    assert not blocked.ok
    assert "already exists" in blocked.refused[0].reason
    assert dest.read_bytes() == original

    replaced = join_folder(tmp_path, output, overwrite=True)
    assert replaced.ok
    assert dest.read_bytes() != original

    dry = join_folder(tmp_path, tmp_path / "dry", dry_run=True)
    assert dry.ok
    assert dry.joined[0].wrote is False
    assert not (tmp_path / "dry").exists()

    deleted = join_folder(tmp_path, tmp_path / "gone", delete_sources=True)
    assert deleted.ok
    assert (tmp_path / "gone" / "A.wav").is_file()
    assert not (tmp_path / "A.L.wav").exists()
    assert not (tmp_path / "A.R.wav").exists()


def test_delete_is_not_applied_when_the_pair_is_refused(tmp_path: Path):
    write_mono(tmp_path / "A.L.wav", pattern_bytes(2, 4, 1), encoding="pcm16", rate=48_000)
    write_mono(tmp_path / "A.R.wav", pattern_bytes(2, 4, 1), encoding="pcm16", rate=44_100)
    report = join_folder(tmp_path, tmp_path / "out", delete_sources=True)
    assert not report.ok
    assert (tmp_path / "A.L.wav").is_file()
    assert (tmp_path / "A.R.wav").is_file()


def test_same_stem_in_two_folders_stays_two_pairs(tmp_path: Path):
    for folder in ("a", "b"):
        write_mono(tmp_path / folder / "Kick.L.wav", pattern_bytes(2, 2, 1), encoding="pcm16")
        write_mono(tmp_path / folder / "Kick.R.wav", pattern_bytes(2, 2, 2), encoding="pcm16")
    report = process(
        [tmp_path],
        output_dir=tmp_path / "out",
        recursive=True,
        patterns=load_patterns(),
    )
    assert report.ok
    assert {item.output.name for item in report.joined} == {"Kick.wav"}
    assert (tmp_path / "out" / "a" / "Kick.wav").is_file()
    assert (tmp_path / "out" / "b" / "Kick.wav").is_file()


def test_flat_output_reports_a_name_collision(tmp_path: Path):
    files = []
    for folder in ("a", "b"):
        left = tmp_path / folder / "Kick.L.wav"
        right = tmp_path / folder / "Kick.R.wav"
        write_mono(left, pattern_bytes(2, 2, 1), encoding="pcm16")
        write_mono(right, pattern_bytes(2, 2, 2), encoding="pcm16")
        files.extend([left, right])
    report = process(files, output_dir=tmp_path / "out", patterns=load_patterns())
    assert len(report.joined) == 1
    assert len(report.refused) == 1
    assert "collides" in report.refused[0].reason


def test_unpaired_files_do_not_fail_the_batch(tmp_path: Path):
    write_mono(tmp_path / "A.L.wav", pattern_bytes(2, 2, 1), encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", pattern_bytes(2, 2, 2), encoding="pcm16")
    write_mono(tmp_path / "Orphan.L.wav", pattern_bytes(2, 2, 3), encoding="pcm16")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / "Bright.wav").write_bytes(b"RIFF")
    report = join_folder(tmp_path, tmp_path / "out")
    assert report.ok
    assert len(report.joined) == 1
    assert [item.path.name for item in report.unpaired] == ["Orphan.L.wav"]
    assert any(item.path.name == "Bright.wav" for item in report.unmatched)


def test_recursive_flag_and_hidden_files(tmp_path: Path):
    write_mono(tmp_path / "nested" / "Hat.L.wav", pattern_bytes(2, 2, 1), encoding="pcm16")
    write_mono(tmp_path / "nested" / "Hat.R.wav", pattern_bytes(2, 2, 2), encoding="pcm16")
    write_mono(tmp_path / "nested" / ".hidden" / "Nope.L.wav", pattern_bytes(2, 2, 1), encoding="pcm16")
    write_mono(tmp_path / "nested" / ".hidden" / "Nope.R.wav", pattern_bytes(2, 2, 2), encoding="pcm16")
    shallow = process([tmp_path], output_dir=tmp_path / "shallow", recursive=False, patterns=load_patterns())
    assert shallow.joined == []
    deep = process([tmp_path], output_dir=tmp_path / "deep", recursive=True, patterns=load_patterns())
    assert [item.output.name for item in deep.joined] == ["Hat.wav"]
    assert deep.ok


def test_fact_chunk_counts_frames_not_samples_times_channels(tmp_path: Path):
    audio = pattern_bytes(2, 5, 4)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16", include_fact=True)
    write_mono(tmp_path / "A.R.wav", audio, encoding="pcm16", include_fact=True)
    report = join_folder(tmp_path, tmp_path / "out")
    info = read_wav(report.joined[0].output)
    assert struct.unpack("<I", info.chunk(b"fact").data)[0] == 5


def test_pcm_with_ixml_only_on_the_right_uses_that_document(tmp_path: Path):
    audio = pattern_bytes(2, 4, 2)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16")
    write_mono(
        tmp_path / "A.R.wav",
        audio,
        encoding="pcm16",
        ixml=demo_ixml(name="Hat.R", function="RIGHT"),
    )
    report = join_folder(tmp_path, tmp_path / "out")
    assert report.ok
    assert any("right file's iXML" in warning for warning in report.joined[0].warnings)
    info = read_wav(report.joined[0].output)
    assert element_texts(info.chunk(b"iXML").data)["TRACK_COUNT"] == ["2"]


def test_demo_pack_rejoins_bit_exactly(tmp_path: Path):
    source = tmp_path / "examples"
    make_samples(source)
    output = tmp_path / "stereo"
    report = process(
        [source],
        output_dir=output,
        recursive=True,
        patterns=load_patterns(),
    )
    assert report.ok, (report.refused, report.errors)
    assert len(report.joined) == 6
    assert [item.path.name for item in report.unpaired] == ["Orphan.L.wav"]
    assert report.unmatched == []
    expected = {
        output / "Dialogue.wav",
        output / "Print.wav",
        output / "Fx.wav",
        output / "Crowd.wav",
        output / "Ambience.wav",
        output / "session" / "Boom.wav",
    }
    assert {item.output for item in report.joined} == expected
    for item in report.joined:
        left_info = read_wav(item.left)
        right_info = read_wav(item.right)
        out_info = read_wav(item.output)
        width = left_info.fmt.sample_width
        assert out_info.fmt.channels == 2
        assert out_info.fmt.sample_rate == left_info.fmt.sample_rate
        assert out_info.fmt.bits_per_sample == left_info.fmt.bits_per_sample
        assert out_info.frames == left_info.frames
        assert read_audio(item.output, out_info) == reference_interleave(
            read_audio(item.left, left_info),
            read_audio(item.right, right_info),
            width,
        )
        if left_info.chunk(b"bext") is not None:
            assert out_info.chunk(b"bext").data == left_info.chunk(b"bext").data
    dialogue = read_wav(output / "Dialogue.wav")
    assert bext_time_reference(dialogue.chunk(b"bext").data) == 230_400_000
    body = element_texts(dialogue.chunk(b"iXML").data)
    assert body["PROJECT"] == ["SCG Stereo Rejoin Demo"]
    assert body["TRACK_COUNT"] == ["2"]
    assert body["FUNCTION"] == ["LEFT", "RIGHT"]
    assert body["TOTAL_FILES"] == ["1"]
    assert body["STUDIO"] == ["Nightshift"]
    assert dialogue.chunk(b"cue ") is not None
    assert dialogue.chunk(b"LIST") is not None
    fx = read_wav(output / "Fx.wav")
    assert fx.fmt.is_float
    assert struct.unpack("<I", fx.chunk(b"fact").data)[0] == fx.frames


def test_overwrite_refuses_output_that_is_another_pairs_source(tmp_path: Path):
    """Batch --overwrite must not replace a WAV that a later pair still has to read."""
    kept = pattern_bytes(2, 4, 1)
    incoming = pattern_bytes(2, 4, 9)
    write_mono(tmp_path / "X.L.wav", incoming, encoding="pcm16")
    write_mono(tmp_path / "X.R.wav", incoming, encoding="pcm16")
    write_mono(tmp_path / "X.wav", kept, encoding="pcm16")
    write_mono(tmp_path / "Y.wav", kept, encoding="pcm16")
    original = (tmp_path / "X.wav").read_bytes()
    report = process(
        [tmp_path],
        output_dir=tmp_path,
        patterns=load_patterns(["X/Y"]),
        overwrite=True,
    )
    assert (tmp_path / "X.wav").read_bytes() == original
    assert (tmp_path / "Y.wav").read_bytes() == original
    refused = [item for item in report.refused if item.left and item.left.name == "X.L.wav"]
    assert refused
    assert "input" in refused[0].reason
    stereo = tmp_path / "stereo.wav"
    assert stereo.is_file()
    info = read_wav(stereo)
    assert read_audio(stereo, info) == reference_interleave(kept, kept, 2)


def test_overwrite_refuses_output_that_collides_with_any_batch_input(tmp_path: Path):
    """An output that lands on any input WAV is refused, even if that WAV is unpaired."""
    audio = pattern_bytes(2, 4, 3)
    write_mono(tmp_path / "Take.L.wav", audio, encoding="pcm16")
    write_mono(tmp_path / "Take.R.wav", audio, encoding="pcm16")
    write_mono(tmp_path / "Take.wav", audio, encoding="pcm16")
    original = (tmp_path / "Take.wav").read_bytes()
    report = process(
        [tmp_path],
        output_dir=tmp_path,
        patterns=load_patterns(),
        overwrite=True,
    )
    assert (tmp_path / "Take.wav").read_bytes() == original
    assert report.joined == []
    assert report.refused
    assert "input" in report.refused[0].reason


def test_existing_partial_is_left_alone_without_overwrite(tmp_path: Path):
    """The fixed name Dest.wav.partial must not be reused, with or without --overwrite."""
    audio = pattern_bytes(2, 4, 5)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", audio, encoding="pcm16")
    output = tmp_path / "out"
    output.mkdir()
    sentinel = output / "A.wav.partial"
    payload = b"keep-me-untouched-partial"
    sentinel.write_bytes(payload)
    report = join_folder(tmp_path, output)
    assert report.ok
    assert sentinel.read_bytes() == payload
    info = read_wav(output / "A.wav")
    assert read_audio(output / "A.wav", info) == reference_interleave(audio, audio, 2)
    leftovers = sorted(path.name for path in output.iterdir() if ".partial" in path.name)
    assert leftovers == ["A.wav.partial"]


def test_failed_write_removes_only_its_own_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = pattern_bytes(2, 4, 5)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", audio, encoding="pcm16")
    output = tmp_path / "out"
    output.mkdir()
    sentinel = output / "A.wav.partial"
    sentinel.write_bytes(b"keep-me")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("scg_stereorejoin.rejoin.write_interleaved_wav", boom)
    report = join_folder(tmp_path, output)
    assert not report.ok
    assert sentinel.read_bytes() == b"keep-me"
    assert not (output / "A.wav").exists()
    assert sorted(path.name for path in output.iterdir()) == ["A.wav.partial"]


def test_overlapping_writes_do_not_share_a_partial_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two joins of the same destination must not open one shared *.partial file."""
    audio = pattern_bytes(2, 8, 6)
    left = tmp_path / "A.L.wav"
    right = tmp_path / "A.R.wav"
    write_mono(left, audio, encoding="pcm16")
    write_mono(right, audio, encoding="pcm16")
    dest = tmp_path / "out" / "A.wav"
    pair = Pair(left=left, right=right, normalized="A", output_name="A.wav")
    paths: list[str] = []
    paths_lock = threading.Lock()
    first_entered = threading.Event()
    release = threading.Event()

    def wrapped(path, **kwargs):
        with paths_lock:
            paths.append(Path(path).name)
            first = len(paths) == 1
        if first:
            first_entered.set()
            assert release.wait(5)
        return write_interleaved_wav(path, **kwargs)

    monkeypatch.setattr("scg_stereorejoin.rejoin.write_interleaved_wav", wrapped)

    errors: list[BaseException] = []

    def once():
        try:
            rejoin_pair(
                pair,
                dest,
                pad=False,
                overwrite=True,
                delete_sources=False,
                dry_run=False,
                large_container=RF64,
                chunk_frames=4,
            )
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=once)
    second = threading.Thread(target=once)
    first.start()
    assert first_entered.wait(5)
    second.start()
    for _ in range(100):
        with paths_lock:
            if len(paths) >= 2:
                break
        release.wait(0.02)
    release.set()
    first.join(5)
    second.join(5)
    assert len(paths) >= 2
    assert paths[0] != paths[1]
    assert errors == []
    info = read_wav(dest)
    assert read_audio(dest, info) == reference_interleave(audio, audio, 2)
    assert not list(dest.parent.glob("*.partial"))
    assert not list(dest.parent.glob(".*.partial"))


def test_delete_sources_waits_until_the_output_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = pattern_bytes(2, 4, 5)
    write_mono(tmp_path / "A.L.wav", audio, encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", audio, encoding="pcm16")

    real_replace = os.replace

    def replace_and_corrupt(src, dst):
        real_replace(src, dst)
        Path(dst).write_bytes(b"not a wav")

    monkeypatch.setattr("scg_stereorejoin.rejoin.os.replace", replace_and_corrupt)
    report = join_folder(tmp_path, tmp_path / "out", delete_sources=True)
    assert (tmp_path / "A.L.wav").is_file()
    assert (tmp_path / "A.R.wav").is_file()
    assert not report.ok
    assert report.joined == []
