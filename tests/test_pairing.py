from pathlib import Path

import pytest

from scg_stereorejoin.pairing import (
    PatternError,
    default_patterns,
    default_patterns_text,
    load_patterns,
    match_stem,
    pair_paths,
)


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def names(result):
    return [(item.left.name, item.right.name, item.output_name) for item in result.pairs]


def test_default_conventions(tmp_path: Path):
    pairs = {
        "Kick.L.wav": "Kick.R.wav",
        "Oh_L.wav": "Oh_R.wav",
        "Hat-L.wav": "Hat-R.wav",
        "Room L.wav": "Room R.wav",
        "Amb.1.wav": "Amb.2.wav",
        "Fol_1.wav": "Fol_2.wav",
        "Crowd Left.wav": "Crowd Right.wav",
        "Mic_Left.wav": "Mic-Right.wav",
        "vox.l.WAV": "Vox.r.wav",
    }
    for left, right in pairs.items():
        touch(tmp_path / left)
        touch(tmp_path / right)
    touch(tmp_path / "notes.txt")
    result = pair_paths(sorted(tmp_path.glob("*.wav")) + sorted(tmp_path.glob("*.WAV")), default_patterns())
    got = {(left, right) for left, right, _name in names(result)}
    assert got == set(pairs.items())
    by_left = {left: output for left, _right, output in names(result)}
    assert by_left["Kick.L.wav"] == "Kick.wav"
    assert by_left["Oh_L.wav"] == "Oh.wav"
    assert by_left["Hat-L.wav"] == "Hat.wav"
    assert by_left["Room L.wav"] == "Room.wav"
    assert by_left["Amb.1.wav"] == "Amb.wav"
    assert by_left["Fol_1.wav"] == "Fol.wav"
    assert by_left["Crowd Left.wav"] == "Crowd.wav"
    assert by_left["Mic_Left.wav"] == "Mic.wav"
    assert by_left["vox.l.WAV"] == "vox.WAV"


def test_word_suffix_does_not_eat_bright(tmp_path: Path):
    touch(tmp_path / "Bright.wav")
    touch(tmp_path / "Bleft.wav")
    touch(tmp_path / "Take1.wav")
    touch(tmp_path / "Take2.wav")
    result = pair_paths(sorted(tmp_path.glob("*.wav")), default_patterns())
    assert result.pairs == []
    assert {item.path.name for item in result.unmatched} == {
        "Bright.wav",
        "Bleft.wav",
        "Take1.wav",
        "Take2.wav",
    }


def test_bare_left_right_becomes_stereo(tmp_path: Path):
    touch(tmp_path / "Left.wav")
    touch(tmp_path / "Right.wav")
    result = pair_paths([tmp_path / "Left.wav", tmp_path / "Right.wav"], default_patterns())
    assert names(result) == [("Left.wav", "Right.wav", "stereo.wav")]


def test_missing_partner_and_ambiguous(tmp_path: Path):
    touch(tmp_path / "Only.L.wav")
    touch(tmp_path / "Solo.R.wav")
    touch(tmp_path / "Song.L.wav")
    touch(tmp_path / "Song_L.wav")
    touch(tmp_path / "Song.R.wav")
    result = pair_paths(sorted(tmp_path.glob("*.wav")), default_patterns())
    assert result.pairs == []
    reasons = {item.path.name: item.reason for item in result.unpaired}
    assert reasons["Only.L.wav"] == "missing right partner"
    assert reasons["Solo.R.wav"] == "missing left partner"
    assert len(result.ambiguous) == 1
    assert "Song.L.wav" in result.ambiguous[0].reason
    assert "Song_L.wav" in result.ambiguous[0].reason


def test_pairs_stay_inside_one_folder(tmp_path: Path):
    touch(tmp_path / "a" / "Kick.L.wav")
    touch(tmp_path / "b" / "Kick.R.wav")
    files = [tmp_path / "a" / "Kick.L.wav", tmp_path / "b" / "Kick.R.wav"]
    result = pair_paths(files, default_patterns())
    assert result.pairs == []
    assert len(result.unpaired) == 2


def test_custom_pattern_beats_shorter_default(tmp_path: Path):
    touch(tmp_path / "Drum.SL.wav")
    touch(tmp_path / "Drum.SR.wav")
    untouched = pair_paths(
        [tmp_path / "Drum.SL.wav", tmp_path / "Drum.SR.wav"],
        default_patterns(),
    )
    assert untouched.pairs == []
    patterns = load_patterns([".SL/.SR"], use_defaults=True)
    paired = pair_paths([tmp_path / "Drum.SL.wav", tmp_path / "Drum.SR.wav"], patterns)
    assert names(paired) == [("Drum.SL.wav", "Drum.SR.wav", "Drum.wav")]


def test_patterns_file_keeps_significant_space(tmp_path: Path):
    path = tmp_path / "patterns.txt"
    path.write_text("# comment\n\n" + default_patterns_text(), encoding="utf-8")
    patterns = load_patterns(patterns_file=path, use_defaults=False)
    match = match_stem("Gtr L", patterns)
    assert match is not None
    assert match.side == "L"
    assert match.normalized == "Gtr"
    match = match_stem("Gtr R", patterns)
    assert match is not None and match.side == "R"


def test_bad_pattern_is_an_error():
    with pytest.raises(PatternError):
        load_patterns(["L-R"], use_defaults=False)
    with pytest.raises(PatternError):
        load_patterns(use_defaults=False)


def test_longest_suffix_wins():
    patterns = load_patterns([".Left/.Right"], use_defaults=True)
    match = match_stem("Kick.Left", patterns)
    assert match is not None
    assert match.suffix == ".Left"
    assert match.normalized == "Kick"
    short = match_stem("Kick.L", patterns)
    assert short is not None and short.suffix == ".L"
