"""Shared helpers for the stereo-rejoin tests."""

from __future__ import annotations

import html
import struct
from pathlib import Path

from scg_stereorejoin.chunks import build_bext, build_cue, build_list_info
from scg_stereorejoin.pairing import default_patterns
from scg_stereorejoin.rejoin import process
from scg_stereorejoin.wav import Chunk, Fmt, build_wav_chunks, make_fmt, write_wav


def pattern_bytes(width: int, count: int, seed: int) -> bytes:
    data = bytearray()
    value = seed & 0xFF
    for _ in range(count * width):
        data.append(value)
        value = (value * 17 + 3) & 0xFF
    return bytes(data)


def reference_interleave(left: bytes, right: bytes, width: int) -> bytes:
    frames = len(left) // width
    out = bytearray()
    for index in range(frames):
        start = index * width
        out += left[start : start + width]
        out += right[start : start + width]
    return bytes(out)


def write_mono(
    path: Path,
    audio: bytes,
    *,
    encoding: str = "pcm24",
    rate: int = 48_000,
    bext: bytes | None = None,
    ixml: bytes | None = None,
    extra: list[Chunk] | None = None,
    channel_mask: int | None = None,
    include_fact: bool | None = None,
    valid_bits: int | None = None,
) -> None:
    fmt: Fmt = make_fmt(encoding, rate, 1, channel_mask=channel_mask, valid_bits=valid_bits)
    if len(audio) % fmt.block_align != 0:
        raise AssertionError("audio is not a whole number of frames")
    frames = len(audio) // fmt.block_align
    before = []
    if bext is not None:
        before.append(Chunk(b"bext", bext))
    after: list[Chunk] = []
    if ixml is not None:
        after.append(Chunk(b"iXML", ixml))
    if extra:
        after.extend(extra)
    chunks = build_wav_chunks(
        fmt,
        before_fmt=before,
        after_fmt=after,
        frames=frames,
        include_fact=include_fact,
    )
    write_wav(path, fmt=fmt, audio=audio, chunks=chunks)


def demo_bext(description: str, time_reference: int = 230_400_000, originator: str = "Nuendo") -> bytes:
    return build_bext(
        description=description,
        originator=originator,
        originator_reference="SCGTEST000000000000000000000001",
        origination_date="2026-11-05",
        origination_time="09:30:00",
        time_reference=time_reference,
        coding_history=b"A=PCM,F=48000,W=24,M=mono\r\n",
    )


def demo_ixml(
    *,
    name: str = "Dialogue.L",
    function: str = "LEFT",
    project: str = "Tom & Jerry",
    total_files: str = "2",
    file_index: str = "1",
    time_reference: int = 230_400_000,
    extra: str = "",
) -> bytes:
    high = (time_reference >> 32) & 0xFFFFFFFF
    low = time_reference & 0xFFFFFFFF
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<BWFXML>
  <!-- keep me -->
  <IXML_VERSION>1.61</IXML_VERSION>
  <PROJECT>{html.escape(project)}</PROJECT>
  <SCENE>01A</SCENE>
  <TAKE>3</TAKE>
  <NOTE></NOTE>
  <SPEED>
    <FILE_SAMPLE_RATE>48000</FILE_SAMPLE_RATE>
    <AUDIO_BIT_DEPTH>24</AUDIO_BIT_DEPTH>
    <TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_HI>{high}</TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_HI>
    <TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_LO>{low}</TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_LO>
  </SPEED>
  <FILE_SET>
    <TOTAL_FILES>{total_files}</TOTAL_FILES>
    <FAMILY_UID>FAMILY-KEEP</FAMILY_UID>
    <FAMILY_NAME>Dialogue</FAMILY_NAME>
    <FILE_SET_INDEX>{file_index}</FILE_SET_INDEX>
  </FILE_SET>
  <TRACK_LIST>
    <TRACK_COUNT>1</TRACK_COUNT>
    <TRACK>
      <CHANNEL_INDEX>1</CHANNEL_INDEX>
      <INTERLEAVE_INDEX>1</INTERLEAVE_INDEX>
      <NAME>{html.escape(name)}</NAME>
      <FUNCTION>{html.escape(function)}</FUNCTION>
      <NOTES>boom</NOTES>
    </TRACK>
  </TRACK_LIST>
  <USER><STUDIO>Nightshift</STUDIO></USER>
  {extra}
</BWFXML>
"""
    return xml.encode("utf-8")


def rich_pair(folder: Path, frames: int = 8, width: int = 3, encoding: str = "pcm24"):
    left_audio = pattern_bytes(width, frames, 11)
    right_audio = pattern_bytes(width, frames, 29)
    cue = build_cue(4)
    info = build_list_info(title="Dialogue", artist="SCG", comment="Split", software="Nuendo")
    write_mono(
        folder / "Dialogue.L.wav",
        left_audio,
        encoding=encoding,
        bext=demo_bext("left channel"),
        ixml=demo_ixml(name="Dialogue.L", function="LEFT", file_index="1"),
        extra=[cue, info],
    )
    write_mono(
        folder / "Dialogue.R.wav",
        right_audio,
        encoding=encoding,
        bext=demo_bext("right channel"),
        ixml=demo_ixml(name="Dialogue.R", function="RIGHT", file_index="2"),
    )
    return left_audio, right_audio


def join_folder(folder: Path, output: Path, **kwargs):
    return process(
        [folder],
        output_dir=output,
        patterns=kwargs.pop("patterns", default_patterns()),
        **kwargs,
    )


def naive_chunks(blob: bytes) -> list[tuple[bytes, bytes]]:
    """Walk a classic RIFF/WAVE file without the package reader."""
    assert blob[:4] == b"RIFF", blob[:4]
    assert blob[8:12] == b"WAVE"
    declared = struct.unpack_from("<I", blob, 4)[0]
    end = 8 + declared
    assert end == len(blob)
    pos = 12
    found = []
    while pos + 8 <= end:
        cid, size = struct.unpack_from("<4sI", blob, pos)
        pos += 8
        data = blob[pos : pos + size]
        assert len(data) == size
        found.append((cid, data))
        pos += size + (size & 1)
    assert pos == end
    return found
