"""Read-only immutable historical ROM organization plan preview."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from collection_rom_historical_organization_plan import HistoricalRomOrganizationPlan


class CollectionRomHistoricalOrganizationPlanDialog:
    """Modal preview of frozen historical-submission ROM move intent."""

    def __init__(
        self,
        parent,
        plan: HistoricalRomOrganizationPlan,
        on_close=None,
        on_review_save_impact=None,
        on_preview_execution_plan=None,
    ):
        self.plan = plan
        self._on_close = on_close
        self._on_review_save_impact = on_review_save_impact
        self._on_preview_execution_plan = on_preview_execution_plan
        self._save_disposition_decision = None
        self._preview_execution_button = None
        self._save_disposition_status_var = None
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Historical ROM Organization Plan")
        self.dialog.geometry("1280x700")
        self.dialog.minsize(980, 540)
        self.dialog.transient(parent)
        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Historical ROM Organization Plan",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Immutable read-only preview. Each target is frozen from the ROM asset's "
                "own reviewed historical SMWC submission metadata. Exact ROM SHA-256, size, "
                "mtime and Collection revision are now preconditions; no files are moved."
            ),
            wraplength=1180,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        summary = (
            f"Frozen historical moves: {len(self.plan.moves)}    "
            f"Review rows: {self.plan.review_row_count}    "
            f"Already in place: {self.plan.in_place_count}    "
            f"Excluded/blocking: {self.plan.excluded_blocking_count}"
        )
        ttk.Label(outer, text=summary, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(0, 10)
        )

        frame = ttk.Frame(outer)
        frame.pack(fill="both", expand=True)
        columns = (
            "collection", "asset", "historical", "metadata",
            "source", "target", "identity",
        )
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        headings = {
            "collection": "Current Collection",
            "asset": "ROM Asset",
            "historical": "ROM Provenance",
            "metadata": "Frozen Historical Layout",
            "source": "Source",
            "target": "Target",
            "identity": "Frozen Byte Identity",
        }
        widths = {
            "collection": 170, "asset": 140, "historical": 120,
            "metadata": 190, "source": 230, "target": 250, "identity": 205,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], minwidth=100, anchor="w")

        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        rows_by_item = {}
        for move in self.plan.moves:
            item = tree.insert(
                "",
                "end",
                values=(
                    move.collection_title,
                    move.asset_name + ("  ★" if move.primary else ""),
                    f"SMWC {move.historical_smwc_submission_id}",
                    f"{move.historical_hack_type} / {move.historical_difficulty}",
                    move.source_path,
                    move.target_path,
                    f"{move.sha256[:12]}… / {move.size_bytes} bytes",
                ),
            )
            rows_by_item[item] = move

        detail_var = tk.StringVar(
            value="Select a move to inspect the frozen historical provenance and byte preconditions."
        )
        ttk.Label(
            outer,
            textvariable=detail_var,
            wraplength=1180,
            justify="left",
        ).pack(fill="x", pady=(10, 8))

        def show_detail(_event=None):
            selected = tree.selection()
            if not selected:
                return
            move = rows_by_item.get(selected[0])
            if move is None:
                return
            detail_var.set(
                f"SMWC {move.historical_smwc_submission_id}: {move.historical_title}. "
                f"Frozen layout metadata: {move.historical_hack_type} / "
                f"{move.historical_difficulty}. SHA-256: {move.sha256}. "
                f"Source mtime_ns: {move.source_mtime_ns}."
            )

        tree.bind("<<TreeviewSelect>>", show_detail)

        self._save_disposition_status_var = tk.StringVar(
            value=(
                "Save dispositions: not reviewed. Historical filesystem execution remains unavailable."
            )
        )
        ttk.Label(
            outer,
            textvariable=self._save_disposition_status_var,
            wraplength=1180,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        ttk.Label(
            outer,
            text=(
                "Save-impact review uses these exact historical move targets. After every save has an "
                "explicit disposition, a separate final execution preview can freeze the exact ROM/save "
                "operations. Apply remains unavailable in this boundary."
            ),
            wraplength=1180,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        if self._on_preview_execution_plan is not None:
            self._preview_execution_button = ttk.Button(
                buttons,
                text="Preview Final Execution Plan...",
                command=self._preview_execution_plan,
                state="disabled",
            )
            self._preview_execution_button.pack(side="right", padx=(0, 8))
        if self._on_review_save_impact is not None:
            ttk.Button(
                buttons,
                text="Review Save Dispositions...",
                command=self._review_save_impact,
            ).pack(side="right", padx=(0, 8))


    def _review_save_impact(self):
        if self._on_review_save_impact is None:
            return
        self._on_review_save_impact(self.plan, self.dialog)

    def _preview_execution_plan(self):
        if self._on_preview_execution_plan is None or self._save_disposition_decision is None:
            return
        self._on_preview_execution_plan(
            self.plan,
            self._save_disposition_decision,
            self.dialog,
        )

    def set_save_disposition_decision(self, decision):
        """Reflect detached save choices and enable the separate final preview boundary."""
        self._save_disposition_decision = decision
        if self._save_disposition_status_var is None:
            return
        self._save_disposition_status_var.set(
            f"Save dispositions reviewed: {decision.approved_move_count} historical ROM move(s) "
            f"remain eligible for a later execution-plan boundary; {decision.blocked_move_count} "
            f"blocked. Save migrations selected: {decision.migrate_save_count}; leave in place: "
            f"{decision.leave_save_count}. Final execution preview is now available; "
            "filesystem Apply is still unavailable."
        )
        if self._preview_execution_button is not None:
            self._preview_execution_button.configure(state="normal")

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
