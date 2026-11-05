# SCG_StereoRejoin

[中文说明](README.zh-CN.md)

SCG_StereoRejoin joins a split dual-mono export back into one interleaved stereo WAV. It is aimed at files from **Pro Tools**, **Cubase**, and **Nuendo**: a left file and a right file, often with BWF (`bext`) and iXML metadata, that should be one stereo clip again.

The samples are copied **byte for byte**. The tool does not resample, dither, or change bit depth. When the result is larger than 4 GB it is written as **RF64** (or **BW64** if you ask). The BWF timestamp is preserved, so the stereo file can re-spot to the original timeline position.

```
Dialogue.L.wav  ─┐
                 ├─►  Dialogue.wav     L R L R L R ...
Dialogue.R.wav  ─┘
```

## Why Python

A single Rust or Go binary is easier to drop on a studio machine that has no toolchain. This project is still Python, for four practical reasons:

1. The hard part is the container, not the math. `bext`, iXML, cue points, LIST/INFO, and the RF64/BW64 size fields have to stay valid. The Python standard library (`struct`, `xml.etree`) makes that behavior easy to test directly.
2. Interleaving is a strided byte copy, and the audio is streamed in chunks. A multi-gigabyte pair does not have to sit in RAM, and the tool does not need a native audio library.
3. There is no required third-party package. The window uses Tk, which ships with the python.org installers on macOS and Windows.
4. The test suite checks pairing, bit-exact samples, metadata, and the mismatch rules. That is the guarantee the join did not convert the audio.

The same code runs on macOS (Apple silicon and Intel), Windows, and Linux. It does not call Core Audio, WASAPI, or any other OS audio API.

## Install

Python 3.10 or newer.

macOS and Linux:

```bash
git clone https://github.com/umikado/SCG_StereoRejoin.git
cd SCG_StereoRejoin
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows (PowerShell):

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
py -3 -m pip install -e .
```

On Debian or Ubuntu the window also needs Tk: `sudo apt install python3-tk`. The python.org installer on macOS and Windows already includes it.

Check the install:

```bash
scg-stereorejoin --help
```

You can skip the install and run from a checkout with `PYTHONPATH=src python -m scg_stereorejoin`.

Optional drag-and-drop onto the window:

```bash
python -m pip install tkinterdnd2
```

The window still works with Add files / Add folder when that package is absent.

## Quick start

The repository includes a small set of split files in `examples/` (24-bit, 16-bit, 32-bit float, several naming styles, one nested folder, and one file with no partner).

```bash
scg-stereorejoin -r -o ./stereo ./examples
```

You get `stereo/Dialogue.wav`, `stereo/Print.wav`, `stereo/Fx.wav`, `stereo/Crowd.wav`, `stereo/Ambience.wav`, and `stereo/session/Boom.wav`. `Orphan.L.wav` is reported and the command still succeeds.

`Dialogue.wav` keeps the left file's BWF time reference, **230400000** samples. At 48 kHz that is **01:20:00.000**. Import it into a 48 kHz session and confirm the spot.

Regenerate the examples if you want a clean copy:

```bash
python -m scg_stereorejoin.samples ./examples
```

Two explicit files, written next to the left file:

```bash
scg-stereorejoin Dialogue.L.wav Dialogue.R.wav
```

## Command line

```text
scg-stereorejoin [options] PATH...
```

`PATH` may be a WAV file or a folder. Repeat it to pass several.

| Flag | Effect |
| --- | --- |
| `-o`, `--output DIR` | Write into this folder. Subfolders are kept when the input was a scanned directory. Omit it and each stereo file is written next to its left source. |
| `-r`, `--recursive` | Enter subfolders. |
| `--pattern LEFT/RIGHT` | Add a suffix pair. Repeat the flag. A leading space is significant, so quote it: `--pattern ' L/ R'`. |
| `--patterns-file FILE` | One `LEFT/RIGHT` pair per line. `#` starts a comment. Do not indent lines; the space in ` L/ R` is part of the pattern. |
| `--no-default-patterns` | Use only the patterns you passed. |
| `--pad` | Lengths differ: extend the shorter side with zero bytes (silence for integer PCM and for float) and warn. |
| `--overwrite` | Replace an output file that is already there. This never replaces an input WAV from the same batch. |
| `--delete-sources` | Move each mono file into `.scg_stereorejoin_trash/` after the output verifies, and only if that source is still the version that was read. The trash copy is kept. |
| `--bw64` | Use a BW64 container instead of RF64 when the output is larger than 4 GB. |
| `-n`, `--dry-run` | Print the plan, including refusals, and write nothing. |
| `--json` | Print a JSON report. The exit code is unchanged. |
| `-v`, `--verbose` | Add sample rate, encoding, frame count, TimeReference, and chunk ids. |
| `-q`, `--quiet` | Warnings, refusals, errors, and the summary line. |
| `--gui` | Open the window. Paths and flags you also passed are filled in. |
| `--version` | Print `SCG_StereoRejoin` and the version. |

Exit code **0** means every pair that could be checked was joined. Unpaired and unmatched names are reported and do not fail the run. Exit code **1** means a pair was refused or a path failed. Exit code **2** means the command line itself is wrong (for example a bad pattern).

A pair is refused, and no stereo file is written, when:

- the sample rate, bit depth, valid bits, or integer/float format differs
- either file is not mono
- the lengths differ and `--pad` was not set
- the output path already exists and `--overwrite` was not set
- two pairs would write the same path
- the output path is any input WAV in this batch, even when `--overwrite` is set
- the data chunk is truncated or the file is not RIFF, RF64, or BW64 WAVE

The whole batch is planned before anything is written, and the rest of the batch continues after a refusal. Each source is parsed and read through one open file handle, so a re-export that replaces the path cannot change the header or the samples that are copied. Each output is written to a uniquely named temporary file in the destination folder, created with an exclusive open so a second run cannot share it and an existing `*.partial` file is left alone. That temporary file is removed if a write fails. Without `--overwrite`, the finished name is published with a hard link that fails if the name already exists, so two runs cannot replace each other. `--overwrite` still replaces the name atomically. Publish, verify, and source removal for one output share an exclusive lock. `--delete-sources` never unlinks a source path. It renames the file into `.scg_stereorejoin_trash/<run-id>/` on the same filesystem, then checks that moved file's inode and audio digest. A match stays in the trash (delete that folder yourself to purge it). A mismatch is linked back onto the original path when that path is free, and otherwise left in the trash, with a warning. If another run replaces the output after this one published it, the sources stay where they are.

## Pairing

Pairs are made **inside one folder**. `reel1/Kick.L.wav` and `reel2/Kick.R.wav` stay unpaired, so two scenes with the same clip name cannot collapse into each other.

Matching is case-insensitive. The output name keeps the left file's casing and extension, with the channel suffix removed. `vox.l.WAV` + `Vox.r.wav` becomes `vox.WAV`.

Built-in suffixes:

| Left | Right | Example | Output |
| --- | --- | --- | --- |
| `.L` | `.R` | `Kick.L.wav` | `Kick.wav` |
| `_L` | `_R` | `Oh_L.wav` | `Oh.wav` |
| `-L` | `-R` | `Hat-L.wav` | `Hat.wav` |
| ` L` | ` R` | `Room L.wav` | `Room.wav` |
| `.1` | `.2` | `Amb.1.wav` | `Amb.wav` |
| `_1` | `_2` | `Fol_1.wav` | `Fol.wav` |
| `Left` | `Right` | `Crowd Left.wav`, `Mic_Left.wav` | `Crowd.wav`, `Mic.wav` |

`Left` / `Right` match a whole token. The suffix must be the entire name, or the character before it must be outside `A–Z`, `a–z`, and `0–9`. That is why `Bright.wav` is not a right channel and `Bleft.wav` is not a left channel. `Mic_Left.wav` and `Mic-Right.wav` both reduce to `Mic` and pair with each other. `Take1.wav` does not match `_1`.

The longest matching suffix wins. Your patterns are tried before the built-in list, so `--pattern .SL/.SR` pairs `Drum.SL.wav` with `Drum.SR.wav` as `Drum.wav` instead of leaving them unmatched. `.SL` does not match the built-in `.L` pattern, because `.L` includes the dot.

`Left.wav` + `Right.wav` have an empty stem after the suffix is removed. The output name is `stereo.wav`.

Files that match one side and lack the other are **unpaired**. WAV names that match no pattern are **unmatched** (an already-joined stereo file in the same folder shows up here). Other extensions are ignored. Hidden files and AppleDouble `._` files are ignored while scanning a folder; a path you pass explicitly is still read.

If several files claim the same stem in one folder (`Song.L.wav`, `Song_L.wav`, and `Song.R.wav`), that group is refused so the wrong partner is not chosen.

## Audio

Supported sample formats, including `WAVE_FORMAT_EXTENSIBLE`:

- 16-bit, 24-bit, and 32-bit integer PCM
- 32-bit and 64-bit IEEE float

Both files have to agree on sample rate, container width, valid bits, and integer versus float. A 32-bit integer file and a 32-bit float file are different formats. Extensible mono files may use different channel masks (front left, front right); the stereo file gets the standard front-left | front-right mask (`0x3`). The sample bytes are still copied, not converted.

`--pad` zero-fills the shorter side. The samples that were already there stay bit-exact. The log says how many silent frames were added, and to which side.

## Metadata and re-spotting

From the **left** file, byte for byte when possible:

- `bext` (description, originator, origination date and time, **TimeReference**, UMID, loudness fields, coding history)
- `cue `
- `LIST` / INFO and any other chunk that is safe to keep

`fmt ` is rewritten for two channels: channel count, block align, and byte rate change. The sample encoding does not. A `fact` chunk, when the format is float or the source already had one, stores the **frame count** (samples per channel), not frames times two.

iXML is parsed and updated in place:

- `TRACK_COUNT` becomes 2
- channel 1 is Left, channel 2 is Right, with `CHANNEL_INDEX` and `INTERLEAVE_INDEX` set to 1 and 2
- the right track's name and extra fields come from the right file's iXML when that document parses
- if the right file has no iXML, the left track is cloned and an obvious left suffix (`.L`, `_Left`, …) is mirrored
- `FILE_SET / TOTAL_FILES` is set to 1 only when it was exactly `2` (this pair). A larger file set is left as it was
- project, scene, take, speed, and `TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_*` stay as they were

If iXML is not valid XML, the original bytes are copied and the log says so. The audio is still joined.

If the left file has no `bext` and the right file has one, the right chunk is used and a warning is printed. If the two TimeReference values differ, the left chunk wins and the log shows both numbers. If neither file has `bext`, the join still works and the log warns that a DAW cannot re-spot it.

Filler chunks (`JUNK`, `FLLR`, `PAD`) are dropped. They are padding, including the BWF placeholder some writers reserve for a future `ds64`.

Pro Tools, Cubase, and Nuendo re-spot from the BWF TimeReference (and Nuendo/Cubase also read the iXML midnight timestamp). Both values come from the source export and are not shifted. A split that was exported without BWF metadata will join, and the DAW will place that file at the cursor rather than at the original timeline position.

## Files larger than 4 GB

A classic RIFF file stores its size in 32 bits, so a file past 4 GB does not fit. When the stereo file would pass that, SCG_StereoRejoin writes **RF64**: the container id is `RF64`, the 32-bit sizes are the sentinel `0xFFFFFFFF`, and a `ds64` chunk stores the real file size, data size, and frame count. `--bw64` writes the same structure with the container id `BW64` (EBU Tech 3306 / ITU-R BS.2088).

Files under the limit stay ordinary `RIFF` / `WAVE`, which older software can open. Audio is streamed, so the process does not need a buffer the size of the output. It does need enough free disk for the stereo file (about the sum of the two monos).

## Window

```bash
scg-stereorejoin --gui
scg-stereorejoin-gui
```

Add files or a folder, pick an output folder (empty means "next to the left file"), edit the pattern list, and press Rejoin. Include subfolders is on by default in the window and off by default on the command line. Delete source files asks for confirmation. The pattern box replaces the built-in list; the defaults are already filled in, including the line that starts with a space.

With `tkinterdnd2` installed, drop files or a folder onto the list.

## Avoid the split at export time

You only need this tool when the session was already exported as dual mono.

**Pro Tools.** In Bounce Mix, and in Export Clips as Files (Export Selected), set the format to **Interleaved**. **Multiple Mono** is the split export. File type should be WAV (BWF) if you want the timestamp to travel with the file.

**Cubase and Nuendo.** File → Export → Audio Mixdown. Set the file type to Wave. Leave **Split Channels** unchecked. If the dialog offers a channel mode instead of a checkbox, choose **Stereo Interleaved** (or Interleaved / Multi Channel Interleaved). Split, Mono Downmix, and Separate Channels write the files this tool is meant to put back together.

A finished stereo export is one file. A split export is a pair whose names differ by `.L`/`.R`, `_L`/`_R`, or `Left`/`Right`.

## Tests

```bash
python -m pip install -e ".[dev]"
pytest
```

The suite builds synthetic mono WAVs (it does not need a DAW) and checks:

- bit-exact interleave for 16/24/32-bit PCM and 32/64-bit float, including a chunk size that does not divide the file
- `bext` bytes, cue, LIST/INFO, and the iXML track list / file set
- pairing, including `Bright` / `Bleft`, custom patterns, and separate folders
- sample-rate, format, and length mismatches, `--pad`, `--overwrite`, and `--delete-sources`
- a forced RF64 and BW64 roundtrip, and the rule that chooses a 64-bit container past 4 GB
- the command line against the example pack

## Layout

```text
src/scg_stereorejoin/   library, CLI, window, example generator
tests/                  pytest suite
examples/               small split-mono files
```

References used for the container and the timestamp: EBU Tech 3285 (BWF `bext`), the iXML specification (track list and file set), and EBU Tech 3306 / ITU-R BS.2088 (RF64 and BW64).
