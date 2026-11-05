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
from tkinter import filedialog, messagebox, ttk

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
    app = StereoRejoinApp(root, prefill or GuiPrefill(patterns_text=default_patterns_text()))
    app.pack(fill="both", expand=True)
    root.mainloop()
    return 0


class StereoRejoinApp(ttk.Frame):
    def __init__(self, master: tk.Misc, prefill: GuiPrefill) -> None:
        super().__init__(master, padding=16)
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
        ttk.Label(header, text="SCG Stereo Rejoin", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Join split dual-mono WAVs into one interleaved stereo file. Audio stays bit-exact.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        ttk.Label(self, text="Files", style="App.TLabel").pack(anchor="w")
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
        ttk.Button(buttons, text="Add files", style="App.TButton", command=self._add_files).pack(side="left")
        ttk.Button(buttons, text="Add folder", style="App.TButton", command=self._add_folder).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="Remove", style="App.TButton", command=self._remove_selected).pack(side="left")
        ttk.Button(buttons, text="Clear", style="App.TButton", command=self._clear).pack(side="left", padx=6)
        self.drop_hint = ttk.Label(
            self,
            text="Drop files here when tkinterdnd2 is installed. Otherwise use Add files or Add folder.",
            style="Muted.TLabel",
        )
        self.drop_hint.pack(anchor="w", pady=(0, 10))

        out = ttk.Frame(self, style="App.TFrame")
        out.pack(fill="x", pady=(0, 8))
        ttk.Label(out, text="Output folder", style="App.TLabel").pack(side="left")
        self.output_var = tk.StringVar(value=prefill.output)
        ttk.Entry(out, textvariable=self.output_var, style="App.TEntry").pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(out, text="Browse", style="App.TButton", command=self._browse_output).pack(side="left")
        ttk.Label(
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
        for text, var in (
            ("Include subfolders", self.recursive_var),
            ("Pad a shorter side with silence", self.pad_var),
            ("Overwrite existing outputs", self.overwrite_var),
            ("Delete source files after a successful join", self.delete_var),
            ("Use BW64 for files over 4 GB", self.bw64_var),
            ("Dry run", self.dry_var),
        ):
            ttk.Checkbutton(options, text=text, variable=var, style="App.TCheckbutton").pack(anchor="w")

        ttk.Label(self, text="Pairing patterns", style="App.TLabel").pack(anchor="w", pady=(10, 2))
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
        self.patterns.insert("1.0", prefill.patterns_text or default_patterns_text())
        ttk.Label(
            self,
            text="One LEFT/RIGHT pair per line. A leading space matters: the built-in “ L/ R” line keeps it.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 8))

        self.run_button = ttk.Button(self, text="Rejoin", style="Run.TButton", command=self._start)
        self.run_button.pack(anchor="w")

        ttk.Label(self, text="Log", style="App.TLabel").pack(anchor="w", pady=(12, 2))
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
            title="Mono WAV files",
            filetypes=[("WAV", "*.wav *.WAV *.wave *.WAVE"), ("All files", "*.*")],
        )
        for name in selected:
            self._add_path(Path(name))

    def _add_folder(self) -> None:
        selected = filedialog.askdirectory(title="Folder of split mono files")
        if selected:
            self._add_path(Path(selected))

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(title="Output folder")
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
            self.drop_hint.configure(text="Drop WAV files or a folder onto the list.")
        except tk.TclError:
            return

    def _on_drop(self, event) -> None:
        for name in parse_drop_paths(event.data):
            self._add_path(Path(name))

    def _start(self) -> None:
        if not self.paths:
            messagebox.showinfo("SCG Stereo Rejoin", "Add at least one file or folder.")
            return
        if self.delete_var.get():
            confirmed = messagebox.askyesno(
                "Delete source files",
                "Delete the original mono files after each successful join?",
            )
            if not confirmed:
                return
        try:
            patterns = self._patterns()
        except PatternError as exc:
            messagebox.showerror("Patterns", str(exc))
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
        text = format_report(report, verbose=True)
        self.events.put(("done", text + "\n"))

    def _drain(self) -> None:
        finished = False
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self.log.insert("end", str(payload) + "\n")
            else:
                self.log.insert("end", str(payload))
                finished = True
            self.log.see("end")
        if finished:
            self.run_button.configure(state="normal")
            return
        self.after(80, self._drain)

    def _write_log(self, text: str) -> None:
        self.log.delete("1.0", "end")
        self.log.insert("end", text)


def _make_root() -> tk.Tk:
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD.Tk()
    except ImportError:
        return tk.Tk()


if __name__ == "__main__":
    raise SystemExit(main())
