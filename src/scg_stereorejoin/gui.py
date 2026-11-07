"""A small desktop window for SCG_StereoRejoin.

Add files or a folder with the buttons. If the optional ``tkinterdnd2``
package is installed, the file list also accepts a drag from Finder,
Explorer, or the file manager.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, ttk

from scg_stereorejoin import __version__
from scg_stereorejoin.gui_i18n import LANGUAGES, translate, tooltip_text
from scg_stereorejoin.gui_tooltips import HoverTip
from scg_stereorejoin.gui_messages import translate_message, format_gui_report
from scg_stereorejoin.pairing import PatternError, default_patterns_text, load_patterns
from scg_stereorejoin.rejoin import RejoinError, format_report, process


@dataclass
class GuiPrefill:
    paths: list[Path] = field(default_factory=list)
    output: str = ""
    recursive: bool = True
    pad: bool = False
    overwrite: bool = False
    delete_sources: bool = False
    bw64: bool = False
    dry_run: bool = False
    patterns_text: str = ""


def parse_drop_paths(data: str) -> list[str]:
    """Split a tkinterdnd2 drop payload into paths.

    Paths that contain spaces arrive wrapped in braces. Other paths are
    separated by spaces.
    """
    paths: list[str] = []
    buffer: list[str] = []
    braced = False
    for char in data.strip():
        if char == "{" and not braced and not buffer:
            braced = True
            continue
        if char == "}" and braced:
            paths.append("".join(buffer))
            buffer = []
            braced = False
            continue
        if char == " " and not braced:
            if buffer:
                paths.append("".join(buffer))
                buffer = []
            continue
        buffer.append(char)
    if buffer:
        paths.append("".join(buffer))
    return [item for item in paths if item]


def main(prefill: GuiPrefill | None = None) -> int:
    try:
        root = _make_root()
    except tk.TclError as exc:
        print(
            f"Could not open the GUI ({exc}). Use scg-stereorejoin in the terminal instead.",
            file=sys.stderr,
        )
        return 1
    root.title(f"SCG StereoRejoin {__version__}")
    app = StereoRejoinApp(root, prefill or GuiPrefill(patterns_text=default_patterns_text()))
    app.pack(fill="both", expand=True)
    root.mainloop()
    return 0


class ReportText(str):
    """String-compatible event carrying a report for lossless localization."""
    def __new__(cls, report):
        value = super().__new__(cls, format_report(report, verbose=True) + "\n")
        value.report = report
        return value


class StereoRejoinApp(ttk.Frame):
    def __init__(self, master: tk.Misc, prefill: GuiPrefill) -> None:
        super().__init__(master, padding=16)
        self.language = "en"
        self._texts = []
        self.tooltips = {}
        self.option_widgets = {}
        self._log_blocks = []
        self._dialogs = []
        self.paths: list[Path] = []
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._build_styles()
        self._build(prefill)
        for path in prefill.paths:
            self._add_path(Path(path))
        self._enable_drop()

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        paper = "#f4f1ea"
        ink = "#1c1b19"
        accent = "#1f4b4a"
        self.paper = paper
        self.ink = ink
        try:
            self.master.configure(bg=paper)
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=paper)
        style.configure("App.TLabel", background=paper, foreground=ink, font=("Helvetica", 11))
        style.configure("Title.TLabel", background=paper, foreground=ink, font=("Helvetica", 20, "bold"))
        style.configure("Muted.TLabel", background=paper, foreground="#5c584f", font=("Helvetica", 11))
        style.configure("App.TCheckbutton", background=paper, foreground=ink, font=("Helvetica", 11))
        style.configure("App.TButton", font=("Helvetica", 11), padding=(10, 6))
        style.configure("Run.TButton", font=("Helvetica", 12, "bold"), padding=(14, 8), background=accent)
        style.configure("App.TEntry", padding=4)
        self.configure(style="App.TFrame")

    def _build(self, prefill: GuiPrefill) -> None:
        header = ttk.Frame(self, style="App.TFrame")
        header.pack(fill="x")
        language_row = ttk.Frame(header, style="App.TFrame")
        language_row.pack(anchor="e")
        self._label(language_row, text="Language", style="App.TLabel").pack(side="left", padx=6)
        self.language_var = tk.StringVar(value=LANGUAGES[self.language])
        self.language_picker = ttk.Combobox(language_row, textvariable=self.language_var,
                                            values=list(LANGUAGES.values()), state="readonly", width=12)
        self.language_picker.pack(side="left")
        self.language_picker.bind("<<ComboboxSelected>>", self._language_selected)
        self._label(header, text="SCG Stereo Rejoin", style="Title.TLabel").pack(anchor="w")
        self._label(
            header,
            text="Join L/R WAVs: mono, or stereo with one silent channel. Audio stays bit-exact.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        self._label(self, text="Files", style="App.TLabel").pack(anchor="w")
        list_row = ttk.Frame(self, style="App.TFrame")
        list_row.pack(fill="both", expand=True)
        self.file_list = tk.Listbox(
            list_row,
            height=8,
            activestyle="none",
            bg="#fffdf8",
            fg=self.ink,
            selectbackground="#d7e4e2",
            highlightthickness=1,
            highlightbackground="#d9d3c7",
            relief="flat",
            font=("Helvetica", 11),
        )
        scroll = ttk.Scrollbar(list_row, command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=scroll.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(self, style="App.TFrame")
        buttons.pack(fill="x", pady=(8, 4))
        self._button(buttons, text="Add files", style="App.TButton", command=self._add_files).pack(side="left")
        self._button(buttons, text="Add folder", style="App.TButton", command=self._add_folder).pack(
            side="left", padx=6
        )
        self._button(buttons, text="Remove", style="App.TButton", command=self._remove_selected).pack(side="left")
        self._button(buttons, text="Clear", style="App.TButton", command=self._clear).pack(side="left", padx=6)
        self.drop_hint = self._label(
            self,
            text="Drop files here when tkinterdnd2 is installed. Otherwise use Add files or Add folder.",
            style="Muted.TLabel",
        )
        self.drop_hint.pack(anchor="w", pady=(0, 10))

        out = ttk.Frame(self, style="App.TFrame")
        out.pack(fill="x", pady=(0, 8))
        self._label(out, text="Output folder", style="App.TLabel").pack(side="left")
        self.output_var = tk.StringVar(value=prefill.output)
        ttk.Entry(out, textvariable=self.output_var, style="App.TEntry").pack(
            side="left", fill="x", expand=True, padx=8
        )
        self._button(out, text="Browse", style="App.TButton", command=self._browse_output).pack(side="left")
        self._label(
            self,
            text="Leave the output folder empty to write each stereo file next to its left source.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        options = ttk.Frame(self, style="App.TFrame")
        options.pack(fill="x")
        self.recursive_var = tk.BooleanVar(value=prefill.recursive)
        self.pad_var = tk.BooleanVar(value=prefill.pad)
        self.overwrite_var = tk.BooleanVar(value=prefill.overwrite)
        self.delete_var = tk.BooleanVar(value=prefill.delete_sources)
        self.bw64_var = tk.BooleanVar(value=prefill.bw64)
        self.dry_var = tk.BooleanVar(value=prefill.dry_run)
        for key, text, var in (
            ("recursive", "Include subfolders", self.recursive_var),
            ("pad", "Pad a shorter side with silence", self.pad_var),
            ("overwrite", "Overwrite existing outputs", self.overwrite_var),
            ("delete", "Move source files to trash after a successful join", self.delete_var),
            ("bw64", "Use BW64 for files over 4 GB", self.bw64_var),
            ("dry", "Dry run", self.dry_var),
        ):
            widget = ttk.Checkbutton(options, text=text, variable=var, style="App.TCheckbutton")
            self._texts.append((widget, text))
            widget.pack(anchor="w")
            self.option_widgets[key] = widget
            self._tip(widget, key)

        self.pattern_title = self._label(self, text="Pairing patterns", style="App.TLabel")
        self.pattern_title.pack(anchor="w", pady=(10, 2))
        self._tip(self.pattern_title, "patterns", "patterns_title")
        self.patterns = tk.Text(
            self,
            height=7,
            width=40,
            bg="#fffdf8",
            fg=self.ink,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#d9d3c7",
            font=("Courier", 11),
        )
        self.patterns.pack(fill="x")
        self._tip(self.patterns, "patterns", "patterns_editor")
        self.patterns.insert("1.0", prefill.patterns_text or default_patterns_text())
        self.pattern_help = self._label(
            self,
            text="One LEFT/RIGHT pair per line. A leading space matters: the built-in “ L/ R” line keeps it.",
            style="Muted.TLabel",
        )
        self.pattern_help.pack(anchor="w", pady=(2, 8))
        self._tip(self.pattern_help, "patterns", "patterns_help")

        self.run_button = self._button(self, text="Rejoin", style="Run.TButton", command=self._start)
        self.run_button.pack(anchor="w")

        self._label(self, text="Log", style="App.TLabel").pack(anchor="w", pady=(12, 2))
        self.log = tk.Text(
            self,
            height=10,
            bg="#fffdf8",
            fg=self.ink,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#d9d3c7",
            font=("Courier", 10),
            wrap="word",
        )
        self.log.pack(fill="both", expand=True)

    def _add_files(self) -> None:
        selected = filedialog.askopenfilenames(
            title=self._t("WAV source files"),
            filetypes=[("WAV", "*.wav *.WAV *.wave *.WAVE"), (self._t("All files"), "*.*")],
        )
        for name in selected:
            self._add_path(Path(name))

    def _add_folder(self) -> None:
        selected = filedialog.askdirectory(title=self._t("Folder of split mono files"))
        if selected:
            self._add_path(Path(selected))

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(title=self._t("Output folder"))
        if selected:
            self.output_var.set(selected)

    def _add_path(self, path: Path) -> None:
        resolved = path.expanduser()
        if resolved in self.paths:
            return
        self.paths.append(resolved)
        self.file_list.insert("end", str(resolved))

    def _remove_selected(self) -> None:
        indexes = list(self.file_list.curselection())
        for index in reversed(indexes):
            self.file_list.delete(index)
            del self.paths[index]

    def _clear(self) -> None:
        self.file_list.delete(0, "end")
        self.paths.clear()

    def _enable_drop(self) -> None:
        try:
            from tkinterdnd2 import DND_FILES
        except ImportError:
            return
        try:
            self.file_list.drop_target_register(DND_FILES)
            self.file_list.dnd_bind("<<Drop>>", self._on_drop)
            self._texts = [(w, "Drop WAV files or a folder onto the list." if w is self.drop_hint else t) for w, t in self._texts]
            self.drop_hint.configure(text=self._t("Drop WAV files or a folder onto the list."))
        except tk.TclError:
            return

    def _on_drop(self, event) -> None:
        for name in parse_drop_paths(event.data):
            self._add_path(Path(name))

    def _start(self) -> None:
        if not self.paths:
            self._dialog("SCG Stereo Rejoin", "Add at least one file or folder.")
            return
        if self.delete_var.get():
            confirmed = self._dialog(
                "Move source files to trash",
                "Move the original source WAVs into the hidden .scg_stereorejoin_trash "
                "folder beside each source after each verified join?",
                question=True,
            )
            if not confirmed:
                return
        try:
            patterns = self._patterns()
        except PatternError as exc:
            self._dialog("Patterns", str(exc), runtime=True)
            return
        output = self.output_var.get().strip()
        options = {
            "recursive": bool(self.recursive_var.get()),
            "pad": bool(self.pad_var.get()),
            "overwrite": bool(self.overwrite_var.get()),
            "delete_sources": bool(self.delete_var.get()),
            "dry_run": bool(self.dry_var.get()),
            "large_container": "bw64" if self.bw64_var.get() else "rf64",
        }
        self.run_button.configure(state="disabled")
        self._write_log("Working…\n")
        worker = threading.Thread(
            target=self._join,
            args=(list(self.paths), patterns, output, options),
            daemon=True,
        )
        worker.start()
        self.after(80, self._drain)

    def _patterns(self):
        specs: list[str] = []
        for line in self.patterns.get("1.0", "end").splitlines():
            if line.lstrip().startswith("#") or line.strip() == "":
                continue
            specs.append(line)
        return load_patterns(specs, use_defaults=False)

    def _join(self, paths: list[Path], patterns, output: str, options: dict) -> None:
        try:
            report = process(
                paths,
                output_dir=Path(output) if output else None,
                recursive=options["recursive"],
                patterns=patterns,
                pad=options["pad"],
                overwrite=options["overwrite"],
                delete_sources=options["delete_sources"],
                dry_run=options["dry_run"],
                large_container=options["large_container"],
                on_message=lambda message: self.events.put(("line", message)),
            )
        except RejoinError as exc:
            self.events.put(("done", f"error: {exc}\n"))
            return
        self.events.put(("done", ReportText(report)))

    def _drain(self) -> None:
        finished = False
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self._append_log(str(payload) + "\n")
            else:
                self._append_log(payload)
                finished = True
            self.log.see("end")
        if finished:
            self.run_button.configure(state="normal")
            return
        self.after(80, self._drain)

    def _write_log(self, text: str) -> None:
        self._log_blocks = [text]
        self._render_log()

    def _append_log(self, payload):
        self._log_blocks.append(payload)
        self.log.insert("end", self._render_block(payload))

    def _render_block(self, payload):
        if isinstance(payload, ReportText):
            return format_gui_report(payload.report, self.language, verbose=True) + "\n"
        return translate_message(str(payload), self.language)

    def _render_log(self):
        position = self.log.yview()
        self.log.delete("1.0", "end")
        self.log.insert("end", "".join(self._render_block(block) for block in self._log_blocks))
        self.log.yview_moveto(position[0])

    def _t(self, text):
        return translate(text, self.language)

    def _label(self, master, **kwargs):
        return self._text_widget(ttk.Label, master, **kwargs)

    def _button(self, master, **kwargs):
        return self._text_widget(ttk.Button, master, **kwargs)

    def _text_widget(self, cls, master, **kwargs):
        text = kwargs.pop("text", "")
        widget = cls(master, text=self._t(text), **kwargs)
        self._texts.append((widget, text))
        return widget

    def _tip(self, widget, key, name=None):
        self.tooltips[name or key] = HoverTip(widget, lambda: tooltip_text(key, self.language))

    def _language_selected(self, event=None):
        for code, name in LANGUAGES.items():
            if name == self.language_var.get():
                self.set_language(code)
                break

    def set_language(self, code):
        if code not in LANGUAGES:
            raise ValueError(f"unsupported language: {code}")
        for tip in self.tooltips.values():
            tip.hide()
        self.language = code
        self.language_var.set(LANGUAGES[code])
        self._texts = [(w, text) for w, text in self._texts if w.winfo_exists()]
        for widget, text in self._texts:
            widget.configure(text=self._t(text))
        for window, title, label, body, runtime in self._dialogs:
            window.title(self._t(title))
            label.configure(text=translate_message(body, code) if runtime else self._t(body))
        self._render_log()

    def _dialog(self, title, body, question=False, runtime=False):
        # App-owned buttons are translated; native filepicker chrome follows macOS.
        window = tk.Toplevel(self)
        window.title(self._t(title))
        window.transient(self.winfo_toplevel())
        result = tk.BooleanVar(master=window, value=False)
        label = ttk.Label(window, text=translate_message(body, self.language) if runtime else self._t(body),
                          wraplength=520, padding=18)
        label.pack(fill="both", expand=True)
        record = (window, title, label, body, runtime)
        self._dialogs.append(record)
        def close(value=False):
            result.set(value)
            window.destroy()
        buttons = ttk.Frame(window, padding=12)
        buttons.pack(fill="x")
        if question:
            cancel = self._button(buttons, text="No", command=close)
            cancel.pack(side="right", padx=6)
        accept = self._button(buttons, text="Yes" if question else "OK", command=lambda: close(True))
        accept.pack(side="right")
        window.protocol("WM_DELETE_WINDOW", close)
        window.bind("<Escape>", lambda event: close())
        def accept_focused(event):
            focused = window.focus_get()
            if focused in buttons.winfo_children():
                focused.invoke()
            return "break"
        window.bind("<Return>", accept_focused)
        window.grab_set()
        (cancel if question else accept).focus_set()
        try:
            self.wait_window(window)
            return result.get()
        finally:
            self._dialogs.remove(record)
            self._texts = [(w, text) for w, text in self._texts if w.winfo_exists()]



def _make_root() -> tk.Tk:
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD.Tk()
    except ImportError:
        return tk.Tk()


if __name__ == "__main__":
    raise SystemExit(main())
