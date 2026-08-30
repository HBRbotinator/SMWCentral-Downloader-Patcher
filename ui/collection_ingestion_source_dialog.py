"""Source-selection and busy UI for non-persisting Collection import review."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui.window_positioning import center_window_on_parent

from collection_ingestion_entrypoint import (
    CollectionIngestionEntrypointError,
    CollectionIngestionSourceSelection,
    validate_collection_ingestion_selection,
)


class CollectionIngestionSourceDialog:
    """Choose ROM-folder and/or GiganticBucket inputs before orchestration."""

    def __init__(
        self,
        parent,
        *,
        default_rom_root="",
        on_start=None,
        on_close=None,
    ):
        self.parent = parent
        self.default_rom_root = str(default_rom_root or "")
        self.on_start = on_start
        self.on_close = on_close
        self.win = None
        self.rom_enabled = None
        self.rom_path = None
        self.bucket_enabled = None
        self.bucket_path = None
        self._closed = False

    @property
    def is_open(self):
        try:
            return bool(self.win and self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self):
        if self.is_open:
            self.lift()
            return self.win

        self.win = tk.Toplevel(self.parent)
        self.win.title("Import into Collection")
        self.win.geometry("720x330")
        self.win.minsize(640, 300)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=16)
        root.pack(fill="both", expand=True)
        ttk.Label(
            root,
            text="Import into Collection",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "Choose one or both real data sources. The import first builds a "
                "review session; no Collection changes are written from this step."
            ),
            wraplength=670,
        ).pack(anchor="w", pady=(4, 14))

        self.rom_enabled = tk.BooleanVar(value=bool(self.default_rom_root))
        self.rom_path = tk.StringVar(value=self.default_rom_root)
        self.bucket_enabled = tk.BooleanVar(value=False)
        self.bucket_path = tk.StringVar(value="")

        sources = ttk.LabelFrame(root, text="Sources", padding=12)
        sources.pack(fill="x")
        self._source_row(
            sources,
            row=0,
            variable=self.rom_enabled,
            label="ROM folder (.sfc / .smc)",
            path_variable=self.rom_path,
            browse_command=self._browse_rom_folder,
        )
        self._source_row(
            sources,
            row=1,
            variable=self.bucket_enabled,
            label="GiganticBucket JSON export",
            path_variable=self.bucket_path,
            browse_command=self._browse_giganticbucket,
        )

        ttk.Label(
            root,
            text=(
                "KaizOFF is used automatically for catalogue matching. The complete "
                "Index is cached locally; rich metadata is not fetched during this "
                "source-selection step."
            ),
            foreground="gray",
            wraplength=670,
        ).pack(anchor="w", pady=(12, 0))

        buttons = ttk.Frame(root)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right")
        ttk.Button(
            buttons,
            text="Start Review",
            style="Accent.TButton",
            command=self._start,
        ).pack(side="right", padx=(0, 8))

        self._center()
        return self.win

    def _source_row(
        self,
        parent,
        *,
        row,
        variable,
        label,
        path_variable,
        browse_command,
    ):
        ttk.Checkbutton(parent, text=label, variable=variable).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=5,
        )
        ttk.Entry(parent, textvariable=path_variable).grid(
            row=row,
            column=1,
            sticky="ew",
            pady=5,
        )
        ttk.Button(parent, text="Browse...", command=browse_command).grid(
            row=row,
            column=2,
            padx=(8, 0),
            pady=5,
        )
        parent.columnconfigure(1, weight=1)

    def _browse_rom_folder(self):
        initial = self.rom_path.get().strip() or self.default_rom_root or None
        selected = filedialog.askdirectory(
            parent=self.win,
            title="Choose ROM folder",
            initialdir=initial,
            mustexist=True,
        )
        if selected:
            self.rom_path.set(selected)
            self.rom_enabled.set(True)

    def _browse_giganticbucket(self):
        selected = filedialog.askopenfilename(
            parent=self.win,
            title="Choose GiganticBucket JSON export",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if selected:
            self.bucket_path.set(selected)
            self.bucket_enabled.set(True)

    def _selection(self):
        selection = CollectionIngestionSourceSelection(
            rom_root=self.rom_path.get().strip() if self.rom_enabled.get() else "",
            giganticbucket_path=(
                self.bucket_path.get().strip() if self.bucket_enabled.get() else ""
            ),
        )
        return validate_collection_ingestion_selection(selection)

    def _start(self):
        try:
            selection = self._selection()
        except CollectionIngestionEntrypointError as error:
            messagebox.showerror("Collection Import", str(error), parent=self.win)
            return
        if self.on_start and self.on_start(selection) is False:
            return
        self.close()

    def lift(self):
        if not self.is_open:
            return
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except tk.TclError:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.win and self.win.winfo_exists():
                self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()

    def _center(self):
        center_window_on_parent(self.win, self.parent)



class CollectionIngestionProgressDialog:
    """Small non-cancellable busy window while real sources are inspected."""

    def __init__(self, parent):
        self.parent = parent
        self.win = None

    def show(self):
        if self.win:
            return self.win
        self.win = tk.Toplevel(self.parent)
        self.win.title("Preparing Collection Import")
        self.win.resizable(False, False)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        body = ttk.Frame(self.win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Preparing Collection import review...",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "Scanning selected files and matching against the cached/current "
                "KaizOFF catalogue. Collection and user metadata are not changed."
            ),
            wraplength=430,
        ).pack(anchor="w", pady=(5, 10))
        progress = ttk.Progressbar(body, mode="indeterminate", length=430)
        progress.pack(fill="x")
        progress.start(12)
        center_window_on_parent(self.win, self.parent)
        return self.win

    def close(self):
        try:
            if self.win and self.win.winfo_exists():
                self.win.destroy()
        except tk.TclError:
            pass
        self.win = None


__all__ = [
    "CollectionIngestionProgressDialog",
    "CollectionIngestionSourceDialog",
]
