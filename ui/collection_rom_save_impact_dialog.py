"""Explicit save-disposition review for Collection ROM organization plans."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from collection_rom_save_disposition import (
    CollectionRomSaveDispositionError,
    SaveDisposition,
    companion_disposition_key,
    finalize_collection_rom_save_disposition_decision,
)
from collection_rom_save_impact import (
    CollectionRomSaveImpactReview,
    SOURCE_COLOCATED,
    SOURCE_CONFIGURED_ASSOCIATION,
    SOURCE_CONFIGURED_NAME,
)


_SOURCE_LABELS = {
    SOURCE_COLOCATED: "Beside ROM",
    SOURCE_CONFIGURED_NAME: "Configured name match",
    SOURCE_CONFIGURED_ASSOCIATION: "Saved association",
}


class CollectionRomSaveImpactDialog:
    """Modal review that records detached save dispositions but performs no mutation."""

    def __init__(self, parent, review: CollectionRomSaveImpactReview, on_save=None, on_close=None):
        self.review = review
        self._parent = parent
        self._on_save = on_save
        self._on_close = on_close
        self._closed = False
        self._companion_vars: dict[str, tk.StringVar] = {}
        self._ack_vars: dict[str, tk.BooleanVar] = {}
        self._save_sync_coverage_ack_vars: dict[str, tk.BooleanVar] = {}
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Collection ROM Organization — Save Dispositions")
        self.dialog.geometry("1180x760")
        self.dialog.minsize(900, 560)
        self.dialog.transient(parent)

        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="ROM Organization Save Dispositions",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Review-only decision boundary. Choose what should happen to detected saves if "
                "a later execution plan is created. Saving this review does not move any ROM or "
                "save file and does not modify Collection or Save Sync settings."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        summary = (
            f"Planned ROM moves: {len(self.review.plan.moves)}    "
            f"Related saves detected: {len(self.review.rows)}    "
            f"Beside ROM: {self.review.colocated_count}    "
            f"Configured/external: {self.review.external_count}    "
            f"Possible target conflicts: {self.review.target_conflict_count}    "
            f"Save Sync coverage loss warnings: {self.review.save_sync_coverage_loss_count}"
        )
        ttk.Label(outer, text=summary, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(0, 10)
        )

        canvas_frame = ttk.Frame(outer)
        canvas_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_frame, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))

        rows_by_move: dict[tuple[str, str], list] = {}
        for row in self.review.rows:
            rows_by_move.setdefault((row.collection_id, row.rom_source_path), []).append(row)

        for move in self.review.plan.moves:
            frame = ttk.LabelFrame(body, text=f"{move.title} — {move.asset_name}", padding=10)
            frame.pack(fill="x", pady=(0, 10))
            ttk.Label(
                frame,
                text=f"ROM: {move.source_path}\nPlanned target: {move.target_path}",
                wraplength=1030,
                justify="left",
            ).pack(anchor="w", pady=(0, 8))

            move_rows = rows_by_move.get((move.collection_id, move.source_path), [])
            colocated = [row for row in move_rows if row.source_kind == SOURCE_COLOCATED]
            external = [row for row in move_rows if row.source_kind != SOURCE_COLOCATED]

            if colocated:
                ttk.Label(
                    frame,
                    text="Detected colocated save companions — choose one disposition for each:",
                    font=("Segoe UI", 9, "bold"),
                ).pack(anchor="w", pady=(0, 5))
                for row in colocated:
                    save_frame = ttk.Frame(frame, padding=(10, 4))
                    save_frame.pack(fill="x", pady=(0, 6))
                    target_state = "occupied" if row.target_occupied else "available"
                    ttk.Label(
                        save_frame,
                        text=(
                            f"{row.save_name}: {row.save_path}\n"
                            f"Possible colocated target ({target_state}): {row.possible_target_path}"
                        ),
                        wraplength=990,
                        justify="left",
                    ).pack(anchor="w")
                    key = companion_disposition_key(
                        row.collection_id,
                        row.rom_source_path,
                        row.save_path,
                    )
                    var = tk.StringVar(value="")
                    self._companion_vars[key] = var
                    migrate = ttk.Radiobutton(
                        save_frame,
                        text="Migrate this save with the ROM",
                        value=SaveDisposition.MIGRATE_WITH_ROM.value,
                        variable=var,
                    )
                    migrate.pack(anchor="w", padx=(14, 0), pady=(3, 1))
                    if row.target_occupied:
                        migrate.state(["disabled"])
                    ttk.Radiobutton(
                        save_frame,
                        text="Leave this save in its current location",
                        value=SaveDisposition.LEAVE_IN_PLACE.value,
                        variable=var,
                    ).pack(anchor="w", padx=(14, 0), pady=1)
                    ttk.Radiobutton(
                        save_frame,
                        text="Block this ROM move",
                        value=SaveDisposition.BLOCK_ROM_MOVE.value,
                        variable=var,
                    ).pack(anchor="w", padx=(14, 0), pady=1)
                    if row.target_occupied:
                        ttk.Label(
                            save_frame,
                            text="Migration is unavailable because the reviewed save target is occupied.",
                            foreground="#B00020",
                            wraplength=960,
                        ).pack(anchor="w", padx=(14, 0), pady=(2, 0))
                    if row.save_sync_coverage_lost:
                        ttk.Label(
                            save_frame,
                            text=(
                                "Save Sync coverage warning: this save currently lives directly in a "
                                "configured Save Sync directory, but the planned destination directory is "
                                "not configured. Migrating it may stop Save Sync from discovering this file."
                            ),
                            foreground="#B00020",
                            wraplength=960,
                            justify="left",
                        ).pack(anchor="w", padx=(14, 0), pady=(4, 1))
                        coverage_var = tk.BooleanVar(value=False)
                        self._save_sync_coverage_ack_vars[key] = coverage_var
                        ttk.Checkbutton(
                            save_frame,
                            text=(
                                "I understand that migrating this save will move it out of configured "
                                "Save Sync coverage. Do not change my Save Sync folders automatically."
                            ),
                            variable=coverage_var,
                        ).pack(anchor="w", padx=(14, 0), pady=(1, 2))
                    elif row.save_sync_coverage_retained:
                        ttk.Label(
                            save_frame,
                            text="Save Sync coverage is retained because the destination directory is also configured.",
                            foreground="gray",
                            wraplength=960,
                        ).pack(anchor="w", padx=(14, 0), pady=(2, 0))
                    elif row.save_sync_coverage_gained:
                        ttk.Label(
                            save_frame,
                            text="The planned destination directory is configured in Save Sync; migration would add scan coverage for this save.",
                            foreground="gray",
                            wraplength=960,
                        ).pack(anchor="w", padx=(14, 0), pady=(2, 0))
            else:
                var = tk.BooleanVar(value=False)
                self._ack_vars[move.source_path] = var
                ttk.Checkbutton(
                    frame,
                    text=(
                        "Proceed with this ROM move in the next planning step after acknowledging "
                        "that no colocated .srm/.sav companion was detected. This does not prove "
                        "that emulator save state is absent elsewhere."
                    ),
                    variable=var,
                ).pack(anchor="w", pady=(2, 6))

            if external:
                ttk.Label(
                    frame,
                    text="Configured/associated Save Sync evidence (informational only):",
                    font=("Segoe UI", 9, "bold"),
                ).pack(anchor="w", pady=(4, 3))
                for row in external:
                    ttk.Label(
                        frame,
                        text=(
                            f"• {_SOURCE_LABELS.get(row.source_kind, row.source_kind)}: "
                            f"{row.save_path}"
                        ),
                        wraplength=1000,
                        justify="left",
                    ).pack(anchor="w", padx=(10, 0), pady=1)
                ttk.Label(
                    frame,
                    text=(
                        "No move disposition is available for configured/external evidence because "
                        "Save Sync folders do not establish the emulator's storage policy."
                    ),
                    foreground="gray",
                    wraplength=1000,
                ).pack(anchor="w", padx=(10, 0), pady=(2, 0))

        ttk.Label(
            outer,
            text=(
                "Saving these choices retains only a detached immutable decision bound to this exact "
                "save-impact review. A later plan must rediscover and revalidate the evidence before "
                "any filesystem action can exist."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(10, 8))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        ttk.Button(
            buttons,
            text="Save Disposition Review",
            command=self._save,
        ).pack(side="right", padx=(0, 8))

    def _save(self):
        dispositions = {key: var.get().strip() for key, var in self._companion_vars.items()}
        acknowledgements = [path for path, var in self._ack_vars.items() if bool(var.get())]
        coverage_acknowledgements = [
            key for key, var in self._save_sync_coverage_ack_vars.items() if bool(var.get())
        ]
        try:
            decision = finalize_collection_rom_save_disposition_decision(
                self.review,
                companion_dispositions=dispositions,
                rom_only_acknowledgements=acknowledgements,
                save_sync_coverage_loss_acknowledgements=coverage_acknowledgements,
            )
        except CollectionRomSaveDispositionError as error:
            messagebox.showinfo("Complete Save Review", str(error), parent=self.dialog)
            return

        accepted = True
        if self._on_save is not None:
            accepted = self._on_save(self.review, decision) is not False
        if accepted:
            self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.dialog.winfo_exists():
                self.dialog.grab_release()
                self.dialog.destroy()
        finally:
            if self._on_close is not None:
                self._on_close()
            try:
                if self._parent.winfo_exists():
                    self._parent.grab_set()
            except tk.TclError:
                pass
