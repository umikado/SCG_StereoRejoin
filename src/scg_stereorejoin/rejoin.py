"""Join paired mono or single-active-channel WAVs into interleaved stereo."""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from scg_stereorejoin.chunks import bext_time_reference
from scg_stereorejoin.ixml import update_ixml
from scg_stereorejoin.pairing import (
    AmbiguousGroup,
    NamedFile,
    Pair,
    SuffixPattern,
    pair_paths,
)
from scg_stereorejoin.wav import (
    BW64,
    RF64,
    Chunk,
    Fmt,
    SourceView,
    WavError,
    WavInfo,
    build_fact,
    build_fmt,
    container_for,
    container_label,
    hash_region,
    read_wav_handle,
    scan_stereo_channel,
    write_interleaved_wav,
)

WAV_SUFFIXES = {".wav", ".wave"}
_RUN_ID = uuid.uuid4().hex
_SKIP_WHEN_COPYING = {
    b"fmt ",
    b"data",
    b"ds64",
    b"JUNK",
    b"junk",
    b"FLLR",
    b"PAD ",
    b"pad ",
    b"fact",
    b"iXML",
    b"bext",
}


class RejoinError(Exception):
    """The batch itself cannot start (bad paths or patterns)."""


class PairRefused(Exception):
    """One pair was skipped. The rest of the batch still runs."""


@dataclass
class JoinedItem:
    left: Path
    right: Path
    output: Path
    frames: int
    sample_rate: int
    bits_per_sample: int
    encoding: str
    container: str
    time_reference: int | None
    padded_left: int
    padded_right: int
    warnings: list[str]
    chunks: list[str]
    wrote: bool
    post_errors: list[str] = field(default_factory=list)


@dataclass
class RefusedItem:
    left: Path | None
    right: Path | None
    reason: str


@dataclass
class BatchReport:
    joined: list[JoinedItem] = field(default_factory=list)
    unpaired: list[NamedFile] = field(default_factory=list)
    unmatched: list[NamedFile] = field(default_factory=list)
    refused: list[RefusedItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refused and not self.errors


def is_wav(path: Path) -> bool:
    return path.suffix.casefold() in WAV_SUFFIXES


def collect_wavs(inputs: list[Path], *, recursive: bool) -> tuple[list[Path], list[str], list[Path]]:
    """Return wav files, error strings, and the directory roots that were scanned."""
    files: list[Path] = []
    errors: list[str] = []
    roots: list[Path] = []
    seen: set[Path] = set()
    for raw in inputs:
        path = Path(raw)
        if not path.exists():
            errors.append(f"path not found: {path}")
            continue
        if path.is_dir():
            roots.append(path)
            iterator = path.rglob("*") if recursive else path.iterdir()
            for child in iterator:
                if not child.is_file() or not is_wav(child):
                    continue
                try:
                    relative = child.resolve().relative_to(path.resolve())
                except ValueError:
                    relative = Path(child.name)
                if any(part.startswith(".") for part in relative.parts):
                    continue
                resolved = child.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                files.append(child)
            continue
        if not path.is_file():
            errors.append(f"not a file or directory: {path}")
            continue
        if not is_wav(path):
            errors.append(f"not a WAV file: {path}")
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        files.append(path)
    files.sort(key=lambda item: str(item).casefold())
    return files, errors, roots


def destination_for(pair: Pair, output_dir: Path | None, roots: list[Path]) -> Path:
    if output_dir is None:
        return pair.left.parent / pair.output_name
    relative = Path()
    parent = pair.left.parent.resolve()
    for root in roots:
        try:
            relative = parent.relative_to(root.resolve())
            break
        except ValueError:
            continue
    return Path(output_dir) / relative / pair.output_name


def incompatibility(left: Fmt, right: Fmt) -> str | None:
    """Return a reason the two source formats cannot be joined without conversion."""
    problems: list[str] = []
    if left.channels not in (1, 2) or right.channels not in (1, 2):
        if left.channels not in (1, 2):
            problems.append(f"left file has {left.channels} channels; expected mono or single-active-channel stereo")
        if right.channels not in (1, 2):
            problems.append(f"right file has {right.channels} channels; expected mono or single-active-channel stereo")
        return "; ".join(problems)
    if left.sample_rate != right.sample_rate:
        problems.append(
            f"sample rate mismatch ({left.sample_rate} Hz vs {right.sample_rate} Hz); this tool does not resample"
        )
    if left.bits_per_sample != right.bits_per_sample:
        problems.append(
            f"bit depth mismatch ({left.bits_per_sample} vs {right.bits_per_sample}); this tool does not convert bit depth"
        )
    if left.valid_bits != right.valid_bits:
        problems.append(f"valid-bit mismatch ({left.valid_bits} vs {right.valid_bits})")
    if left.format_tag != right.format_tag or left.subformat != right.subformat or left.is_float != right.is_float:
        problems.append(
            f"sample format mismatch ({left.encoding_name} vs {right.encoding_name}); this tool does not convert sample format"
        )
    if left.block_align != left.sample_width * left.channels or right.block_align != right.sample_width * right.channels:
        problems.append(
            "block align does not match the sample width and channel count "
            f"({left.block_align} vs {left.sample_width * left.channels}, "
            f"{right.block_align} vs {right.sample_width * right.channels})"
        )
    if problems:
        return "; ".join(problems)
    return None


def process(
    inputs: list[Path],
    *,
    output_dir: Path | None = None,
    recursive: bool = False,
    patterns: list[SuffixPattern],
    pad: bool = False,
    overwrite: bool = False,
    delete_sources: bool = False,
    dry_run: bool = False,
    large_container: str = "rf64",
    on_message: Callable[[str], None] | None = None,
    chunk_frames: int = 65536,
) -> BatchReport:
    report = BatchReport()
    if large_container not in ("rf64", "bw64"):
        raise RejoinError("large-file container must be rf64 or bw64")
    container_bytes = BW64 if large_container == "bw64" else RF64
    files, errors, roots = collect_wavs(inputs, recursive=recursive)
    report.errors.extend(errors)
    if not files and not errors:
        report.errors.append("no WAV files found")
        return report
    pairing = pair_paths(files, patterns)
    report.unpaired.extend(pairing.unpaired)
    report.unmatched.extend(pairing.unmatched)
    for group in pairing.ambiguous:
        report.refused.append(_refuse_group(group))

    input_keys = {_collision_key(path): path for path in files}
    planned: dict[str, Pair] = {}
    jobs: list[tuple[Pair, Path]] = []
    for pair in pairing.pairs:
        dest = destination_for(pair, output_dir, roots)
        key = _collision_key(dest)
        if key in planned:
            other = planned[key]
            report.refused.append(
                RefusedItem(
                    pair.left,
                    pair.right,
                    f"output path {dest} collides with {other.left.name} + {other.right.name}",
                )
            )
            continue
        if key in input_keys:
            report.refused.append(
                RefusedItem(
                    pair.left,
                    pair.right,
                    f"output path {dest} collides with input {input_keys[key]}",
                )
            )
            continue
        planned[key] = pair
        jobs.append((pair, dest))

    for pair, dest in jobs:
        if on_message:
            on_message(f"joining {pair.left.name} + {pair.right.name}")
        try:
            item = rejoin_pair(
                pair,
                dest,
                pad=pad,
                overwrite=overwrite,
                delete_sources=delete_sources,
                dry_run=dry_run,
                large_container=container_bytes,
                chunk_frames=chunk_frames,
            )
        except PairRefused as exc:
            report.refused.append(RefusedItem(pair.left, pair.right, str(exc)))
            continue
        except (WavError, OSError) as exc:
            report.refused.append(RefusedItem(pair.left, pair.right, str(exc)))
            continue
        report.joined.append(item)
        report.errors.extend(item.post_errors)
        if on_message:
            verb = "would write" if dry_run else "wrote"
            on_message(f"{verb} {item.output}")
            for warning in item.warnings:
                on_message(f"warning {warning}")
            for message in item.post_errors:
                on_message(f"error {message}")
    return report


def rejoin_pair(
    pair: Pair,
    dest: Path,
    *,
    pad: bool,
    overwrite: bool,
    delete_sources: bool,
    dry_run: bool,
    large_container: bytes,
    chunk_frames: int,
) -> JoinedItem:
    if pair.left.resolve() == pair.right.resolve():
        raise PairRefused("left and right paths are the same file")
    try:
        left_fh = pair.left.open("rb", buffering=0)
    except OSError as exc:
        raise PairRefused(f"{pair.left}: {exc.strerror}") from exc
    try:
        try:
            right_fh = pair.right.open("rb", buffering=0)
        except OSError as exc:
            raise PairRefused(f"{pair.right}: {exc.strerror}") from exc
        try:
            try:
                left_stat = os.fstat(left_fh.fileno())
                left_header = _HeaderReader(left_fh)
                left = read_wav_handle(pair.left, left_header, left_stat.st_size)
                right_stat = os.fstat(right_fh.fileno())
                right_header = _HeaderReader(right_fh)
                right = read_wav_handle(pair.right, right_header, right_stat.st_size)
                left_freeze = _freeze_handle(left_fh, left, left_stat, left_header.reads)
                right_freeze = _freeze_handle(right_fh, right, right_stat, right_header.reads)
            except WavError as exc:
                raise PairRefused(str(exc)) from exc
            except OSError as exc:
                raise PairRefused(str(exc)) from exc
            return _rejoin_parsed(
                pair,
                dest,
                left,
                right,
                left_fh,
                right_fh,
                left_freeze,
                right_freeze,
                pad=pad,
                overwrite=overwrite,
                delete_sources=delete_sources,
                dry_run=dry_run,
                large_container=large_container,
                chunk_frames=chunk_frames,
            )
        finally:
            right_fh.close()
    finally:
        left_fh.close()


def _rejoin_parsed(
    pair: Pair,
    dest: Path,
    left: WavInfo,
    right: WavInfo,
    left_fh,
    right_fh,
    left_freeze: "_HandleFreeze",
    right_freeze: "_HandleFreeze",
    *,
    pad: bool,
    overwrite: bool,
    delete_sources: bool,
    dry_run: bool,
    large_container: bytes,
    chunk_frames: int,
) -> JoinedItem:
    reason = incompatibility(left.fmt, right.fmt)
    if reason:
        raise PairRefused(reason)
    if left.data_remainder or right.data_remainder:
        raise PairRefused(
            "audio data size is not a whole number of frames "
            f"(left remainder {left.data_remainder}, right remainder {right.data_remainder})"
        )
    if left.frames != right.frames and not pad:
        raise PairRefused(
            f"length mismatch ({left.frames} vs {right.frames} frames); "
            "re-run with --pad to pad the shorter side with silence"
        )
    dest = Path(dest)
    if dest.resolve() in {pair.left.resolve(), pair.right.resolve()}:
        raise PairRefused(f"output path {dest} is the same as a source file")
    if dest.exists() and not overwrite:
        raise PairRefused(f"output already exists: {dest} (pass --overwrite to replace it)")

    warnings: list[str] = []
    selected = []
    for info, handle, frozen, role, preferred in (
        (left, left_fh, left_freeze, "left", 0),
        (right, right_fh, right_freeze, "right", 1),
    ):
        channel = 0
        if info.fmt.channels == 2:
            channel, silent, digest = scan_stereo_channel(handle, info, preferred=preferred, chunk_frames=chunk_frames)
            _require_handle_unchanged(handle, frozen, info.path, digest)
            detail = "both channels are silent" if silent else "the other channel is exactly silent"
            warnings.append(f"{role} source {info.path.name}: selected internal channel {channel + 1} for output {role.upper()} ({detail})")
        selected.append(channel)
    left_channel, right_channel = selected
    chunks, time_reference = _metadata_chunks(left, right, warnings, left_channel, right_channel)
    padded_left = max(0, right.frames - left.frames)
    padded_right = max(0, left.frames - right.frames)
    if padded_left:
        warnings.append(f"padded the left file with {padded_left} silent frames")
    if padded_right:
        warnings.append(f"padded the right file with {padded_right} silent frames")
    frames = max(left.frames, right.frames)
    chunk_names = [chunk.ident.decode("ascii", errors="replace").rstrip() for chunk in chunks]
    width = left.fmt.sample_width
    chosen = container_for(
        chunks,
        frames * width * 2,
        large_container=large_container,
    )
    if dry_run:
        return _item(
            pair,
            dest,
            left,
            frames=frames,
            time_reference=time_reference,
            padded_left=padded_left,
            padded_right=padded_right,
            warnings=warnings,
            chunks=chunk_names,
            container=container_label(chosen),
            wrote=False,
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = _exclusive_temp(dest)
    lock_fd: int | None = None
    try:
        written = write_interleaved_wav(
            temporary,
            chunks=chunks,
            sample_width=left.fmt.sample_width,
            left_path=left.path,
            left_offset=left.data_offset,
            left_frames=left.frames,
            right_path=right.path,
            right_offset=right.data_offset,
            right_frames=right.frames,
            pad=pad or left.frames != right.frames,
            large_container=large_container,
            chunk_frames=chunk_frames,
            left_handle=left_fh,
            right_handle=right_fh,
            left_channels=left.fmt.channels,
            right_channels=right.fmt.channels,
            left_channel=left_channel,
            right_channel=right_channel,
        )
        _require_handle_unchanged(left_fh, left_freeze, pair.left, written.left.audio_sha256 if written.left else "")
        _require_handle_unchanged(
            right_fh, right_freeze, pair.right, written.right.audio_sha256 if written.right else ""
        )
        identity = _file_identity(temporary)
        lock_fd = _acquire_output_lock(dest)
        _publish(temporary, dest, overwrite=overwrite)
        if temporary.exists():
            temporary.unlink()
        try:
            _verify_published(
                dest,
                identity=identity,
                frames=written.frames,
                sample_rate=left.fmt.sample_rate,
                bits_per_sample=left.fmt.bits_per_sample,
                audio_sha256=written.audio_sha256,
            )
        except (WavError, OSError) as exc:
            raise PairRefused(f"output failed verification: {dest}: {exc}") from exc

        post_errors: list[str] = []
        if delete_sources:
            if _output_still_ours(dest, identity):
                for source, view in ((pair.left, written.left), (pair.right, written.right)):
                    _retire_source(source, view, warnings)
            else:
                warnings.append(
                    f"skipped deleting sources: output {dest} no longer names the file this run published"
                )
        item = _item(
            pair,
            dest,
            left,
            frames=written.frames,
            time_reference=time_reference,
            padded_left=padded_left,
            padded_right=padded_right,
            warnings=warnings,
            chunks=chunk_names,
            container=container_label(written.container),
            wrote=True,
        )
        item.post_errors = post_errors
        return item
    finally:
        if temporary.exists():
            temporary.unlink()
        if lock_fd is not None:
            _release_output_lock(lock_fd)


def format_report(report: BatchReport, *, verbose: bool = False, quiet: bool = False) -> str:
    lines: list[str] = []
    if not quiet:
        for item in report.joined:
            verb = "would join" if not item.wrote else "joined"
            lines.append(f"{verb}  {item.left.name} + {item.right.name} -> {item.output}")
            if verbose:
                lines.append(
                    f"        {item.sample_rate} Hz, {item.encoding}, {item.frames} frames, {item.container}"
                )
                if item.time_reference is not None:
                    lines.append(f"        TimeReference {item.time_reference} samples")
                if item.chunks:
                    lines.append("        chunks: " + ", ".join(item.chunks))
            for warning in item.warnings:
                lines.append(f"warning {item.output.name}: {warning}")
        for item in report.unpaired:
            lines.append(f"unpaired {item.path}: {item.reason}")
        for item in report.unmatched:
            lines.append(f"unmatched {item.path}: {item.reason}")
    else:
        for item in report.joined:
            for warning in item.warnings:
                lines.append(f"warning {item.output.name}: {warning}")
    for item in report.refused:
        left = item.left.name if item.left else "?"
        right = item.right.name if item.right else "?"
        lines.append(f"refused {left} + {right}: {item.reason}")
    for message in report.errors:
        lines.append(f"error   {message}")
    lines.append(
        "summary "
        f"joined={len(report.joined)} unpaired={len(report.unpaired)} "
        f"unmatched={len(report.unmatched)} refused={len(report.refused)} "
        f"errors={len(report.errors)}"
    )
    return "\n".join(lines)


def report_json(report: BatchReport, *, version: str) -> dict:
    def named(item: NamedFile) -> dict:
        return {"path": str(item.path), "reason": item.reason}

    return {
        "tool": "SCG_StereoRejoin",
        "version": version,
        "joined": [
            {
                "left": str(item.left),
                "right": str(item.right),
                "output": str(item.output),
                "frames": item.frames,
                "sample_rate": item.sample_rate,
                "bits_per_sample": item.bits_per_sample,
                "encoding": item.encoding,
                "container": item.container,
                "time_reference": item.time_reference,
                "padded_left_frames": item.padded_left,
                "padded_right_frames": item.padded_right,
                "warnings": item.warnings,
                "chunks": item.chunks,
                "wrote": item.wrote,
            }
            for item in report.joined
        ],
        "unpaired": [named(item) for item in report.unpaired],
        "unmatched": [named(item) for item in report.unmatched],
        "refused": [
            {
                "left": str(item.left) if item.left else None,
                "right": str(item.right) if item.right else None,
                "reason": item.reason,
            }
            for item in report.refused
        ],
        "errors": list(report.errors),
    }


def _metadata_chunks(left: WavInfo, right: WavInfo, warnings: list[str], left_channel: int = 0, right_channel: int = 0) -> tuple[list[Chunk], int | None]:
    bext = left.chunk(b"bext")
    right_bext = right.chunk(b"bext")
    if bext is None and right_bext is not None:
        bext = right_bext
        warnings.append("left file has no bext chunk; copied bext from the right file")
    elif bext is None:
        warnings.append("no bext chunk; a DAW cannot re-spot this file to a BWF timestamp")
    else:
        left_time = bext_time_reference(bext.data)
        right_time = bext_time_reference(right_bext.data) if right_bext else None
        if right_time is not None and left_time is not None and right_time != left_time:
            warnings.append(
                f"BWF TimeReference differs (L={left_time}, R={right_time}); "
                "the stereo file keeps the left file's bext chunk"
            )
    time_reference = bext_time_reference(bext.data) if bext else None

    ixml_chunk = left.chunk(b"iXML")
    ixml_from_right = False
    if ixml_chunk is None and right.chunk(b"iXML") is not None:
        ixml_chunk = right.chunk(b"iXML")
        ixml_from_right = True
        warnings.append("left file has no iXML chunk; updated the right file's iXML instead")
    updated_ixml: bytes | None = None
    if ixml_chunk is not None:
        right_xml = None if ixml_from_right else (right.chunk(b"iXML").data if right.chunk(b"iXML") else None)
        result = update_ixml(
            ixml_chunk.data, right_xml,
            left_channel=left_channel if left.fmt.channels == 2 and not ixml_from_right else None,
            right_channel=right_channel if right.fmt.channels == 2 else None,
            base_from_right=ixml_from_right and right.fmt.channels == 2,
        )
        updated_ixml = result.data
        warnings.extend(result.warnings)

    stereo = left.fmt.as_stereo()
    frames = max(left.frames, right.frames)
    source_fact = left.chunk(b"fact") or right.chunk(b"fact")
    chunks: list[Chunk] = []
    if bext is not None:
        chunks.append(Chunk(b"bext", bext.data))
    chunks.append(Chunk(b"fmt ", build_fmt(stereo)))
    if stereo.is_float or source_fact is not None:
        chunks.append(Chunk(b"fact", build_fact(frames)))
    if updated_ixml is not None:
        chunks.append(Chunk(b"iXML", updated_ixml))
    for chunk in left.chunks:
        if chunk.ident in _SKIP_WHEN_COPYING:
            continue
        chunks.append(Chunk(chunk.ident, chunk.data))
    return chunks, time_reference


def _item(
    pair: Pair,
    dest: Path,
    left: WavInfo,
    *,
    frames: int,
    time_reference: int | None,
    padded_left: int,
    padded_right: int,
    warnings: list[str],
    chunks: list[str],
    container: str,
    wrote: bool,
) -> JoinedItem:
    return JoinedItem(
        left=pair.left,
        right=pair.right,
        output=dest,
        frames=frames,
        sample_rate=left.fmt.sample_rate,
        bits_per_sample=left.fmt.bits_per_sample,
        encoding=left.fmt.as_stereo().encoding_name,
        container=container,
        time_reference=time_reference,
        padded_left=padded_left,
        padded_right=padded_right,
        warnings=warnings,
        chunks=chunks,
        wrote=wrote,
    )


def _refuse_group(group: AmbiguousGroup) -> RefusedItem:
    left = group.paths[0] if group.paths else None
    right = group.paths[1] if len(group.paths) > 1 else None
    return RefusedItem(left, right, group.reason)


def _exclusive_temp(dest: Path) -> Path:
    """Create a unique temporary file in the destination directory.

    ``O_EXCL`` means a concurrent join cannot open the same path, and a
    pre-existing ``*.partial`` file is never reused.
    """
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    parent = dest.parent
    for _ in range(128):
        candidate = parent / f".{dest.name}.{os.urandom(8).hex()}.partial"
        try:
            fd = os.open(candidate, flags, 0o666)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate
    raise PairRefused(f"could not create a temporary file in {parent}")


def _acquire_output_lock(dest: Path) -> int:
    """Block other runs that publish or retire sources for this output path."""
    lock_path = dest.parent / f".{dest.name}.scg-lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _release_output_lock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _output_still_ours(dest: Path, identity: tuple[int, int]) -> bool:
    try:
        st = dest.stat()
    except OSError:
        return False
    return (st.st_dev, st.st_ino) == identity


@dataclass(frozen=True)
class _HandleFreeze:
    """Stat, header bytes, and audio digest from the handle that was parsed."""

    dev: int
    ino: int
    size: int
    mtime_ns: int
    ctime_ns: int
    header_reads: tuple[tuple[int, bytes], ...]
    audio_sha256: str


class _HeaderReader:
    """Record the exact bytes consumed by the WAV parser, excluding skipped audio."""

    def __init__(self, handle):
        self.handle = handle
        self.reads: list[tuple[int, bytes]] = []

    def read(self, count: int = -1) -> bytes:
        offset = self.handle.tell()
        data = self.handle.read(count)
        self.reads.append((offset, data))
        return data

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self.handle.seek(offset, whence)

    def tell(self) -> int:
        return self.handle.tell()


def _ctime_ns(stat) -> int:
    value = getattr(stat, "st_ctime_ns", None)
    if value is not None:
        return int(value)
    return int(stat.st_ctime * 1_000_000_000)


def _require_parse_state(initial, current, path: Path) -> None:
    """Keep the state from before parsing rather than accepting a later rewrite.

    Replacing the source path may unlink the open, unchanged inode and update
    only its ctime. Its original header and audio remain usable; retirement
    will separately reject the new inode at the source path.
    """
    before = (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns)
    after = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if before == after:
        if _ctime_ns(initial) == _ctime_ns(current):
            return
        if current.st_nlink < initial.st_nlink:
            try:
                named = path.stat()
            except FileNotFoundError:
                return
            if (named.st_dev, named.st_ino) != (current.st_dev, current.st_ino):
                return
    raise PairRefused(f"{path} changed while it was being read")


def _require_header_reads(handle, reads: tuple[tuple[int, bytes], ...], path: Path) -> None:
    position = handle.tell()
    try:
        for offset, expected in reads:
            handle.seek(offset)
            if handle.read(len(expected)) != expected:
                raise PairRefused(f"{path} changed while it was being read")
    finally:
        handle.seek(position)


def _freeze_handle(handle, info: WavInfo, initial_stat, parsed_reads: list[tuple[int, bytes]]) -> _HandleFreeze:
    # Source handles are unbuffered so rereading a range checks current bytes,
    # not a parser read-ahead buffer retained across an in-place rewrite.
    stat = os.fstat(handle.fileno())
    _require_parse_state(initial_stat, stat, info.path)
    header_reads = tuple(parsed_reads)
    position = handle.tell()
    try:
        _require_header_reads(handle, header_reads, info.path)
        audio_sha256 = hash_region(handle, info.data_offset, info.data_size)
        _require_header_reads(handle, header_reads, info.path)
        final_stat = os.fstat(handle.fileno())
        _require_parse_state(initial_stat, final_stat, info.path)
    finally:
        handle.seek(position)
    return _HandleFreeze(
        dev=final_stat.st_dev,
        ino=final_stat.st_ino,
        size=final_stat.st_size,
        mtime_ns=final_stat.st_mtime_ns,
        ctime_ns=_ctime_ns(final_stat),
        header_reads=header_reads,
        audio_sha256=audio_sha256,
    )


def _require_handle_unchanged(handle, frozen: _HandleFreeze, path: Path, streamed_audio_sha256: str) -> None:
    """Abort when the open inode, its header, or its samples changed after the parse.

    ``mtime_ns`` and ``ctime_ns`` can stay put when a same-sized rewrite lands
    inside one timestamp tick and ``utime`` is then asked to store the times
    the inode already has. The audio digest catches that case.
    """
    stat = os.fstat(handle.fileno())
    now = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, _ctime_ns(stat))
    was = (frozen.dev, frozen.ino, frozen.size, frozen.mtime_ns, frozen.ctime_ns)
    _require_header_reads(handle, frozen.header_reads, path)
    final_stat = os.fstat(handle.fileno())
    final = (final_stat.st_dev, final_stat.st_ino, final_stat.st_size, final_stat.st_mtime_ns, _ctime_ns(final_stat))
    if now != was or final != was or streamed_audio_sha256 != frozen.audio_sha256:
        raise PairRefused(f"{path} changed while it was being read")


def _exclusive_trash_destination(trash_dir: Path, source_name: str) -> Path:
    """Return a path that does not exist, inside a directory created with mkdir.

    ``os.rename`` onto an existing file replaces it on POSIX. A fresh directory
    from ``os.mkdir`` cannot already contain ``source_name``, and a collision
    on the directory name is retried instead of overwritten.
    """
    trash_dir.mkdir(parents=True, exist_ok=True)
    for attempt in range(128):
        folder = trash_dir / f"{os.urandom(4).hex()}-{attempt}"
        try:
            os.mkdir(folder)
        except FileExistsError:
            continue
        return folder / source_name
    raise OSError(17, "could not create a trash directory")


def _retire_source(source: Path, view: SourceView | None, warnings: list[str]) -> None:
    """Move ``source`` aside, then keep it only if it is still the file we read.

    The original path is never unlinked. A mismatch is linked back when the
    path is free, and otherwise left in the trash directory.
    """
    if view is None:
        warnings.append(f"skipped deleting {source}: file changed after it was read")
        return
    trash_dir = source.parent / ".scg_stereorejoin_trash" / _RUN_ID
    trash: Path | None = None
    try:
        trash = _exclusive_trash_destination(trash_dir, source.name)
        os.rename(source, trash)
    except OSError as exc:
        if trash is not None and trash.parent.is_dir() and not any(trash.parent.iterdir()):
            try:
                trash.parent.rmdir()
            except OSError:
                pass
        warnings.append(f"skipped deleting {source}: {exc.strerror}")
        return
    if _quarantine_matches(trash, view):
        warnings.append(f"moved {source.name} to {trash}")
        return
    try:
        os.link(trash, source)
    except FileExistsError:
        warnings.append(f"skipped deleting {source}: quarantined changed file at {trash}")
        return
    except OSError as exc:
        warnings.append(f"skipped deleting {source}: left changed file at {trash} ({exc.strerror})")
        return
    warnings.append(f"skipped deleting {source}: file changed after it was read")


def _quarantine_matches(path: Path, view: SourceView) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != (
            view.dev,
            view.ino,
            view.size,
            view.mtime_ns,
        ):
            return False
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            digest = hash_region(handle, view.offset, view.audio_bytes)
        return digest == view.audio_sha256
    except (OSError, WavError):
        return False
    finally:
        if fd >= 0:
            os.close(fd)


def _file_identity(path: Path) -> tuple[int, int]:
    st = path.stat()
    return (st.st_dev, st.st_ino)


def _publish(temporary: Path, dest: Path, *, overwrite: bool) -> None:
    """Make ``dest`` name the finished file.

    Without ``overwrite``, ``os.link`` is the publish. It fails with
    ``EEXIST`` when the name is already taken, including when another run
    wins the race, on POSIX and on Windows. ``os.replace`` is only used
    when replacement was requested, because on POSIX it overwrites.
    """
    if overwrite:
        os.replace(temporary, dest)
        return
    try:
        os.link(temporary, dest)
    except FileExistsError as exc:
        raise PairRefused(f"output already exists: {dest} (pass --overwrite to replace it)") from exc


def _verify_published(
    path: Path,
    *,
    identity: tuple[int, int],
    frames: int,
    sample_rate: int,
    bits_per_sample: int,
    audio_sha256: str,
) -> None:
    """Re-read the published inode, not whatever later appears at ``path``."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as exc:
        raise WavError(f"{path}: {exc.strerror}") from exc
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != identity:
            raise WavError(f"{path}: published file is not the file this run wrote")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            info = read_wav_handle(path, handle, st.st_size)
            problems: list[str] = []
            if info.fmt.channels != 2:
                problems.append(f"{info.fmt.channels} channels, expected 2")
            if info.frames != frames:
                problems.append(f"{info.frames} frames, expected {frames}")
            if info.fmt.sample_rate != sample_rate:
                problems.append(f"{info.fmt.sample_rate} Hz, expected {sample_rate}")
            if info.fmt.bits_per_sample != bits_per_sample:
                problems.append(f"{info.fmt.bits_per_sample} bits, expected {bits_per_sample}")
            if problems:
                raise WavError(f"{path}: " + "; ".join(problems))
            digest = hash_region(handle, info.data_offset, info.data_size)
            if digest != audio_sha256:
                raise WavError(f"{path}: audio bytes do not match the source files")
    finally:
        if fd >= 0:
            os.close(fd)


def _collision_key(path: Path) -> str:
    text = str(path.resolve())
    if os.name == "nt" or sys.platform == "darwin":
        return text.casefold()
    return text
