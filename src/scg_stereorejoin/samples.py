"""Write a small folder of split-mono WAVs for the README and the CLI.

Run ``python -m scg_stereorejoin.samples ./examples``.
"""

from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path

from scg_stereorejoin.chunks import build_bext, build_cue, build_list_info
from scg_stereorejoin.wav import Chunk, build_wav_chunks, make_fmt, write_wav


def make_samples(dest: Path) -> list[Path]:
    """Create the demo split pairs. Existing files in ``dest`` are replaced."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    specs = [
        _Spec("Dialogue.L.wav", "Dialogue.R.wav", "Dialogue", "pcm24", 48_000, 440.0, 660.0, "Nuendo", 230_400_000, True),
        _Spec("Print_L.wav", "Print_R.wav", "Print", "pcm16", 48_000, 330.0, 495.0, "Pro Tools", 1_440_000, False),
        _Spec("Fx-L.wav", "Fx-R.wav", "Fx", "float32", 48_000, 180.0, 240.0, "Cubase", 960_000, False),
        _Spec("Crowd Left.wav", "Crowd Right.wav", "Crowd", "pcm24", 48_000, 200.0, 300.0, "Nuendo", 480_000, False),
        _Spec("Ambience.1.wav", "Ambience.2.wav", "Ambience", "pcm24", 96_000, 90.0, 120.0, "Nuendo", 96_000, False),
    ]
    for spec in specs:
        written.extend(_write_pair(dest, spec))
    nested = dest / "session"
    written.extend(
        _write_pair(
            nested,
            _Spec("Boom_Left.wav", "Boom_Right.wav", "Boom", "pcm24", 48_000, 80.0, 160.0, "Pro Tools", 2_400_000, False),
        )
    )
    orphan = dest / "Orphan.L.wav"
    _write_mono(
        orphan,
        encoding="pcm16",
        rate=48_000,
        frequency=523.25,
        frames=2_400,
        side="L",
        stem="Orphan",
        originator="Nuendo",
        time_reference=48_000,
        rich=False,
    )
    written.append(orphan)
    notes = dest / "notes.txt"
    notes.write_text(
        "This text file is not audio. A folder scan ignores it.\n",
        encoding="utf-8",
    )
    written.append(notes)
    return written


def _write_pair(folder: Path, spec: "_Spec") -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    left = folder / spec.left_name
    right = folder / spec.right_name
    frames = 4_800
    _write_mono(
        left,
        encoding=spec.encoding,
        rate=spec.rate,
        frequency=spec.left_hz,
        frames=frames,
        side="L",
        stem=spec.stem,
        originator=spec.originator,
        time_reference=spec.time_reference,
        rich=spec.rich,
    )
    _write_mono(
        right,
        encoding=spec.encoding,
        rate=spec.rate,
        frequency=spec.right_hz,
        frames=frames,
        side="R",
        stem=spec.stem,
        originator=spec.originator,
        time_reference=spec.time_reference,
        rich=spec.rich,
    )
    return [left, right]


def _write_mono(
    path: Path,
    *,
    encoding: str,
    rate: int,
    frequency: float,
    frames: int,
    side: str,
    stem: str,
    originator: str,
    time_reference: int,
    rich: bool,
) -> None:
    fmt = make_fmt(encoding, rate, 1)
    audio = _tone(encoding, rate, frequency, frames, pan=0.35 if side == "L" else 0.55)
    bits = fmt.bits_per_sample
    kind = "float" if fmt.is_float else "PCM"
    bext = build_bext(
        description=f"SCG demo {stem} {side}",
        originator=originator,
        originator_reference="SCGSTEREORJ000000000000000000",
        origination_date="2026-11-05",
        origination_time="09:30:00",
        time_reference=time_reference,
        coding_history=f"A={kind},F={rate},W={bits},M=mono,T={originator}\r\n".encode("ascii"),
    )
    after = [Chunk(b"iXML", _ixml(stem, side, rate, bits, kind, time_reference, originator).encode("utf-8"))]
    if rich:
        after.append(build_cue(0))
        after.append(
            build_list_info(
                title=stem,
                artist="SCG",
                comment="Split mono export",
                software=originator,
            )
        )
    chunks = build_wav_chunks(
        fmt,
        before_fmt=[Chunk(b"bext", bext)],
        after_fmt=after,
        frames=frames,
    )
    write_wav(path, fmt=fmt, audio=audio, chunks=chunks)


def _tone(encoding: str, rate: int, frequency: float, frames: int, *, pan: float) -> bytes:
    base = encoding[4:] if encoding.startswith("ext-") else encoding
    bits = {"pcm16": 16, "pcm24": 24, "pcm32": 32, "float32": 32, "float64": 64}[base]
    out = bytearray()
    for index in range(frames):
        sample = math.sin(2 * math.pi * frequency * index / rate) * pan
        out += _pack(sample, base, bits)
    return bytes(out)


def _pack(sample: float, base: str, bits: int) -> bytes:
    clipped = max(-1.0, min(1.0, sample))
    if base == "float32":
        return struct.pack("<f", clipped)
    if base == "float64":
        return struct.pack("<d", clipped)
    peak = (1 << (bits - 1)) - 1
    value = int(round(clipped * peak))
    if bits == 16:
        return struct.pack("<h", value)
    if bits == 32:
        return struct.pack("<i", value)
    if value < 0:
        value += 1 << 24
    return value.to_bytes(3, "little")


def _ixml(stem: str, side: str, rate: int, bits: int, kind: str, time_reference: int, originator: str) -> str:
    function = "LEFT" if side == "L" else "RIGHT"
    index = "1" if side == "L" else "2"
    high = (time_reference >> 32) & 0xFFFFFFFF
    low = time_reference & 0xFFFFFFFF
    depth = bits if kind != "float" else bits
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<BWFXML>
  <IXML_VERSION>1.61</IXML_VERSION>
  <PROJECT>SCG Stereo Rejoin Demo</PROJECT>
  <SCENE>01</SCENE>
  <TAKE>3</TAKE>
  <TAPE>A001</TAPE>
  <CIRCLED>false</CIRCLED>
  <FILE_UID>SCGSTEREOREJOINDEMO00000000000001</FILE_UID>
  <NOTE>Split mono export</NOTE>
  <BWF_ORIGINATOR>{originator}</BWF_ORIGINATOR>
  <SPEED>
    <MASTER_SPEED>{rate} 1/1</MASTER_SPEED>
    <CURRENT_SPEED>{rate} 1/1</CURRENT_SPEED>
    <TIMECODE_RATE>25 1/1</TIMECODE_RATE>
    <TIMECODE_FLAG>NDF</TIMECODE_FLAG>
    <FILE_SAMPLE_RATE>{rate}</FILE_SAMPLE_RATE>
    <AUDIO_BIT_DEPTH>{depth}</AUDIO_BIT_DEPTH>
    <TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_HI>{high}</TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_HI>
    <TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_LO>{low}</TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_LO>
  </SPEED>
  <FILE_SET>
    <TOTAL_FILES>2</TOTAL_FILES>
    <FAMILY_UID>SCGFAMILYDEMO000000000000000001</FAMILY_UID>
    <FAMILY_NAME>{stem}</FAMILY_NAME>
    <FILE_SET_INDEX>{index}</FILE_SET_INDEX>
  </FILE_SET>
  <TRACK_LIST>
    <TRACK_COUNT>1</TRACK_COUNT>
    <TRACK>
      <CHANNEL_INDEX>1</CHANNEL_INDEX>
      <INTERLEAVE_INDEX>1</INTERLEAVE_INDEX>
      <NAME>{stem} {side}</NAME>
      <FUNCTION>{function}</FUNCTION>
    </TRACK>
  </TRACK_LIST>
  <USER>
    <STUDIO>Nightshift</STUDIO>
  </USER>
</BWFXML>
"""


class _Spec:
    def __init__(
        self,
        left_name: str,
        right_name: str,
        stem: str,
        encoding: str,
        rate: int,
        left_hz: float,
        right_hz: float,
        originator: str,
        time_reference: int,
        rich: bool,
    ) -> None:
        self.left_name = left_name
        self.right_name = right_name
        self.stem = stem
        self.encoding = encoding
        self.rate = rate
        self.left_hz = left_hz
        self.right_hz = right_hz
        self.originator = originator
        self.time_reference = time_reference
        self.rich = rich


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write synthetic split-mono WAV examples")
    parser.add_argument("dest", type=Path, nargs="?", default=Path("examples"))
    args = parser.parse_args(argv)
    for path in make_samples(args.dest):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
