"""Data Management entry points and the persistent Save Sync workspace."""
import sys
import tkinter as tk
from tkinter import ttk

from ui.save_sync_panel import SaveSyncPanel


class DataPage:
    def __init__(self, parent, setup_section, collection_page, logger=None):
        self.parent = parent
        self.setup_section = setup_section
        self.collection_page = collection_page
        self.logger = logger
        self.frame = None
        self.save_sync_panel = None

    def create(self):
        if self.frame is not None:
            return self.frame
        self.frame = ttk.Frame(self.parent)
        self.canvas = tk.Canvas(self.frame, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(self.canvas, padding=(20, 14))
        content_window = self.canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(
            content_window, width=event.width))
        self.frame.bind("<<ThemeChanged>>", self._update_theme, add="+")
        self._update_theme()

        ttk.Label(content, text="Data Management", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            content,
            text="Bring ROMs, play history and save progress into your Collection. "
                 "Review the proposed changes before applying them.",
            wraplength=700,
        ).pack(anchor="w", pady=(4, 12))

        imports = ttk.Frame(content)
        imports.pack(fill="x", pady=(0, 8))
        imports.columnconfigure(0, weight=1, uniform="imports")
        imports.columnconfigure(1, weight=1, uniform="imports")
        self._import_card(
            imports, 0, "ROMs", "Add .sfc / .smc files from a folder you already have.",
            "Import ROMs...", "rom",
        )
        self._import_card(
            imports, 1, "GiganticBucket", "Bring playthroughs and personal data from a JSON export.",
            "Import GiganticBucket...", "giganticbucket",
        )

        self.advanced_var = tk.BooleanVar(master=self.frame, value=False)
        ttk.Checkbutton(
            content, text="Advanced import options", variable=self.advanced_var,
            command=self._toggle_advanced,
        ).pack(anchor="w", pady=(0, 8))
        self.advanced_frame = ttk.Frame(content)
        ttk.Button(
            self.advanced_frame, text="Combine sources...",
            command=lambda: self._start_import("combined"),
        ).pack(side="left")
        ttk.Label(
            self.advanced_frame,
            text="Review a ROM folder and GiganticBucket export together.",
            wraplength=470,
        ).pack(side="left", padx=(10, 0))

        self.save_sync_panel = SaveSyncPanel(
            content, self.setup_section, self.collection_page.data_manager,
            logger=self.logger,
            on_applied=self.collection_page._refresh_data_and_table,
        )
        self.save_sync_panel.create().pack(fill="x")
        self._bind_scrolling(self.frame)
        return self.frame

    def _import_card(self, parent, column, title, description, action, source_kind):
        card = ttk.LabelFrame(parent, text=title, padding=12)
        card.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
        label = ttk.Label(card, text=description, wraplength=300)
        label.pack(anchor="w", pady=(0, 10))
        card.bind("<Configure>", lambda event: label.configure(wraplength=max(120, event.width - 28)))
        ttk.Button(
            card, text=action, style="Accent.TButton",
            command=lambda: self._start_import(source_kind),
        ).pack(anchor="w")

    def _start_import(self, source_kind):
        self.collection_page._open_collection_import(source_kind=source_kind)

    def _toggle_advanced(self):
        if self.advanced_var.get():
            self.advanced_frame.pack(fill="x", pady=(0, 12), before=self.save_sync_panel.frame)
        else:
            self.advanced_frame.pack_forget()

    def _update_theme(self, _event=None):
        color = ttk.Style().lookup("TFrame", "background") or self.frame.winfo_toplevel().cget("bg")
        self.canvas.configure(background=color)

    def _bind_scrolling(self, widget):
        # Page-local bindings: scrolling here cannot take over another page/dialog.
        if not isinstance(widget, (tk.Listbox, ttk.Combobox, ttk.Scrollbar)):
            for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(event, self._scroll, add="+")
        for child in widget.winfo_children():
            self._bind_scrolling(child)

    def _scroll(self, event):
        if self.canvas.yview() == (0.0, 1.0):
            return
        number = getattr(event, "num", None)
        if number in (4, 5):
            steps = -1 if number == 4 else 1
        elif not event.delta:
            return
        elif sys.platform == "darwin":
            steps = -int(event.delta)
        else:
            steps = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(steps, "units")
        return "break"
