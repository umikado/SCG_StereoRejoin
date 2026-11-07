"""Nonmodal, delayed hover help; bindings never consume widget events."""
from __future__ import annotations
import tkinter as tk
from collections.abc import Callable


class HoverTip:
    def __init__(self, widget: tk.Misc, text: Callable[[], str], delay: int = 400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.pending = None
        self.window = None
        self.top = widget.winfo_toplevel()
        self.bindings = []
        for target, sequence, callback in (
            (widget, "<Enter>", self.schedule),
            (widget, "<Leave>", self.hide),
            (widget, "<ButtonPress>", self.hide),
            (widget, "<Destroy>", self.dispose),
            (self.top, "<FocusOut>", self.hide),
            (self.top, "<Unmap>", self.hide),
            (self.top, "<ButtonPress>", self.hide),
        ):
            self.bindings.append((target, sequence, target.bind(sequence, callback, add="+")))

    def schedule(self, event=None):
        self.hide()
        self.pending = self.widget.after(self.delay, self.show)

    def show(self):
        self.pending = None
        if not self.widget.winfo_exists() or not self.widget.winfo_viewable():
            return
        window = self.window = tk.Toplevel(self.widget, takefocus=False)
        window.withdraw()
        window.overrideredirect(True)
        try:
            window.attributes("-topmost", True)
            if window.tk.call("tk", "windowingsystem") == "aqua":
                window.tk.call("::tk::unsupported::MacWindowStyle", "style", window._w, "help", "noActivates")
        except tk.TclError:
            pass
        width = self.widget.winfo_screenwidth()
        height = self.widget.winfo_screenheight()
        tk.Label(window, text=self.text(), justify="left", wraplength=max(120, min(560, width - 32)),
                 background="#fffbe8", foreground="#202020", relief="solid", borderwidth=1,
                 padx=10, pady=8, font=("Helvetica", 11), takefocus=False).pack()
        window.update_idletasks()
        w, h = window.winfo_reqwidth(), window.winfo_reqheight()
        x = max(0, min(self.widget.winfo_rootx(), width - w))
        y = max(0, min(self.widget.winfo_rooty() - h - 6, height - h))
        window.geometry(f"+{x}+{y}")
        window.deiconify()

    def hide(self, event=None):
        if self.pending is not None:
            try:
                self.widget.after_cancel(self.pending)
            except tk.TclError:
                pass
            self.pending = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None

    def dispose(self, event=None):
        self.hide()
        for target, sequence, binding in self.bindings:
            try:
                target.unbind(sequence, binding)
            except tk.TclError:
                pass
        self.bindings.clear()
