import json
import subprocess
import sys
from pathlib import Path

from scg_stereorejoin.samples import make_samples
from tests.support import pattern_bytes, write_mono

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scg_stereorejoin", *args],
        cwd=cwd,
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_help_and_version():
    help_run = run(["--help"], ROOT)
    assert help_run.returncode == 0
    assert "Interleaved" not in help_run.stdout or "stereo" in help_run.stdout.lower()
    assert "--pad" in help_run.stdout
    assert "--delete-sources" in help_run.stdout
    version = run(["--version"], ROOT)
    assert version.returncode == 0
    assert "SCG_StereoRejoin" in version.stdout


def test_cli_joins_examples_and_reports_the_orphan(tmp_path: Path):
    make_samples(tmp_path / "examples")
    output = tmp_path / "stereo"
    result = run(["-r", "-o", str(output), "-v", str(tmp_path / "examples")], tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "joined  Dialogue.L.wav + Dialogue.R.wav" in result.stdout
    assert "TimeReference 230400000" in result.stdout
    assert "unpaired" in result.stdout
    assert "Orphan.L.wav" in result.stdout
    assert "summary joined=6" in result.stdout
    assert (output / "Dialogue.wav").is_file()
    assert (output / "session" / "Boom.wav").is_file()
    second = run(["-r", "-o", str(output), str(tmp_path / "examples")], tmp_path)
    assert second.returncode == 1
    assert "already exists" in second.stdout


def test_cli_json_and_mismatch_exit_code(tmp_path: Path):
    write_mono(tmp_path / "A.L.wav", pattern_bytes(2, 4, 1), encoding="pcm16", rate=48_000)
    write_mono(tmp_path / "A.R.wav", pattern_bytes(2, 4, 1), encoding="pcm16", rate=44_100)
    result = run(["--json", "-o", str(tmp_path / "out"), str(tmp_path)], tmp_path)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["tool"] == "SCG_StereoRejoin"
    assert payload["joined"] == []
    assert "sample rate mismatch" in payload["refused"][0]["reason"]
    assert "joined" not in result.stderr


def test_cli_custom_pattern_file(tmp_path: Path):
    write_mono(tmp_path / "Drum.SL.wav", pattern_bytes(2, 2, 1), encoding="pcm16")
    write_mono(tmp_path / "Drum.SR.wav", pattern_bytes(2, 2, 2), encoding="pcm16")
    patterns = tmp_path / "patterns.txt"
    patterns.write_text("# recorder\n.SL/.SR\n", encoding="utf-8")
    result = run(
        ["--no-default-patterns", "--patterns-file", str(patterns), "-o", str(tmp_path / "out"), str(tmp_path)],
        tmp_path,
    )
    assert result.returncode == 0, result.stdout
    assert (tmp_path / "out" / "Drum.wav").is_file()


def test_cli_bad_pattern_exits_2(tmp_path: Path):
    result = run(["--pattern", "not-a-pair", str(tmp_path)], tmp_path)
    assert result.returncode == 2
    assert "pattern" in result.stderr.lower()


def test_missing_path_is_an_error_and_other_pairs_still_join(tmp_path: Path):
    write_mono(tmp_path / "A.L.wav", pattern_bytes(2, 2, 1), encoding="pcm16")
    write_mono(tmp_path / "A.R.wav", pattern_bytes(2, 2, 2), encoding="pcm16")
    result = run(
        ["-o", str(tmp_path / "out"), str(tmp_path / "A.L.wav"), str(tmp_path / "A.R.wav"), str(tmp_path / "nope.wav")],
        tmp_path,
    )
    assert result.returncode == 1
    assert (tmp_path / "out" / "A.wav").is_file()
    assert "not found" in result.stdout
