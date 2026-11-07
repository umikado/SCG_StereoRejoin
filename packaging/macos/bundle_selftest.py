"""Packaged GUI self-test. Synthetic WAVs live only in a fresh temporary folder."""
from pathlib import Path
import json
import platform
import struct
import sys
import tempfile
import time
import traceback
import wave


def _interleave(left, right, width=2):
    return b''.join(left[i:i + width] + right[i:i + width]
                    for i in range(0, len(left), width))


def run(result_file):
    result = {'status': 'failed', 'checks': [], 'architecture': platform.machine(),
              'python': sys.version, 'frozen': bool(getattr(sys, 'frozen', False))}
    root = None
    try:
        from scg_stereorejoin import __version__
        from scg_stereorejoin.gui import _make_root, StereoRejoinApp, GuiPrefill
        result['version'] = __version__
        root = _make_root()
        root.withdraw()
        result['tk'] = root.tk.call('info', 'patchlevel')
        result['tkdnd'] = root.tk.call('package', 'present', 'tkdnd')
        result['tk_library'] = str(root.tk.call('set', 'tk_library'))
        app = StereoRejoinApp(root, GuiPrefill())
        app.pack(fill='both', expand=True)
        root.update()
        assert not app.delete_var.get() and not app.overwrite_var.get()
        assert app.drop_hint.cget('text') == 'Drop WAV files or a folder onto the list.'
        assert root.tk.call('bind', str(app.file_list), '<<Drop>>')
        result['checks'].append('GUI created; destructive options off; native TkDND loaded and drop target registered')
        with tempfile.TemporaryDirectory(prefix='scg-1.0.2-bundle-selftest-') as directory:
            base = Path(directory)
            left = struct.pack('<5h', -32768, -123, 0, 123, 32767)
            right = struct.pack('<5h', 32767, 50, 0, -50, -32768)
            silence = bytes(len(left))
            cases = [
                ('mono', 1, left, 1, right, left, right),
                ('stereo-single-sided', 2, _interleave(left, silence), 2, _interleave(silence, right), left, right),
                ('stereo-reversed-internal-channels', 2, _interleave(silence, left), 2, _interleave(right, silence), left, right),
                ('mono-left-stereo-right', 1, left, 2, _interleave(right, silence), left, right),
                ('stereo-left-mono-right', 2, _interleave(silence, left), 1, right, left, right),
                ('both-sources-silent', 2, silence * 2, 2, silence * 2, silence, silence),
            ]
            def create_pair(folder, left_channels, left_bytes, right_channels, right_bytes):
                folder.mkdir()
                paths = [folder / 'Synthetic & 合成 take_L.wav', folder / 'Synthetic & 合成 take_R.wav']
                for path, channels, data in zip(paths, (left_channels, right_channels), (left_bytes, right_bytes)):
                    with wave.open(str(path), 'wb') as writer:
                        writer.setparams((channels, 2, 48000, 0, 'NONE', 'not compressed'))
                        writer.writeframes(data)
                return paths
            def select(paths, folder):
                app._clear()
                app.dry_var.set(False)
                class Event:
                    data = ' '.join('{' + str(p) + '}' for p in paths)
                app._on_drop(Event())
                app._on_drop(Event())
                assert app.file_list.size() == 2
                app.output_var.set(str(folder / 'out'))
            def join():
                app._start()
                deadline = time.monotonic() + 15
                while str(app.run_button.cget('state')) == 'disabled':
                    root.update()
                    if time.monotonic() >= deadline:
                        raise AssertionError('GUI worker did not complete within 15 seconds')
                    time.sleep(.01)
                return app.log.get('1.0', 'end')
            result['case_logs'] = {}
            for name, lc, lb, rc, rb, wanted_l, wanted_r in cases:
                folder = base / name
                paths = create_pair(folder, lc, lb, rc, rb)
                before = {p: p.read_bytes() for p in paths}
                select(paths, folder)
                result['case_logs'][name] = join()
                output = folder / 'out' / 'Synthetic & 合成 take.wav'
                with wave.open(str(output), 'rb') as reader:
                    assert reader.getnchannels() == 2
                    assert reader.getsampwidth() == 2
                    assert reader.getframerate() == 48000
                    actual = reader.readframes(reader.getnframes())
                assert actual == _interleave(wanted_l, wanted_r)
                assert all(p.read_bytes() == data for p, data in before.items())
                saved = output.read_bytes()
                rerun = join()
                assert 'refus' in rerun.lower() and output.read_bytes() == saved
                app.output_var.set(str(folder / 'dry-run-output'))
                app.dry_var.set(True)
                dry_log = join()
                assert 'would join' in dry_log
                assert not (folder / 'dry-run-output').exists()
                assert all(p.read_bytes() == data for p, data in before.items())
                result['checks'].append(name + ': GUI bit-exact stereo, sources unchanged, no overwrite, dry run writes nothing')
            folder = base / 'ambiguous-two-active-channels'
            paths = create_pair(folder, 2, _interleave(left, right), 2, _interleave(silence, right))
            before = {p: p.read_bytes() for p in paths}
            select(paths, folder)
            log = join()
            result['case_logs']['ambiguous-refusal'] = log
            assert 'both stereo channels' in log and 'refus' in log.lower()
            assert not (folder / 'out').exists()
            assert all(p.read_bytes() == data for p, data in before.items())
            result['checks'].append('Ambiguous two-active-channel source refused without output or source changes')
            app._clear()
            assert not app.paths and app.file_list.size() == 0
            result['checks'].append('Drop callback preserves Unicode/spaced paths and deduplicates; Clear resets input list')
            # Exercise the same frozen GUI, not a separate Python/Tk installation.
            from scg_stereorejoin.gui_i18n import LANGUAGES, translate, tooltip_text
            from tkinter import ttk
            root.geometry('1050x1030+40+40')
            root.deiconify()
            root.lift()
            root.focus_force()
            def pump(seconds=.08):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    root.update()
                    time.sleep(.005)
            pump(.35)
            result['language_checks'] = {}
            for code, label in LANGUAGES.items():
                app.language_picker.set(label)
                app.language_picker.event_generate('<<ComboboxSelected>>')
                pump()
                assert app.language == code
                assert app.run_button.cget('text') == translate('Rejoin', code)
                assert app.drop_hint.cget('text') == translate('Drop WAV files or a folder onto the list.', code)
                folder = base / ('language-' + code)
                paths = create_pair(folder, 2, _interleave(silence, left), 2, _interleave(right, silence))
                before = {p: p.read_bytes() for p in paths}
                select(paths, folder)
                patterns = app.patterns.get('1.0', 'end-1c')
                log = join()
                output = folder / 'out' / 'Synthetic & 合成 take.wav'
                with wave.open(str(output), 'rb') as reader:
                    assert reader.readframes(reader.getnframes()) == _interleave(left, right)
                assert all(p.read_bytes() == data for p, data in before.items())
                assert all(p.name in log for p in paths)
                assert str(output) in log
                if code != 'en':
                    assert 'Working…' not in log and 'summary joined=' not in log
                result['case_logs']['language-' + code] = log
                for alternate in LANGUAGES:
                    app.set_language(alternate)
                    assert app.paths == paths and app.output_var.get() == str(folder / 'out')
                    assert app.patterns.get('1.0', 'end-1c') == patterns
                    assert all(p.name in app.log.get('1.0', 'end') for p in paths)
                app.set_language(code)
                assert app.log.get('1.0', 'end') == log
                for name, tip in app.tooltips.items():
                    tip.delay = 30
                    # A user may change foreground apps while this test runs.
                    # Refocus and retry once if normal FocusOut hiding cancelled it.
                    for attempt in range(2):
                        root.focus_force()
                        pump(.05)
                        tip.widget.event_generate('<Enter>')
                        pump(.09)
                        if tip.window is not None:
                            break
                    assert tip.window is not None, (code, name, 'tooltip missing')
                    window = tip.window
                    key = 'patterns' if name.startswith('patterns') else name
                    assert window.winfo_children()[0].cget('text') == tooltip_text(key, code)
                    assert window.winfo_rooty() + window.winfo_height() <= tip.widget.winfo_rooty()
                    assert 0 <= window.winfo_rootx() <= window.winfo_screenwidth() - window.winfo_width()
                    tip.widget.event_generate('<Leave>')
                    pump(.02)
                    assert tip.window is None
                observed = {}
                def inspect_dialog():
                    win, title, text, body, runtime = app._dialogs[0]
                    buttons = [w for frame in win.winfo_children() for w in frame.winfo_children()
                               if isinstance(w, ttk.Button)]
                    observed['buttons'] = {w.cget('text') for w in buttons}
                    observed['body'] = text.cget('text')
                    observed['title'] = win.title()
                    buttons[0].invoke()  # No: never authorize source movement in a test.
                root.after(80, inspect_dialog)
                assert not app._dialog('Move source files to trash',
                                       'Add at least one file or folder.', question=True)
                assert observed['buttons'] == {translate('No', code), translate('Yes', code)}
                assert observed['body'] == translate('Add at least one file or folder.', code)
                assert observed['title'] == translate('Move source files to trash', code)
                result['language_checks'][code] = 'passed: selector, labels, dialogs, nine hover targets, live log retranslation, bit-exact synthetic join'
            result['checks'].append('English, Chinese and Japanese packaged GUI interaction passed; audio and source bytes unchanged')
        result['status'] = 'passed'
    except BaseException:
        result['error'] = traceback.format_exc()
    finally:
        if root is not None:
            root.destroy()
        destination = Path(result_file).expanduser().resolve()
        with destination.open('x', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    return 0 if result['status'] == 'passed' else 1
