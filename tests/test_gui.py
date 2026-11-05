from pathlib import Path

import pytest

from scg_stereorejoin.gui import GuiPrefill, parse_drop_paths
from scg_stereorejoin.pairing import default_patterns
from tests.support import pattern_bytes, write_mono


def test_parse_drop_paths_handles_spaces_and_plain_paths():
    payload = "{/Library/Audio/Take L.wav} {/Library/Audio/Take R.wav} /tmp/plain.L.wav"
    assert parse_drop_paths(payload) == [
        "/Library/Audio/Take L.wav",
        "/Library/Audio/Take R.wav",
        "/tmp/plain.L.wav",
    ]
    assert parse_drop_paths("") == []


def test_window_builds_without_entering_mainloop():
    pytest.importorskip("tkinter")
    import tkinter as tk

    from scg_stereorejoin.gui import StereoRejoinApp

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    app = StereoRejoinApp(
        root,
        GuiPrefill(paths=[Path("/tmp/Dialogue.L.wav")], patterns_text=".L/.R\n_L/_R\n"),
    )
    assert app.file_list.size() == 1
    assert ".L/.R" in app.patterns.get("1.0", "end")
    app._patterns()
    root.destroy()


def test_gui_join_writes_the_stereo_file(tmp_path: Path):
    pytest.importorskip("tkinter")
    import tkinter as tk

    from scg_stereorejoin.gui import StereoRejoinApp

    write_mono(tmp_path / "Hat.L.wav", pattern_bytes(2, 4, 1), encoding="pcm16")
    write_mono(tmp_path / "Hat.R.wav", pattern_bytes(2, 4, 2), encoding="pcm16")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    app = StereoRejoinApp(root, GuiPrefill(patterns_text=".L/.R\n"))
    app._join(
        [tmp_path],
        default_patterns(),
        str(tmp_path / "out"),
        {
            "recursive": False,
            "pad": False,
            "overwrite": False,
            "delete_sources": False,
            "dry_run": False,
            "large_container": "rf64",
        },
    )
    finished = None
    while not app.events.empty():
        kind, payload = app.events.get_nowait()
        if kind == "done":
            finished = str(payload)
    root.destroy()
    assert finished is not None
    assert "joined" in finished
    assert (tmp_path / "out" / "Hat.wav").is_file()
