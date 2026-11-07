"""Independent event-level localization and hover regression checks."""
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import ttk

import pytest

from scg_stereorejoin.gui import GuiPrefill, StereoRejoinApp, _make_root
from scg_stereorejoin.gui_i18n import LANGUAGES, tooltip_text
from scg_stereorejoin.pairing import default_patterns, match_stem
from scg_stereorejoin.rejoin import BatchReport


def pump(root, seconds=0.04):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.005)


@pytest.fixture
def ui():
    root = _make_root()
    root.geometry('1000x1000+40+40')
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = StereoRejoinApp(root, GuiPrefill(patterns_text=' L/ R\n.L/.R\n# comment\n'))
    app.pack(fill='both', expand=True)
    root.lift()
    root.focus_force()
    pump(root, 0.35)
    yield root, app
    root.destroy()
    assert not errors, errors


def select(root, app, code):
    app.language_picker.set(LANGUAGES[code])
    app.language_picker.event_generate('<<ComboboxSelected>>')
    pump(root)
    assert app.language == code


@pytest.mark.parametrize('code', LANGUAGES)
def test_real_hover_events_delay_position_and_lifecycle(ui, code):
    root, app = ui
    select(root, app, code)
    before = [getattr(app, k + '_var').get() for k in ('recursive','pad','overwrite','delete','bw64','dry')]
    for name, tip in app.tooltips.items():
        widget = tip.widget
        # These event-level checks require an active app, as real focus loss
        # intentionally dismisses hover help. Do not run beside other GUI tests.
        root.focus_force()
        pump(root, 0.1)
        history = []
        started = time.monotonic()
        focus_binding = root.bind('<FocusOut>', lambda e: history.append(('focusout', str(e.widget), str(root.focus_get()), round(time.monotonic() - started, 3))), add='+')
        unmap_binding = root.bind('<Unmap>', lambda e: history.append(('unmap', str(e.widget))), add='+')
        leave_binding = widget.bind('<Leave>', lambda e: history.append(('leave', str(e.widget))), add='+')
        widget.event_generate('<Enter>')
        pump(root, 0.05)
        assert tip.window is None, name
        pump(root, 0.43)
        assert tip.window is not None, (name, history)
        window = tip.window
        assert window.winfo_viewable()
        assert window.winfo_rooty() + window.winfo_height() <= widget.winfo_rooty(), name
        assert 0 <= window.winfo_rootx() <= window.winfo_screenwidth() - window.winfo_width()
        assert 0 <= window.winfo_rooty() <= window.winfo_screenheight() - window.winfo_height()
        assert window.winfo_children()[0].cget('text') == tooltip_text('patterns' if name.startswith('patterns') else name, code)
        widget.event_generate('<Leave>')
        pump(root)
        assert tip.window is None
        widget.event_generate('<Enter>')
        widget.event_generate('<Leave>')
        pump(root, 0.45)
        assert tip.window is None
        root.unbind('<FocusOut>', focus_binding)
        root.unbind('<Unmap>', unmap_binding)
        widget.unbind('<Leave>', leave_binding)
    assert before == [getattr(app, k + '_var').get() for k in ('recursive','pad','overwrite','delete','bw64','dry')]
    tip = app.tooltips['pad']
    tip.widget.event_generate('<Enter>'); pump(root, 0.45)
    tip.widget.event_generate('<ButtonPress-1>'); pump(root)
    assert tip.window is None
    tip.widget.event_generate('<Enter>'); pump(root, 0.45)
    select(root, app, 'ja' if code != 'ja' else 'en')
    assert tip.window is None
    tip.widget.event_generate('<Enter>'); pump(root, 0.45)
    tip.widget.destroy(); pump(root)
    assert tip.window is None and tip.pending is None and not tip.bindings


def test_language_events_preserve_inputs_and_inflight_work(ui, monkeypatch, tmp_path):
    root, app = ui
    import scg_stereorejoin.gui as gui
    source = tmp_path / 'wrote error: 中文 日本語 L.wav'
    app._add_path(source)
    app.output_var.set(str(tmp_path / '出力 wrote'))
    app.pad_var.set(True)
    app.overwrite_var.set(True)
    app.bw64_var.set(True)
    app.dry_var.set(True)
    patterns = app.patterns.get('1.0','end-1c')
    entered, release = threading.Event(), threading.Event()
    captured = {}
    def process(paths, **kwargs):
        captured.update(kwargs); captured['paths'] = paths
        entered.set()
        release.wait(10)
        return BatchReport()
    monkeypatch.setattr(gui, 'process', process)
    app._start()
    assert entered.wait(2)
    try:
        for code in ('zh-CN','ja','en'):
            select(root, app, code)
            assert app.paths == [source]
            assert app.file_list.get(0) == str(source)
            assert app.output_var.get() == str(tmp_path / '出力 wrote')
            assert app.patterns.get('1.0','end-1c') == patterns
            assert app.pad_var.get() and app.overwrite_var.get() and app.bw64_var.get() and app.dry_var.get()
            assert 'disabled' in app.run_button.state()
            assert [p.source for p in captured['patterns']] == [' L/ R','.L/.R']
            assert captured['large_container'] == 'bw64' and captured['dry_run']
        assert 'Working' in app.log.get('1.0','end')
        select(root, app, 'ja')
        assert 'Working' not in app.log.get('1.0','end')
    finally:
        release.set()
    pump(root, 0.3)
    assert 'disabled' not in app.run_button.state()


@pytest.mark.parametrize('code', LANGUAGES)
def test_app_dialog_localized_buttons(ui, code):
    root, app = ui
    select(root, app, code)
    observed = []
    def inspect():
        win, title, label, body, runtime = app._dialogs[0]
        buttons = [w for frame in win.winfo_children() for w in frame.winfo_children() if isinstance(w, ttk.Button)]
        observed.extend(w.cget('text') for w in buttons)
        buttons[0].invoke()
    root.after(40, inspect)
    assert not app._dialog('Move source files to trash', 'Add at least one file or folder.', question=True)
    assert set(observed) == {'en': {'Yes','No'}, 'zh-CN': {'是','否'}, 'ja': {'はい','いいえ'}}[code]


def test_all_documented_pair_examples():
    for left, right in [('Take.L','Take.R'),('Take_L','Take_R'),('Take-L','Take-R'),('Take L','Take R'),('Take.1','Take.2'),('Take_1','Take_2'),('Take_Left','Take_Right')]:
        l, r = match_stem(left, default_patterns()), match_stem(right, default_patterns())
        assert l.side == 'L' and r.side == 'R' and l.normalized == r.normalized
    assert match_stem('Bleft', default_patterns()) is None
    assert match_stem('Bright', default_patterns()) is None


def test_log_rerenders_structured_report_without_translating_filenames(ui, tmp_path):
    from scg_stereorejoin.gui import ReportText
    from scg_stereorejoin.rejoin import process
    from tests.support import pattern_bytes, write_mono
    root, app = ui
    stem = 'wrote no WAV files found 中文 日本語'
    left, right = tmp_path / (stem + '.L.wav'), tmp_path / (stem + '.R.wav')
    write_mono(left, pattern_bytes(2, 4, 1), encoding='pcm16')
    write_mono(right, pattern_bytes(2, 4, 2), encoding='pcm16')
    report = process([left, right], patterns=default_patterns(), output_dir=tmp_path / 'out')
    assert len(report.joined) == 1 and report.ok
    output = report.joined[0].output
    original = output.read_bytes()
    app._write_log('Working…\n')
    app._append_log('wrote ' + str(output) + '\n')
    app._append_log(ReportText(report))
    en = app.log.get('1.0','end-1c')
    for code in ('zh-CN','ja','en'):
        select(root, app, code)
        text = app.log.get('1.0','end-1c')
        assert left.name in text and right.name in text and str(output) in text
        if code == 'en':
            assert text == en
        else:
            assert text != en and 'Working…' not in text
        assert output.read_bytes() == original
