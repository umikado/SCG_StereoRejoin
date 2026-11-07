"""Synthetic GUI-only checks; no personal files, settings, or audio devices."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import pytest

from scg_stereorejoin.gui import GuiPrefill, StereoRejoinApp, ReportText
from scg_stereorejoin.gui_i18n import LANGUAGES, TRANSLATIONS, TOOLTIPS, tooltip_text
from scg_stereorejoin.gui_messages import format_gui_report
from scg_stereorejoin.pairing import default_patterns
from scg_stereorejoin.rejoin import process
from tests.support import pattern_bytes, write_mono


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    widget = StereoRejoinApp(root, GuiPrefill(paths=[Path('/tmp/日本語 Left.wav')], output='/tmp/中文 out',
                                             pad=True, patterns_text=' L/ R\n.L/.R\n'))
    widget.pack(fill='both', expand=True)
    yield widget
    root.destroy()


def test_catalogues_have_three_languages_and_precise_help():
    assert list(LANGUAGES.values()) == ['English', '简体中文', '日本語']
    assert all(len(values) == 2 and all(values) for values in TRANSLATIONS.values())
    assert all(len(values) == 3 and all(values) for values in TOOLTIPS.values())
    for language in LANGUAGES:
        text = tooltip_text('patterns', language)
        for literal in ('.L/.R', '_L/_R', '-L/-R', ' L/ R', '.1/.2', '_1/_2', 'Left/Right', 'Bleft/Bright'):
            assert literal in text
        assert '.scg_stereorejoin_trash' in tooltip_text('delete', language)
        assert 'macOS' in tooltip_text('delete', language)
        assert 'RF64' in tooltip_text('bw64', language)
        assert 'RIFF WAV' in tooltip_text('bw64', language)


def test_switch_preserves_every_input_and_running_state(app):
    paths = list(app.paths)
    patterns = app.patterns.get('1.0', 'end')
    app.run_button.configure(state='disabled')
    options = [app.recursive_var, app.pad_var, app.overwrite_var, app.delete_var, app.bw64_var, app.dry_var]
    values = [var.get() for var in options]
    for language, run_label in [('zh-CN', '合并'), ('ja', '結合'), ('en', 'Rejoin')]:
        app.set_language(language)
        assert app.language == language
        assert app.run_button.cget('text') == run_label
        assert str(app.run_button.cget('state')) == 'disabled'
        assert app.paths == paths
        assert app.output_var.get() == '/tmp/中文 out'
        assert app.patterns.get('1.0', 'end') == patterns
        assert [var.get() for var in options] == values
        assert all(tip.text() == tooltip_text('patterns' if name.startswith('patterns') else name, language)
                   for name, tip in app.tooltips.items())
    assert len(app.tooltips) == 9
    with pytest.raises(ValueError):
        app.set_language('unknown')


def test_report_relocalizes_without_modifying_paths(app, tmp_path):
    for side in ('L', 'R'):
        write_mono(tmp_path / f'joined 日本語.{side}.wav', pattern_bytes(2, 4, 1), encoding='pcm16')
    report = process([tmp_path], output_dir=tmp_path / 'out', dry_run=True, patterns=default_patterns())
    payload = ReportText(report)
    assert isinstance(payload, str)
    app.events.put(('done', payload))
    app._drain()
    for language in LANGUAGES:
        app.set_language(language)
        assert app.log.get('1.0', 'end-1c') == format_gui_report(report, language, verbose=True) + '\n'
        assert str(tmp_path / 'out' / 'joined 日本語.wav') in app.log.get('1.0', 'end')
    assert not (tmp_path / 'out').exists()


def test_queued_progress_uses_current_language(app):
    app._write_log('Working…\n')
    app.set_language('ja')
    assert 'Working' not in app.log.get('1.0', 'end')
    app.events.put(('done', 'error: no pairing patterns are configured\n'))
    app.set_language('zh-CN')
    app._drain()
    assert str(app.run_button.cget('state')) == 'normal'
    assert 'no pairing patterns' not in app.log.get('1.0', 'end')
    app.set_language('en')
    assert 'Working…' in app.log.get('1.0', 'end')
    assert 'no pairing patterns are configured' in app.log.get('1.0', 'end')


def test_tooltip_cancellation_switch_and_destroy(app):
    tip = app.tooltips['pad']
    assert tip.delay == 400
    tip.schedule()
    assert tip.pending is not None
    tip.hide()
    assert tip.pending is None
    tip.schedule()
    app.set_language('ja')
    assert tip.pending is None
    tip.schedule()
    tip.widget.destroy()
    assert tip.pending is None
    assert tip.bindings == []


def test_tooltip_position_above_widget_and_nonfocusable(app):
    root = app.winfo_toplevel()
    root.geometry('+50+100')
    root.deiconify()
    root.update()
    tip = app.tooltips['dry']
    tip.show()
    root.update_idletasks()
    assert tip.window is not None
    assert str(tip.window.cget('takefocus')) in ('0', 'False')
    assert tip.window.winfo_y() + tip.window.winfo_height() <= tip.widget.winfo_rooty()
    assert tip.window.winfo_x() >= 0
    assert tip.window.winfo_x() + tip.window.winfo_width() <= root.winfo_screenwidth()
    tip.widget.event_generate('<ButtonPress-1>')
    assert tip.window is None


def test_dialog_labels_switch_and_cancel_without_processing(app):
    seen = []
    def inspect_and_close():
        app.set_language('zh-CN')
        window, title, label, body, runtime = app._dialogs[0]
        assert window.title() == '配对规则'
        assert '至少' in label.cget('text')
        buttons = [w for child in window.winfo_children() for w in child.winfo_children() if isinstance(w, ttk.Button)]
        seen.extend(button.cget('text') for button in buttons)
        next(button for button in buttons if button.cget('text') == '否').invoke()
    app.after(20, inspect_and_close)
    assert app._dialog('Patterns', 'Add at least one file or folder.', question=True) is False
    assert set(seen) == {'是', '否'}
    assert not app._dialogs
    app.set_language('ja')  # Destroyed dialog labels must not leave stale callbacks.
