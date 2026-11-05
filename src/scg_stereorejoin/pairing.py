"""Pair split mono filenames into left/right stems.

Matching is case-insensitive. A suffix that starts with a letter or digit
matches only at a token boundary, so ``Bright.wav`` is not a right channel
and ``Bleft.wav`` is not a left channel. Suffixes that already start with a
separator (``.L``, ``_L``, ``-L``, `` L``) match literally.

When several patterns match, the longest suffix wins. User patterns are
tried before the built-in list, so an equal-length custom pattern wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# The conventions named in the brief. ``Left/Right`` is the word form;
# ``.L/.R`` and the other separator forms cover the short suffixes.
DEFAULT_PATTERN_SPECS: tuple[str, ...] = (
    ".L/.R",
    "_L/_R",
    "-L/-R",
    " L/ R",
    ".1/.2",
    "_1/_2",
    "Left/Right",
)

_TRAILING_SEPARATORS = " ._-‐–—"


class PatternError(ValueError):
    """A pairing pattern is missing, empty, or not ``LEFT/RIGHT``."""


@dataclass(frozen=True)
class SuffixPattern:
    left: str
    right: str
    source: str

    @classmethod
    def parse(cls, spec: str) -> SuffixPattern:
        if spec.lstrip().startswith("#") or spec.strip() == "":
            raise PatternError(f"empty pattern {spec!r}")
        if "/" not in spec:
            raise PatternError(f"pattern {spec!r} must look like .L/.R")
        left, right = spec.split("/", 1)
        if left == "" or right == "":
            raise PatternError(f"pattern {spec!r} needs both a left and a right suffix")
        if left.casefold() == right.casefold():
            raise PatternError(f"pattern {spec!r} uses the same suffix for both sides")
        return cls(left=left, right=right, source=spec)


@dataclass(frozen=True)
class SideMatch:
    base: str
    normalized: str
    side: str
    suffix: str

    @property
    def output_stem(self) -> str:
        return self.normalized or "stereo"


@dataclass(frozen=True)
class Pair:
    left: Path
    right: Path
    normalized: str
    output_name: str


@dataclass(frozen=True)
class NamedFile:
    path: Path
    reason: str


@dataclass(frozen=True)
class AmbiguousGroup:
    paths: tuple[Path, ...]
    reason: str


@dataclass
class PairingResult:
    pairs: list[Pair]
    unpaired: list[NamedFile]
    unmatched: list[NamedFile]
    ambiguous: list[AmbiguousGroup]


def default_patterns() -> list[SuffixPattern]:
    return [SuffixPattern.parse(spec) for spec in DEFAULT_PATTERN_SPECS]


def default_patterns_text() -> str:
    return "\n".join(DEFAULT_PATTERN_SPECS) + "\n"


def load_patterns(
    extra: list[str] | None = None,
    *,
    patterns_file: Path | None = None,
    use_defaults: bool = True,
) -> list[SuffixPattern]:
    """User patterns come first so they win ties against the built-in list."""
    patterns: list[SuffixPattern] = []
    for spec in extra or []:
        patterns.append(SuffixPattern.parse(spec))
    if patterns_file is not None:
        try:
            text = patterns_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise PatternError(f"cannot read patterns file {patterns_file}: {exc.strerror}") from exc
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#") or line.strip() == "":
                continue
            try:
                patterns.append(SuffixPattern.parse(line))
            except PatternError as exc:
                raise PatternError(f"{patterns_file}:{line_number}: {exc}") from exc
    if use_defaults:
        patterns.extend(default_patterns())
    if not patterns:
        raise PatternError("no pairing patterns are configured")
    return patterns


def normalized_stem(base: str) -> str:
    """Drop separators left behind by a channel word (``Kick_`` + ``Left``)."""
    return base.rstrip(_TRAILING_SEPARATORS).strip()


def match_stem(stem: str, patterns: list[SuffixPattern]) -> SideMatch | None:
    best_rank: tuple[int, int] | None = None
    best: SideMatch | None = None
    for index, pattern in enumerate(patterns):
        for side, suffix in (("L", pattern.left), ("R", pattern.right)):
            if not _suffix_matches(stem, suffix):
                continue
            rank = (len(suffix), -index)
            if best_rank is not None and rank <= best_rank:
                continue
            base = stem[: len(stem) - len(suffix)]
            best_rank = rank
            best = SideMatch(
                base=base,
                normalized=normalized_stem(base),
                side=side,
                suffix=suffix,
            )
    return best


def output_filename(filename: str, match: SideMatch) -> str:
    suffix = Path(filename).suffix or ".wav"
    stem = match.output_stem.replace("/", "_").replace("\\", "_")
    return f"{stem}{suffix}"


def pair_paths(paths: list[Path], patterns: list[SuffixPattern]) -> PairingResult:
    """Pair files that share a folder and a normalized stem. Order is stable."""
    groups: dict[tuple[Path, str], dict[str, list[tuple[Path, SideMatch]]]] = {}
    unmatched: list[NamedFile] = []
    for path in paths:
        match = match_stem(path.stem, patterns)
        if match is None:
            unmatched.append(NamedFile(path, "name does not match an L/R pattern"))
            continue
        key = (path.parent.resolve(), match.normalized.casefold())
        groups.setdefault(key, {"L": [], "R": []})[match.side].append((path, match))

    pairs: list[Pair] = []
    unpaired: list[NamedFile] = []
    ambiguous: list[AmbiguousGroup] = []
    for sides in groups.values():
        lefts = sides["L"]
        rights = sides["R"]
        if len(lefts) == 1 and len(rights) == 1:
            left_path, left_match = lefts[0]
            right_path, _right_match = rights[0]
            pairs.append(
                Pair(
                    left=left_path,
                    right=right_path,
                    normalized=left_match.normalized,
                    output_name=output_filename(left_path.name, left_match),
                )
            )
            continue
        involved = [item[0] for item in lefts + rights]
        if len(lefts) == 1 and not rights:
            unpaired.append(NamedFile(lefts[0][0], "missing right partner"))
            continue
        if len(rights) == 1 and not lefts:
            unpaired.append(NamedFile(rights[0][0], "missing left partner"))
            continue
        names = ", ".join(path.name for path in involved)
        ambiguous.append(
            AmbiguousGroup(
                paths=tuple(involved),
                reason=f"more than one file claims this stem ({names})",
            )
        )

    pairs.sort(key=lambda item: str(item.left).casefold())
    unpaired.sort(key=lambda item: str(item.path).casefold())
    unmatched.sort(key=lambda item: str(item.path).casefold())
    ambiguous.sort(key=lambda item: str(item.paths[0]).casefold() if item.paths else "")
    return PairingResult(pairs=pairs, unpaired=unpaired, unmatched=unmatched, ambiguous=ambiguous)


def _suffix_matches(stem: str, suffix: str) -> bool:
    if not suffix or len(stem) < len(suffix):
        return False
    if stem[-len(suffix) :].casefold() != suffix.casefold():
        return False
    if len(stem) == len(suffix):
        return True
    if not suffix[0].isalnum():
        return True
    return not stem[-(len(suffix) + 1)].isalnum()
