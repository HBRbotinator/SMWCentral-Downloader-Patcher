import tkinter as tk
from tkinter import ttk, messagebox
import copy
import sys
import os
import platform
import subprocess
import shlex
import re
import threading
import queue
from pathlib import Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from hack_data_manager import HackDataManager
from ui.collection_components import InlineEditor, DateValidator, NotesValidator, HackCollectionInlineEditor
from ui.components.table_filters import TableFilters
from ui_constants import get_page_padding, get_section_padding
from file_explorer_utils import open_file_in_explorer, get_file_icon_unicode
from collection_wheel_model import CollectionWheelModel
from ui.collection_wheel_dialog import CollectionWheelDialog
from collection_rom_organization import build_collection_rom_organization_audit
from ui.collection_rom_organization_dialog import CollectionRomOrganizationAuditDialog
from collection_rom_modern_provenance_review import (
    ModernRomProvenanceReviewError,
    build_modern_rom_provenance_review,
)
from ui.collection_rom_modern_provenance_dialog import CollectionRomModernProvenanceDialog
from collection_rom_legacy_metadata import build_legacy_rom_metadata_audit
from ui.collection_rom_legacy_metadata_dialog import CollectionRomLegacyMetadataDialog
from collection_rom_legacy_provenance_review import (
    LegacyRomProvenanceReviewError,
    build_legacy_rom_provenance_review,
)
from ui.collection_rom_legacy_provenance_dialog import CollectionRomLegacyProvenanceDialog
from collection_rom_legacy_metadata_plan import (
    LegacyRomMetadataPlanError,
    build_legacy_rom_metadata_modernization_plan,
    build_reviewed_legacy_rom_metadata_modernization_plan,
)
from ui.collection_rom_legacy_metadata_plan_dialog import (
    CollectionRomLegacyMetadataPlanDialog,
)
from ui.collection_rom_legacy_provenance_plan_dialog import (
    CollectionRomLegacyProvenancePlanDialog,
)
from collection_rom_organization_plan import (
    CollectionRomOrganizationPlanError,
    build_collection_rom_organization_plan,
)
from ui.collection_rom_organization_plan_dialog import CollectionRomOrganizationPlanDialog
from collection_rom_save_impact import (
    CollectionRomSaveImpactError,
    build_collection_rom_save_impact_review,
)
from ui.collection_rom_save_impact_dialog import CollectionRomSaveImpactDialog
from collection_rom_organization_execution_plan import (
    CollectionRomOrganizationExecutionPlanError,
    build_collection_rom_organization_execution_plan,
)
from ui.collection_rom_organization_execution_plan_dialog import (
    CollectionRomOrganizationExecutionPlanDialog,
)
from collection_rom_historical_organization_execution_plan import (
    HistoricalRomOrganizationExecutionPlanError,
    build_historical_rom_organization_execution_plan,
)
from ui.collection_rom_historical_organization_execution_plan_dialog import (
    HistoricalRomOrganizationExecutionPlanDialog,
)

# Info icon unicode (using standard info symbol)
INFO_ICON = "ℹ"
from config_manager import ConfigManager

# Platform-specific cursor
HOVER_CURSOR = "pointinghand" if platform.system() == "Darwin" else "hand2"
from utils import get_sorted_folder_name, move_hack_to_new_difficulty, get_primary_type, format_types_display
from colors import get_colors
from collection_rating import (
    format_smwc_rating,
    migrate_smwc_rating_column,
    smwc_rating_sort_value,
)

from product_identity import VERSION

class CollectionPage:
    """Simplified hack collection page with extracted components"""

    def __init__(self, parent, logger=None):
        self.parent = parent
        self.frame = None
        self.logger = logger  # Add logger support
        self.data_manager = HackDataManager(logger=logger)
        self.collection_wheel_model = CollectionWheelModel()
        self.collection_wheel_dialog = None
        self.collection_rom_organization_audit_dialog = None
        self.collection_rom_modern_provenance_dialog = None
        self._last_collection_modern_provenance_review = None
        self._last_collection_modern_provenance_decision = None
        self.collection_rom_legacy_metadata_dialog = None
        self.collection_rom_legacy_metadata_plan_dialog = None
        self.collection_rom_legacy_provenance_dialog = None
        self.collection_rom_legacy_provenance_plan_dialog = None
        self._last_collection_legacy_provenance_review = None
        self._last_collection_legacy_provenance_decision = None
        self.collection_rom_historical_provenance_dialog = None
        self.collection_rom_historical_organization_plan_dialog = None
        self.collection_rom_historical_provenance_progress_dialog = None
        self._collection_rom_historical_provenance_busy = False
        self._collection_rom_historical_provenance_queue = queue.Queue()
        self._collection_rom_historical_provenance_poll_id = None
        self.collection_rom_organization_plan_dialog = None
        self.collection_rom_save_impact_dialog = None
        self.collection_rom_organization_execution_plan_dialog = None
        self.collection_rom_historical_organization_execution_plan_dialog = None
        self._last_collection_rom_save_disposition_review = None
        self._last_collection_rom_save_disposition_decision = None
        self._last_collection_historical_rom_save_disposition_review = None
        self._last_collection_historical_rom_save_disposition_decision = None
        self._last_collection_legacy_provenance_review = None
        self._last_collection_legacy_provenance_decision = None

        # v3.1 NEW: Pagination state
        self.current_page = 1
        self.page_size = 50  # Default page size
        self.total_pages = 1

        # Sorting state - Default to title ascending
        self.sort_column = "title"
        self.sort_reverse = False

        # Column Configuration (ID, Header, Width, MinWidth, Anchor)
        # DEFAULT_COLUMNS stores the original default order - never modified
        self.DEFAULT_COLUMNS = [
            {"id": "completed", "header": "✓", "width": 45, "min_width": 35, "anchor": "center"},
            {"id": "play", "header": "▶", "width": 35, "min_width": 25, "anchor": "center"},
            {"id": "folder", "header": get_file_icon_unicode(), "width": 35, "min_width": 25, "anchor": "center"},
            {"id": "title", "header": "Title", "width": 220, "min_width": 170, "anchor": "w"},
            {"id": "type", "header": "Type(s)", "width": 90, "min_width": 70, "anchor": "center"},
            {"id": "difficulty", "header": "Difficulty", "width": 100, "min_width": 80, "anchor": "center"},
            {"id": "rating", "header": "Personal Rating", "width": 115, "min_width": 95, "anchor": "center"},
            {"id": "smwc_rating", "header": "SMWC Rating", "width": 100, "min_width": 85, "anchor": "center"},
            {"id": "completed_date", "header": "Completed Date", "width": 110, "min_width": 90, "anchor": "center"},
            {"id": "time_to_beat", "header": "Time to Beat", "width": 120, "min_width": 100, "anchor": "center"},
            {"id": "release_date", "header": "Released", "width": 100, "min_width": 80, "anchor": "center"}, # NEW
            {"id": "notes", "header": "Notes", "width": 120, "min_width": 90, "anchor": "w"}
        ]

        # COLUMNS is the working copy that can be reordered based on user config
        self.COLUMNS = [col.copy() for col in self.DEFAULT_COLUMNS]

        # Load column visibility and order from config
        from config_manager import ConfigManager
        self.config_manager = ConfigManager()

        # Load visible columns and column order from config
        self.visible_columns = self.config_manager.get("visible_columns", [c["id"] for c in self.COLUMNS])
        column_order = self.config_manager.get("column_order", None)

        # Show the new SMWC rating column once for existing column
        # configurations, while preserving later user visibility choices.
        (
            self.visible_columns,
            column_order,
            rating_column_migrated,
        ) = migrate_smwc_rating_column(
            self.visible_columns,
            column_order,
        )
        if rating_column_migrated:
            self.config_manager.config["visible_columns"] = (
                self.visible_columns
            )
            self.config_manager.config["column_order"] = column_order
            self.config_manager.save()

        # If we have a saved column order, use it; otherwise use default order
        if column_order:
            ordered_columns = []
            # Add columns in saved order
            for col_id in column_order:
                col_def = next((c for c in self.COLUMNS if c["id"] == col_id), None)
                if col_def:
                    ordered_columns.append(col_def)

            # Add any new columns that might not be in saved order (for backward compatibility)
            existing_ids = [col["id"] for col in ordered_columns]
            for col in self.COLUMNS:
                if col["id"] not in existing_ids:
                    ordered_columns.append(col)

            self.COLUMNS = ordered_columns

        # Initialize components - USE HackCollectionInlineEditor instead of InlineEditor
        self.filters = TableFilters(self._apply_filters, self._open_collection_wheel)
        self.date_editor = HackCollectionInlineEditor(None, self.data_manager, self, logger)
        self.notes_editor = HackCollectionInlineEditor(None, self.data_manager, self, logger)
        self.time_editor = HackCollectionInlineEditor(None, self.data_manager, self, logger)  # v3.1 NEW

        # Track open dialogs to prevent duplicates
        self.column_config_dialog = None
        self.collection_ingestion_source_dialog = None
        self.collection_ingestion_progress_dialog = None
        self.collection_ingestion_review_dialog = None
        self.collection_ingestion_convergence_review_dialog = None
        self.collection_ingestion_finalization_progress_dialog = None
        self.collection_ingestion_plan_preview_dialog = None
        self.collection_ingestion_apply_progress_dialog = None
        self._collection_ingestion_busy = False
        self._collection_ingestion_result_queue = queue.Queue()
        self._collection_ingestion_poll_id = None
        self._active_collection_ingestion_session = None
        self._last_collection_ingestion_review_decisions = None
        self._last_collection_ingestion_convergence_decisions = None
        self._last_collection_ingestion_plan = None

        # Read-only, user-initiated SMWC update/replacement discovery and planning.
        self.collection_update_discovery_dialog = None
        self.collection_update_discovery_progress_dialog = None
        self._collection_update_discovery_busy = False
        self._collection_update_discovery_queue = queue.Queue()
        self._collection_update_discovery_poll_id = None
        self._last_collection_update_selection = None
        self.collection_update_merge_review_dialog = None
        self._last_collection_update_merge_review = None
        self._last_collection_update_merge_decision = None
        self.collection_update_plan_progress_dialog = None
        self.collection_update_plan_preview_dialog = None
        self.collection_update_apply_progress_dialog = None
        self.collection_update_rom_acquisition_progress_dialog = None
        self._collection_update_plan_busy = False
        self._collection_update_apply_busy = False
        self._collection_update_rom_acquisition_busy = False
        self._collection_update_plan_queue = queue.Queue()
        self._collection_update_plan_poll_id = None
        self._collection_update_rom_acquisition_queue = queue.Queue()
        self._collection_update_rom_acquisition_poll_id = None
        self._last_collection_update_plan = None

        # Same-SMWC-ID refresh/re-download stays separate from replacement semantics.
        self.collection_current_refresh_preview_dialog = None
        self.collection_current_refresh_progress_dialog = None
        self.collection_current_rom_disposition_dialog = None
        self._last_collection_current_rom_disposition_review = None
        self._collection_current_refresh_queue = queue.Queue()
        self._collection_current_refresh_poll_id = None
        self._last_collection_current_refresh_plan = None

        # Debounce timer for scrollbar toggle
        self.scrollbar_toggle_timer = None

        # Table and data
        self.tree = None
        self.filtered_data = []
        self.status_label = None

        # Cache ConfigManager instance and emulator path for performance
        self.config_manager = ConfigManager()
        self._emulator_path = self.config_manager.get("emulator_path", "")
        self._show_rom_picker = self.config_manager.get("show_rom_picker", False)

    def refresh_emulator_cache(self):
        """Refresh cached emulator settings - called when settings change"""
        old_path = self._emulator_path
        # Create NEW ConfigManager instance to reload config from disk
        self.config_manager = ConfigManager()
        self._emulator_path = self.config_manager.get("emulator_path", "")
        self._show_rom_picker = self.config_manager.get("show_rom_picker", False)
        self._log(f"🔄 Emulator cache refreshed: '{old_path}' -> '{self._emulator_path}'", "Debug")
        # Refresh table to update play icons
        if self.tree:
            self._log("🔄 Refreshing collection table to update play icons...", "Debug")
            self._refresh_table()
        else:
            self._log("⚠️ Tree not initialized yet, skipping table refresh", "Debug")

    def _log(self, message, level="Information"):
        """Log a message if logger is available"""
        if self.logger:
            self.logger.log(message, level)

    def create(self):
        """Create the hack collection page"""
        self.frame = ttk.Frame(self.parent, padding=get_page_padding())

        # Create filter section
        _, section_padding_y = get_section_padding()
        filter_frame = self.filters.create_filter_ui(self.frame, self.data_manager)
        filter_frame.pack(fill="x", pady=(0, section_padding_y))

        # Create download status indicator
        self.status_frame = ttk.Frame(self.frame)
        self.status_frame.pack(fill="x", pady=(0, 5))

        self.download_status_label = ttk.Label(
            self.status_frame,
            text="",
            font=("Segoe UI", 9, "bold"),
            foreground="#FF6B6B"  # Red color for warning
        )
        self.download_status_label.pack()

        # Register for download state changes
        try:
            from download_state_manager import register_callback
            register_callback(self._on_download_state_change)
        except ImportError:
            pass  # Download state manager not available

        # Connect refresh button
        # (This is a bit hacky but keeps the component simple)
        for widget in filter_frame.winfo_children():
            if isinstance(widget, ttk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Frame):
                        for grandchild in child.winfo_children():
                            if isinstance(grandchild, ttk.Button) and "Refresh" in grandchild.cget("text"):
                                grandchild.configure(command=self._refresh_data_and_table)

        # v3.1 NEW: Create pagination controls
        self._create_pagination_controls()

        # Create table section
        self._create_table()

        # Load initial data
        self._refresh_data_and_table()

        return self.frame

    def show(self):
        """Called when the page becomes visible"""
        if self.frame:
            # Only refresh when showing - don't duplicate if user just clicked refresh
            # Check if we need to refresh (e.g., returning from another page)
            total_hacks = len(self.data_manager.get_all_hacks())
            completed_hacks = sum(1 for hack in self.data_manager.get_all_hacks() if hack.get("completed", False))
            self._log(f"📊 Hack Collection page loaded - {total_hacks} total hacks, {completed_hacks} completed", "Information")

    def hide(self):
        """Called when the page becomes hidden"""
        self.date_editor.cleanup()
        self.notes_editor.cleanup()
        self.time_editor.cleanup()  # v3.1 NEW

    def cleanup(self):
        """Clean up resources and ensure data is saved"""
        # Unregister download state callback
        try:
            from download_state_manager import unregister_callback
            unregister_callback(self._on_download_state_change)
        except ImportError:
            pass

        if self.collection_wheel_dialog:
            self.collection_wheel_dialog.close()
            self.collection_wheel_dialog = None

        if self.collection_rom_organization_audit_dialog is not None:
            self.collection_rom_organization_audit_dialog.close()
            self.collection_rom_organization_audit_dialog = None

        if self.collection_rom_legacy_metadata_dialog is not None:
            self.collection_rom_legacy_metadata_dialog.close()
            self.collection_rom_legacy_metadata_dialog = None

        if self.collection_rom_legacy_metadata_plan_dialog is not None:
            self.collection_rom_legacy_metadata_plan_dialog.close()
            self.collection_rom_legacy_metadata_plan_dialog = None

        if self.collection_rom_legacy_provenance_dialog is not None:
            self.collection_rom_legacy_provenance_dialog.close()
            self.collection_rom_legacy_provenance_dialog = None

        if self.collection_rom_historical_organization_plan_dialog is not None:
            self.collection_rom_historical_organization_plan_dialog.close()
            self.collection_rom_historical_organization_plan_dialog = None

        if self.collection_rom_save_impact_dialog is not None:
            self.collection_rom_save_impact_dialog.close()
            self.collection_rom_save_impact_dialog = None

        if self.collection_rom_organization_execution_plan_dialog is not None:
            self.collection_rom_organization_execution_plan_dialog.close()
            self.collection_rom_organization_execution_plan_dialog = None

        if self.collection_rom_organization_plan_dialog is not None:
            self.collection_rom_organization_plan_dialog.close()
            self.collection_rom_organization_plan_dialog = None

        if self.collection_update_discovery_dialog is not None:
            self.collection_update_discovery_dialog.close()
            self.collection_update_discovery_dialog = None
        if self.collection_update_discovery_progress_dialog is not None:
            self.collection_update_discovery_progress_dialog.close()
            self.collection_update_discovery_progress_dialog = None
        if self._collection_update_discovery_poll_id is not None and self.frame:
            try:
                self.frame.after_cancel(self._collection_update_discovery_poll_id)
            except tk.TclError:
                pass
            self._collection_update_discovery_poll_id = None
        if self.collection_update_merge_review_dialog is not None:
            self.collection_update_merge_review_dialog.close()
            self.collection_update_merge_review_dialog = None
        if self.collection_update_plan_preview_dialog is not None:
            self.collection_update_plan_preview_dialog.close()
            self.collection_update_plan_preview_dialog = None
        if self.collection_update_plan_progress_dialog is not None:
            self.collection_update_plan_progress_dialog.close()
            self.collection_update_plan_progress_dialog = None
        if self.collection_update_apply_progress_dialog is not None:
            self.collection_update_apply_progress_dialog.close()
            self.collection_update_apply_progress_dialog = None
        if self.collection_update_rom_acquisition_progress_dialog is not None:
            self.collection_update_rom_acquisition_progress_dialog.close()
            self.collection_update_rom_acquisition_progress_dialog = None
        if self.collection_current_refresh_preview_dialog is not None:
            self.collection_current_refresh_preview_dialog.close()
            self.collection_current_refresh_preview_dialog = None
        if self.collection_current_refresh_progress_dialog is not None:
            self.collection_current_refresh_progress_dialog.close()
            self.collection_current_refresh_progress_dialog = None
        if self.collection_current_rom_disposition_dialog is not None:
            self.collection_current_rom_disposition_dialog.close()
            self.collection_current_rom_disposition_dialog = None
        if self._collection_current_refresh_poll_id is not None and self.frame:
            try:
                self.frame.after_cancel(self._collection_current_refresh_poll_id)
            except tk.TclError:
                pass
            self._collection_current_refresh_poll_id = None
        if self._collection_update_plan_poll_id is not None and self.frame:
            try:
                self.frame.after_cancel(self._collection_update_plan_poll_id)
            except tk.TclError:
                pass
            self._collection_update_plan_poll_id = None
        if self._collection_update_rom_acquisition_poll_id is not None and self.frame:
            try:
                self.frame.after_cancel(self._collection_update_rom_acquisition_poll_id)
            except tk.TclError:
                pass
            self._collection_update_rom_acquisition_poll_id = None

        # Force save any pending changes
        self.data_manager.force_save()

    def _on_download_state_change(self, download_active):
        """Handle download state changes"""
        if hasattr(self, 'download_status_label') and self.download_status_label:
            if download_active:
                self.download_status_label.config(
                    text="⚠️ Download in progress - Collection editing is temporarily disabled",
                    foreground="#FF6B6B"  # Red
                )
            else:
                self.download_status_label.config(text="", foreground="#4ECDC4")  # Clear text

    def _create_table(self):
        """Create the main data table"""
        table_frame = ttk.Frame(self.frame)
        table_frame.pack(fill="both", expand=True)

        # Create treeview with custom Collection style
        column_ids = [col["id"] for col in self.COLUMNS]
        self.tree = ttk.Treeview(table_frame, columns=column_ids, show="headings", height=15, style="Collection.Treeview")

        # Configure headers and columns
        for col_config in self.COLUMNS:
            col_id = col_config["id"]
            self.tree.heading(col_id, text=col_config["header"], command=lambda c=col_id: self._sort_by_column(c))
            self.tree.column(col_id, width=col_config["width"], minwidth=col_config["min_width"], anchor=col_config["anchor"])

        # Set initial visibility
        self.tree["displaycolumns"] = self.visible_columns

        # Scrollbars
        v_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.h_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=self.h_scrollbar.set)

        # Grid layout
        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        self.h_scrollbar.grid_remove()

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Configure editors with tree reference
        self.date_editor.tree = self.tree
        self.notes_editor.tree = self.tree
        self.time_editor.tree = self.tree  # v3.1 NEW

        # Bind events
        self.tree.bind("<Button-1>", self._on_item_click)
        self.tree.bind("<Double-1>", self._on_item_double_click)
        self.tree.bind("<Motion>", self._on_mouse_motion)
        self.tree.bind("<Configure>", lambda e: self._toggle_h_scrollbar(self.h_scrollbar))

        # Status label - positioned in a footer frame after pagination
        footer_frame = ttk.Frame(self.frame)
        footer_frame.pack(fill="x", pady=(23, 0))  # Increased top padding from 5 to 20

        self.status_label = ttk.Label(footer_frame, text="", font=("Segoe UI", 9))
        self.status_label.pack(anchor="center")

    def _refresh_data_and_table(self):
        """Reload all data and refresh the table"""
        # Guard against duplicate calls
        if hasattr(self, '_is_refreshing') and self._is_refreshing:
            self._log("DEBUG: Skipping duplicate refresh call", "Debug")
            return

        self._is_refreshing = True

        try:
            # Debug: Add stack trace to find duplicate calls
            import traceback
            stack_summary = traceback.extract_stack()
            self._log(f"DEBUG: _refresh_data_and_table called from {stack_summary[-2].filename.split('/')[-1].split(chr(92))[-1]}:{stack_summary[-2].lineno}", "Debug")

            self.config_manager.reload()  # Reload config to get latest emulator settings
            # CRITICAL: Force save any pending changes before refreshing to prevent data loss
            if hasattr(self.data_manager, 'unsaved_changes') and self.data_manager.unsaved_changes:
                self._log("💾 Saving pending changes before refresh to prevent data loss...", "Information")
                if self.data_manager.force_save():
                    pass # Saved successfully
                else:
                    self._log("❌ Failed to save changes before refresh", "Error")

            # Reload data from disk to pick up external changes (e.g. metadata fetch)
            self.data_manager.reload_data()
            self.filters.refresh_dropdown_values(self.data_manager)

            # Apply filters and sorting
            self._apply_filters()
            self._refresh_table()

            self._log(f"🔄 Refreshed hack data from file", "Debug")
        finally:
            self._is_refreshing = False

    def _refresh_table(self):
        """Refresh table data with pagination and sorting"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Get filtered data - include obsolete hacks so table filters can handle them
        all_hacks = self.data_manager.get_all_hacks(include_obsolete=True)
        self.filtered_data = self.filters.apply_filters(all_hacks)

        # Apply sorting
        self._sort_filtered_data()

        # Update column headers to show sort indicators
        self._update_column_headers()

        # Calculate pagination
        total_hacks = len(self.filtered_data)
        self.total_pages = max(1, (total_hacks + self.page_size - 1) // self.page_size)

        # Ensure current page is valid
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
            self.page_var.set(str(self.current_page))

        # Calculate page slice
        start_index = (self.current_page - 1) * self.page_size
        end_index = min(start_index + self.page_size, total_hacks)
        page_data = self.filtered_data[start_index:end_index]

        # Populate table with page data
        for hack in page_data:
            self._insert_hack_row(hack)

        # Update status with pagination info
        if total_hacks > self.page_size:
            sort_info = f" (sorted by {self.sort_column})" if self.sort_column else ""
            status_text = f"Showing {len(page_data)} of {total_hacks} hack(s) (Page {self.current_page} of {self.total_pages}){sort_info}"
        else:
            sort_info = f" (sorted by {self.sort_column})" if self.sort_column else ""
            status_text = f"Displaying {total_hacks} hack(s){sort_info}"
        self._update_status_label(len(all_hacks), total_hacks, status_text)

        # Update pagination controls
        self._update_pagination_controls()

    def _insert_hack_row(self, hack):
        """Insert a single hack row into the table"""
        completed_display = "✓" if hack.get("completed", False) else ""
        rating_display = self._get_rating_display(hack.get("personal_rating", 0))
        smwc_rating_display = format_smwc_rating(hack.get("rating", 0))

        notes_display = hack.get("notes", "")
        if len(notes_display) > 30:
            notes_display = notes_display[:30] + "..."

        # v3.1 NEW: Format time to beat display
        time_to_beat_display = self._format_time_display(hack.get("time_to_beat", 0))

        hack_id = hack.get("id")

        # Use new helper function for type display
        hack_types = hack.get("hack_types", []) or [hack.get("hack_type", "standard")]
        type_display = format_types_display(hack_types)

        # Check if hack file exists for folder icon display
        file_path = hack.get("file_path", "")
        folder_icon = get_file_icon_unicode() if file_path and os.path.exists(file_path) else ""

        # Check if emulator is configured for play icon display
        play_icon = self._get_play_icon(hack)

        release_date = hack.get("date", "")
        if not release_date and hack.get("time"):
            try:
                from datetime import datetime
                ts = int(hack.get("time"))
                release_date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            except:
                pass

        # Prepare values dict for easy mapping
        row_data = {
            "completed": completed_display,
            "play": play_icon,
            "folder": folder_icon,
            "title": hack["title"],
            "type": type_display,
            "difficulty": hack.get("difficulty", "Unknown"),
            "rating": rating_display,
            "smwc_rating": smwc_rating_display,
            "completed_date": hack.get("completed_date", ""),
            "time_to_beat": time_to_beat_display,
            "release_date": release_date,  # Updated
            "notes": notes_display
        }

        # Build values tuple using the treeview's fixed creation-time column order.
        # IMPORTANT: self.COLUMNS may be reordered by _apply_column_config, but the
        # treeview's internal 'columns' definition never changes after creation.
        # Using self.COLUMNS here would cause values to land in the wrong cells
        # on any subsequent refresh (e.g. after a sort trigger).
        values = [row_data.get(col_id, "") for col_id in self.tree["columns"]]

        self.tree.insert("", "end", values=values, tags=(hack_id,))

    def _update_status_label(self, total_count, filtered_count, custom_text=None):
        """Update the status label"""
        if custom_text:
            # Use custom text when provided (for pagination)
            status_text = custom_text
        else:
            # Use default format
            completed_count = sum(1 for hack in self.filtered_data if hack.get("completed", False))
            status_text = f"Showing {filtered_count} of {total_count} hacks"
            if filtered_count > 0:
                status_text += f" • {completed_count} completed"
        self.status_label.config(text=status_text)

    def _apply_filters(self):
        """Apply filters and refresh table"""
        self._refresh_table()

    def _open_collection_wheel(self):
        """Open one Wheel dialog for the full Collection."""
        if (
            self.collection_wheel_dialog
            and self.collection_wheel_dialog.is_open
        ):
            self.collection_wheel_dialog.lift()
            return

        self.collection_wheel_model.reload_planner_state()
        self.config_manager.reload()
        self.collection_wheel_dialog = CollectionWheelDialog(
            self.frame.winfo_toplevel(),
            self.collection_wheel_model,
            collection_records=self.data_manager.get_all_hacks(include_obsolete=True),
            result_callback=self._focus_wheel_result,
            on_close=self._on_collection_wheel_closed,
            planner_features_visible=self.config_manager.get(
                "show_planner", True
            ),
        )
    def _on_collection_wheel_closed(self):
        self.collection_wheel_dialog = None

    def _focus_wheel_result(self, hack_id):
        """Reveal and select a Wheel result in Collection."""
        hack_id_text = str(hack_id)

        def find_result_index():
            for index, hack in enumerate(self.filtered_data):
                if str(hack.get("id")) == hack_id_text:
                    return index
            return None

        result_index = find_result_index()
        if result_index is None:
            self.filters.clear_filters()
            result_index = find_result_index()

        if result_index is None:
            self._log(
                f"⚠️ Collection Wheel result {hack_id} could not be shown",
                "Warning",
            )
            return

        hack = self.filtered_data[result_index]
        target_page = (result_index // self.page_size) + 1
        if target_page != self.current_page:
            self.current_page = target_page
            self.page_var.set(str(self.current_page))
            self._refresh_table()

        self._select_hack_in_tree(hack_id)
        self._log(
            "🎡 Collection Wheel selected "
            f"'{hack.get('title', 'Unknown')}' (ID: {hack_id})",
            "Information",
        )
    def _select_hack_in_tree(self, hack_id):
        """Find a hack in the current tree view, select it, and ensure it's visible"""
        hack_id_str = str(hack_id)

        # Iterate through tree items to find the match
        for item in self.tree.get_children():
            tags = self.tree.item(item)["tags"]
            if tags and str(tags[0]) == hack_id_str:
                # Found it!
                self.tree.selection_set(item)
                self.tree.focus(item)
                self.tree.see(item)
                return

        self._log(f"⚠️ Could not find hack {hack_id} in tree view", "Warning")

    def _on_item_click(self, event):
        """Handle single clicks on table items"""
        # Check if download is active - prevent editing during downloads
        try:
            from download_state_manager import is_download_active
            if is_download_active():
                messagebox.showwarning(
                    "Download in Progress",
                    "Cannot edit hack collection while a download is in progress.\n\n"
                    "Please wait for the download to complete or cancel it before making changes."
                )
                return
        except ImportError:
            pass  # If download state manager not available, allow editing

        # Save any active edits first
        if self.date_editor.entry:
            self.date_editor.save()

        if self.notes_editor.entry:
            self.notes_editor.save()

        # v3.1 NEW: Save time editor if active
        if self.time_editor.entry:
            self.time_editor.save()

        # Identify clicked item and column
        item = self.tree.identify("item", event.x, event.y)
        column = self.tree.identify("column", event.x, event.y)

        if not item or not column:
            return

        # Get hack ID from tags
        tags = self.tree.item(item)["tags"]
        if not tags:
            return
        hack_id = tags[0]

        hack_id = tags[0]

        col_id = self._get_column_id(column)
        if not col_id:
            return

        # Handle different column clicks
        if col_id == "completed":
            self._toggle_completed(hack_id)
        elif col_id == "play":
            self._launch_emulator(hack_id)
        elif col_id == "folder":
            self._open_hack_in_explorer(hack_id)
        elif col_id == "rating":
            self._edit_rating(hack_id, item, event, col_id)
        elif col_id == "completed_date":
            self.date_editor.start_edit(hack_id, item, event, "completed_date", col_id, DateValidator.validate)
        elif col_id == "time_to_beat":
            self.time_editor.start_edit(hack_id, item, event, "time_to_beat", col_id, self._validate_time_input)
        elif col_id == "notes":
            self.notes_editor.start_edit(hack_id, item, event, "notes", col_id, NotesValidator.validate)

    def _get_column_id(self, col_idx_str):
        """Convert treeview display column index (e.g. '#1') to logical column ID.

        tree.identify('column', x, y) returns '#N' where N is the 1-based position
        within the *displayed* columns (i.e. tree['displaycolumns'] order).  Using
        self.COLUMNS for this mapping breaks whenever the user reorders columns,
        because self.COLUMNS is mutated by _apply_column_config while the treeview
        tracks display order independently via displaycolumns.
        """
        try:
            idx = int(col_idx_str.replace("#", "")) - 1

            # Resolve against the live displaycolumns list; fall back to the full
            # columns tuple when all columns are shown (displaycolumns == columns).
            display_cols = self.tree["displaycolumns"]
            # tkinter returns ('',) or an empty tuple when nothing is explicitly set;
            # guard against that by falling back to the complete column list.
            if not display_cols or (len(display_cols) == 1 and display_cols[0] in ("", "#all")):
                display_cols = self.tree["columns"]

            if 0 <= idx < len(display_cols):
                return display_cols[idx]
            return None
        except (ValueError, IndexError):
            return None

    def _on_item_double_click(self, event):
        """Handle double click - show edit hack dialog"""
        # Check if download is active - prevent editing during downloads
        try:
            from download_state_manager import is_download_active
            if is_download_active():
                messagebox.showwarning(
                    "Download in Progress",
                    "Cannot edit hack collection while a download is in progress.\n\n"
                    "Please wait for the download to complete or cancel it before making changes."
                )
                return
        except ImportError:
            pass  # If download state manager not available, allow editing

        item = self.tree.identify("item", event.x, event.y)
        if not item:
            return

        tags = self.tree.item(item)["tags"]
        if not tags:
            return
        hack_id = tags[0]

        # Find hack data and show edit dialog
        for hack in self.filtered_data:
            if str(hack.get("id")) == str(hack_id):
                self.filters.show_edit_hack_dialog(hack, hack_id)
                break

    def _on_mouse_motion(self, event):
        """Change cursor when hovering over clickable columns"""
        item = self.tree.identify("item", event.x, event.y)
        column = self.tree.identify("column", event.x, event.y)

        col_id = self._get_column_id(column)
        clickable_cols = ["completed", "play", "folder", "info", "rating", "completed_date", "time_to_beat", "notes"]

        if item and col_id in clickable_cols:
            self.tree.config(cursor=HOVER_CURSOR)

            # ENHANCED: Show rating preview on hover
            if col_id == "rating":
                self._show_rating_preview(item, event, column)
        else:
            self.tree.config(cursor="")

    def _show_info_dialog(self, hack_id):
        """Show the hack info dialog"""
        hack_data = self._find_hack_data(str(hack_id))
        if hack_data:
            dialog = HackInfoDialog(self.parent, hack_data)
            dialog.show()

    def _show_column_config(self):
        """Show column configuration dialog"""
        # Prevent multiple dialogs from opening
        if self.column_config_dialog is not None:
            try:
                # If dialog still exists, focus it instead of opening a new one
                self.column_config_dialog.dialog.lift()
                self.column_config_dialog.dialog.focus_force()
                return
            except:
                # Dialog was closed, reset the reference
                self.column_config_dialog = None

        from ui.components.column_config_dialog import ColumnConfigDialog

        self.column_config_dialog = ColumnConfigDialog(
            self.parent,
            self.COLUMNS,
            self.visible_columns,
            self._apply_column_config,
            self.config_manager,
            self.DEFAULT_COLUMNS  # Pass original default order
        )

        # Clear reference when dialog is closed
        def on_dialog_close():
            self.column_config_dialog = None

        self.column_config_dialog.show()

        # Bind to dialog destruction to clear reference
        if self.column_config_dialog.dialog:
            self.column_config_dialog.dialog.bind("<Destroy>", lambda e: on_dialog_close())

    def _apply_column_config(self, new_visible_cols):
        """Apply new column configuration"""
        self.visible_columns = new_visible_cols

        # Reload config to get updated column_order and visible_columns
        self.config_manager.reload()
        column_order = self.config_manager.get("column_order", None)
        updated_visible = self.config_manager.get("visible_columns", new_visible_cols)

        # Reorder COLUMNS based on column_order (if available)
        if column_order:
            ordered_columns = []
            for col_id in column_order:
                col_def = next((c for c in self.COLUMNS if c["id"] == col_id), None)
                if col_def:
                    ordered_columns.append(col_def)

            # Add any new columns not in saved order
            existing_ids = [col["id"] for col in ordered_columns]
            for col in self.COLUMNS:
                if col["id"] not in existing_ids:
                    ordered_columns.append(col)

            self.COLUMNS = ordered_columns

        # Update table visibility
        self.tree["displaycolumns"] = updated_visible

        # Force scrollbar update after column change
        self.tree.update_idletasks()
        self._toggle_h_scrollbar(self.h_scrollbar)

    def _show_rating_preview(self, item, event, col_idx_str):
        """Show preview of which star would be selected"""
        # Get hack data
        tags = self.tree.item(item)["tags"]
        if not tags:
            return
        hack_id = str(tags[0])
        hack_data = self._find_hack_data(hack_id)
        if not hack_data:
            return

        # Calculate which star would be selected (same logic as _edit_rating)
        # Use the column index string passed from event
        bbox = self.tree.bbox(item, col_idx_str)
        if not bbox:
            return

        cell_x = event.x - bbox[0]
        cell_width = bbox[2]

        margin = cell_width * 0.02
        usable_width = cell_width - (margin * 2)
        star_zone_width = usable_width / 5
        adjusted_x = cell_x - margin

        # Calculate relative position for star mapping
        relative_pos = cell_x / cell_width

        # Custom zones based on actual user clicks
        if relative_pos <= 0.30:     # 0-30% = star 1 (your click at 24.8% was star 1)
            preview_rating = 1
        elif relative_pos <= 0.45:   # 30-45% = star 2
            preview_rating = 2
        elif relative_pos <= 0.60:   # 45-60% = star 3
            preview_rating = 3
        elif relative_pos <= 0.72:   # 60-72% = star 4
            preview_rating = 4
        else:                        # 72-100% = star 5 (your click at 74.3% was star 5)
            preview_rating = 5

        # Optional: Update tooltip or status to show preview
        # For now, just ensure the cursor indicates interactivity
        self.tree.config(cursor=HOVER_CURSOR)

    def _toggle_completed(self, hack_id):
        """Toggle completed status for a hack"""
        hack_id_str = str(hack_id)

        # Find hack data
        hack_data = self._find_hack_data(hack_id_str)
        if not hack_data:
            return

        # Toggle completed status
        new_completed = not hack_data.get("completed", False)

        if self.data_manager.update_hack(hack_id_str, "completed", new_completed):
            hack_data["completed"] = new_completed

            # Auto-set/clear completion date ONLY if date field is empty
            if new_completed and not hack_data.get("completed_date"):
                from datetime import datetime
                today = datetime.now().strftime("%Y-%m-%d")
                hack_data["completed_date"] = today
                if self.data_manager.update_hack(hack_id_str, "completed_date", today):
                    self._log(f"✅ Automatically set completion date to {today} for '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str})", "Debug")
                else:
                    self._log(f"❌ Failed to auto-set completion date for '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str})", "Error")
            elif not new_completed:
                # Clear the date when unchecking completed
                hack_data["completed_date"] = ""
                if self.data_manager.update_hack(hack_id_str, "completed_date", ""):
                    self._log(f"📅 Cleared completion date for '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str}) - marked as not completed", "Debug")
                else:
                    self._log(f"❌ Failed to clear completion date for '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str})", "Error")

            # Update the specific tree item directly (same as inline editing)
            for item in self.tree.get_children():
                item_tags = self.tree.item(item)["tags"]
                if item_tags and str(item_tags[0]) == str(hack_id_str):
                    # Get current values
                    current_values = list(self.tree.item(item)["values"])

                    # Update completed checkbox (use treeview's fixed column order,
                    # NOT self.COLUMNS which may be reordered by the user)
                    tree_cols = list(self.tree["columns"])
                    try:
                        completed_col_idx = tree_cols.index("completed")
                        current_values[completed_col_idx] = "✓" if new_completed else ""
                    except ValueError:
                        # "completed" column might be hidden or missing
                        pass

                    # Update completion date if it changed dynamically
                    try:
                        date_col_idx = tree_cols.index("completed_date")
                        current_values[date_col_idx] = hack_data.get("completed_date", "")
                    except ValueError:
                        pass # Column might be hidden/missing

                    # Update the tree item
                    self.tree.item(item, values=current_values)
                    completion_status = "✅ completed" if new_completed else "❌ not completed"
                    self._log(f"🔄 Updated completion status for '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str}) - now marked as {completion_status}", "Information")
                    break

    def _edit_rating(self, hack_id, item, event, col_id="rating"):
        """Handle rating clicks - improved star detection"""
        hack_id_str = str(hack_id)
        hack_data = self._find_hack_data(hack_id_str)
        if not hack_data:
            return

        # Get cell position using column ID
        bbox = self.tree.bbox(item, col_id)
        if not bbox:
            return

        cell_x = event.x - bbox[0]
        cell_width = bbox[2]

        # IMPROVED: Use character-based calculation
        # Each star character is roughly equal width in monospace display
        # Divide cell into 5 equal click zones with small margins
        margin = cell_width * 0.02  # Reduced margin to 2%
        usable_width = cell_width - (margin * 2)
        star_zone_width = usable_width / 5
        adjusted_x = cell_x - margin

        # Determine which star zone was clicked
        # Based on actual click testing - adjusted zones to match visual star positions
        relative_pos = cell_x / cell_width

        # Custom zones based on actual user clicks
        if relative_pos <= 0.30:     # 0-30% = star 1 (your click at 24.8% was star 1)
            star_position = 1
        elif relative_pos <= 0.45:   # 30-45% = star 2
            star_position = 2
        elif relative_pos <= 0.60:   # 45-60% = star 3
            star_position = 3
        elif relative_pos <= 0.72:   # 60-72% = star 4
            star_position = 4
        else:                        # 72-100% = star 5 (your click at 74.3% was star 5)
            star_position = 5

        self._log(f"🌟 Rating click detected for '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str}) - position: {relative_pos:.1%}, targeting star {star_position}", "Debug")

        # Update rating - if clicking same rating, set to 0 (clear rating)
        current_rating = hack_data.get("personal_rating", 0)
        new_rating = 0 if current_rating == star_position else star_position

        if self.data_manager.update_hack(hack_id_str, "personal_rating", new_rating):
            hack_data["personal_rating"] = new_rating

            # IMPROVED: Use optimized tree update instead of full refresh
            for tree_item in self.tree.get_children():
                item_tags = self.tree.item(tree_item)["tags"]
                if item_tags and str(item_tags[0]) == str(hack_id_str):
                    # Get current values
                    current_values = list(self.tree.item(tree_item)["values"])

                    # Update rating in the correct column (use treeview's fixed column
                    # order, NOT self.COLUMNS which may be reordered by the user)
                    try:
                        rating_col_idx = list(self.tree["columns"]).index("rating")
                        current_values[rating_col_idx] = self._get_rating_display(new_rating)
                    except ValueError:
                        pass

                    # Update the tree item
                    self.tree.item(tree_item, values=current_values)

                    # User-friendly logging
                    if new_rating == 0:
                        self._log(f"⭐ Cleared rating for '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str})", "Information")
                    else:
                        stars_text = "★" * new_rating + "☆" * (5 - new_rating)
                        self._log(f"⭐ Rated '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str}) as {new_rating}/5 stars [{stars_text}]", "Information")
                    break
        else:
            self._log(f"❌ Failed to update rating for '{hack_data.get('title', 'Unknown')}' (hack #{hack_id_str}) - data manager update failed", "Error")

    def _open_hack_in_explorer(self, hack_id):
        """Open the hack file location in the system file explorer"""

        hack_data = self._find_hack_data(hack_id)
        if not hack_data:
            return

        file_path = hack_data.get("file_path", "")
        hack_title = hack_data.get("title", "Unknown")

        # Silently return if no file path (hack not downloaded) - don't show error
        if not file_path:
            return

        # Only show error if file_path exists but file is missing (was moved/deleted)
        if not os.path.exists(file_path):
            self._log(f"⚠️ File not found: {file_path} for '{hack_title}'", "Warning")
            messagebox.showwarning(
                "File Not Found",
                f"The file for '{hack_title}' could not be found:\n\n"
                f"{file_path}\n\n"
                f"The file may have been moved or deleted."
            )
            return

        # Try to open the file in the system explorer
        success = open_file_in_explorer(file_path)

        if success:
            self._log(f"📂 Opened file location for '{hack_title}' in system explorer", "Information")
        else:
            # Fallback message if the explorer couldn't be opened
            self._log(f"❌ Failed to open file explorer for '{hack_title}'", "Error")
            messagebox.showerror(
                "Explorer Error",
                f"Could not open file explorer for '{hack_title}'.\n\n"
                f"File path: {file_path}"
            )

    def _get_play_icon(self, hack):
        """Get play icon if emulator is configured and file exists"""
        # Only show play icon if emulator is configured and file exists
        # Use cached emulator path for performance
        file_path = hack.get("file_path", "")
        if self._emulator_path and file_path and os.path.exists(file_path):
            return "▶"
        return ""

    def _convert_app_to_executable(self, app_path):
        """Convert macOS .app bundle path to actual executable path"""
        # Extract app name from path
        app_name = os.path.basename(app_path).replace(".app", "")

        # Standard macOS app structure: AppName.app/Contents/MacOS/AppName
        executable_path = os.path.join(app_path, "Contents", "MacOS", app_name)

        # Check if the standard executable exists
        if os.path.exists(executable_path):
            self._log(f"Converted .app bundle to executable: {executable_path}", "Debug")
            return executable_path

        # Fallback: Try to find any executable in Contents/MacOS/
        macos_dir = os.path.join(app_path, "Contents", "MacOS")
        if os.path.exists(macos_dir):
            for file in os.listdir(macos_dir):
                file_path = os.path.join(macos_dir, file)
                if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                    self._log(f"Found executable in .app bundle: {file_path}", "Debug")
                    return file_path

        # If no executable found, return original path with warning
        self._log(f"Could not find executable in .app bundle, using bundle path", "Warning")
        return app_path

    def _parse_emulator_args(self, args_string):
        """Parse emulator arguments string into a list, handling platform-specific quoting.

        Args:
            args_string: String containing emulator arguments

        Returns:
            List of parsed argument strings
        """
        if platform.system() == "Windows":
            # Windows: Split by spaces but keep quoted strings together
            # Use a more efficient regex pattern to avoid ReDoS vulnerability
            parts = re.findall(r'[^\s"]+|"[^"]*"', args_string)
            # Remove quotes only from fully-quoted strings
            return [p[1:-1] if p.startswith('"') and p.endswith('"') else p for p in parts]
        else:
            # Unix: use shlex for proper quote handling
            return shlex.split(args_string)

    def _normalize_emulator_arg(self, arg):
        """Normalize a single emulator argument token (expand ~, env vars, and common macOS RetroArch mistakes)."""
        if not arg:
            return arg

        expanded = os.path.expanduser(os.path.expandvars(arg))

        # Common macOS path typo: "Application/Support" instead of "Application Support"
        if platform.system() == "Darwin" and "/Library/Application/Support/" in expanded:
            alt = expanded.replace("/Library/Application/Support/", "/Library/Application Support/")
            # Prefer the correct path if it exists; otherwise fall back only if original exists.
            if os.path.exists(alt) or not os.path.exists(expanded):
                expanded = alt

        # Common macOS RetroArch core extension mismatch: .dll -> .dylib
        if platform.system() == "Darwin" and expanded.lower().endswith(".dll"):
            alt = expanded[:-4] + ".dylib"
            if os.path.exists(alt) and not os.path.exists(expanded):
                expanded = alt

        return expanded

    def _build_emulator_command(self, emulator_path, emulator_args, emulator_args_enabled, rom_path):
        """Build a safe subprocess command list for launching the emulator."""
        command = [emulator_path]
        rom_added = False

        if emulator_args_enabled and emulator_args:
            placeholders = ("%1", "$1", "{rom}", "{ROM}")
            if any(ph in emulator_args for ph in placeholders):
                args_with_rom = emulator_args
                for ph in placeholders:
                    args_with_rom = args_with_rom.replace(ph, rom_path)
                parsed = self._parse_emulator_args(args_with_rom)
                rom_added = True
            else:
                parsed = self._parse_emulator_args(emulator_args)

            normalized = [self._normalize_emulator_arg(a) for a in parsed]

            # Users sometimes paste a full command line including the emulator path.
            # If the first token matches the emulator executable (or macOS .app bundle), drop it.
            if normalized:
                try:
                    first = os.path.normpath(normalized[0])
                    exe_norm = os.path.normpath(emulator_path)
                    bundle_path = self._find_macos_app_bundle(emulator_path)
                    bundle_norm = os.path.normpath(bundle_path) if bundle_path else None

                    if first == exe_norm or (bundle_norm and first == bundle_norm):
                        normalized = normalized[1:]
                except Exception:
                    pass

            command.extend(normalized)

        if not rom_added:
            command.append(rom_path)

        return command

    def _find_macos_app_bundle(self, executable_path):
        """If executable_path is inside a .app bundle, return the bundle path, else None."""
        if platform.system() != "Darwin" or not executable_path:
            return None

        # Typical layout: <App>.app/Contents/MacOS/<binary>
        marker = ".app/Contents/MacOS/"
        idx = executable_path.find(marker)
        if idx == -1:
            return None

        bundle_path = executable_path[: idx + len(".app")]
        if os.path.isdir(bundle_path):
            return bundle_path
        return None

    def _pick_rom_file(self, hack_title, files):
        """Show a dialog to pick which ROM to launch when multiple files exist.
        Returns the selected file path, or None if the user cancelled."""
        import tkinter as tk
        from tkinter import ttk
        from utils import set_window_icon

        result = {"path": None}

        dialog = tk.Toplevel(self.frame)
        dialog.title("Choose Version")
        dialog.resizable(False, False)
        dialog.transient(self.frame.winfo_toplevel())
        dialog.grab_set()
        set_window_icon(dialog)

        outer = ttk.Frame(dialog, padding=(24, 20, 24, 20))
        outer.pack(fill="both", expand=True)

        # Header
        ttk.Label(
            outer,
            text=f"Multiple versions found for \"{hack_title}\"",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            outer,
            text="Select which version to launch:",
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(0, 10))

        # Radio button for each file
        primary_idx = next((i for i, f in enumerate(files) if f.get("primary")), 0)
        selected_var = tk.StringVar(value=str(primary_idx))

        for i, f in enumerate(files):
            display = f.get("name") or os.path.basename(f.get("path", ""))
            if f.get("primary"):
                display += "  ★"
            row = ttk.Frame(outer)
            row.pack(fill="x", pady=3)
            ttk.Radiobutton(
                row,
                text=display,
                variable=selected_var,
                value=str(i),
            ).pack(side="left", padx=(4, 0))

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(12, 0))

        btn_frame = ttk.Frame(outer)
        btn_frame.pack(fill="x", pady=(12, 0))

        def on_launch():
            result["path"] = files[int(selected_var.get())].get("path", "")
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        ttk.Button(btn_frame, text="Cancel", command=on_cancel, width=12).pack(side="right", padx=(8, 0))
        ttk.Button(btn_frame, text="Launch", style="Accent.TButton", command=on_launch, width=14).pack(side="right")

        dialog.bind("<Return>", lambda _: on_launch())
        dialog.bind("<Escape>", lambda _: on_cancel())

        # Centre on parent, enforce minimum width
        dialog.update_idletasks()
        pw = self.frame.winfo_toplevel()
        dw = max(dialog.winfo_reqwidth(), 460)
        dh = dialog.winfo_reqheight()
        x = pw.winfo_x() + (pw.winfo_width() - dw) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{x}+{y}")

        dialog.wait_window()
        return result["path"]

    def _launch_emulator(self, hack_id):
        """Launch the emulator with the ROM file"""
        hack_data = self._find_hack_data(hack_id)
        if not hack_data:
            return

        hack_title = hack_data.get("title", "Unknown")

        # Determine which file to launch
        files = hack_data.get("files", [])
        if len(files) > 1 and self._show_rom_picker:
            file_path = self._pick_rom_file(hack_title, files)
            if not file_path:
                return  # User cancelled
        else:
            file_path = hack_data.get("file_path", "")

        # Check if file exists
        if not file_path or not os.path.exists(file_path):
            self._log(f"⚠️ Cannot launch '{hack_title}' - file not found", "Warning")
            messagebox.showwarning(
                "File Not Found",
                f"The ROM file for '{hack_title}' could not be found:\n\n"
                f"{file_path}\n\n"
                f"The file may have been moved or deleted."
            )
            return

        # Load emulator configuration from cached instance
        emulator_path = (self.config_manager.get("emulator_path", "") or "").strip()
        emulator_args = self.config_manager.get("emulator_args", "")
        emulator_args_enabled = self.config_manager.get("emulator_args_enabled", False)

        system = platform.system()

        # macOS: Convert .app bundle to executable if needed
        if system == "Darwin" and emulator_path:
            # Normalize possible trailing slash and handle case-insensitive suffix
            emulator_path_normalized = emulator_path.rstrip("/")
            if emulator_path_normalized.lower().endswith(".app") and os.path.isdir(emulator_path_normalized):
                emulator_path = self._convert_app_to_executable(emulator_path_normalized)

        if not emulator_path:
            self._log("⚠️ No emulator configured", "Warning")
            messagebox.showwarning(
                "No Emulator Configured",
                "Please configure an emulator in Settings before launching games."
            )
            return

        if not os.path.exists(emulator_path):
            self._log(f"⚠️ Emulator not found: {emulator_path}", "Warning")
            messagebox.showwarning(
                "Emulator Not Found",
                f"The configured emulator could not be found:\n\n"
                f"{emulator_path}\n\n"
                f"Please check your emulator settings."
            )
            return

        # Security: Validate emulator path points to an actual file (not a directory)
        if not os.path.isfile(emulator_path):
            self._log(f"⚠️ Emulator path is not a file: {emulator_path}", "Warning")
            messagebox.showwarning(
                "Invalid Emulator",
                f"The configured emulator path is not a valid file:\n\n"
                f"{emulator_path}\n\n"
                f"Please configure a valid emulator executable in Settings."
            )
            return

        # Security: Normalize path first to prevent bypassing validation
        emulator_path = os.path.normpath(emulator_path)
        if not os.path.isabs(emulator_path):
            self._log(f"⚠️ Emulator path must be absolute: {emulator_path}", "Warning")
            messagebox.showwarning(
                "Invalid Emulator Path",
                f"The configured emulator path must be an absolute path.\n\n"
                f"Please configure a valid emulator path in Settings."
            )
            return

        # Security: Check if file is executable
        if platform.system() == "Windows":
            # Windows: Validate file has an executable extension
            valid_extensions = ('.exe', '.bat', '.cmd', '.com')
            if not emulator_path.lower().endswith(valid_extensions):
                self._log(f"⚠️ Emulator is not a valid executable: {emulator_path}", "Warning")
                messagebox.showwarning(
                    "Invalid Emulator",
                    f"The configured emulator must be a valid executable file (.exe, .bat, .cmd, or .com):\n\n"
                    f"{emulator_path}\n\n"
                    f"Please configure a valid emulator in Settings."
                )
                return
        else:
            # Unix/macOS: Check if file is executable
            if not os.access(emulator_path, os.X_OK):
                self._log(f"⚠️ Emulator is not executable: {emulator_path}", "Warning")
                messagebox.showwarning(
                    "Emulator Not Executable",
                    f"The configured emulator is not executable:\n\n"
                    f"{emulator_path}\n\n"
                    f"Please check file permissions or configure a valid emulator."
                )
                return

        # Security: Validate emulator path doesn't contain dangerous shell metacharacters
        # This prevents paths like "/bin/sh;malicious" or "cmd.exe|evil"
        # Note: We allow spaces and normal path characters like (), {}, [], *, ? which may appear
        # in legitimate Windows paths (e.g., "Program Files (x86)"). Since we use shell=False,
        # these won't be interpreted as shell metacharacters.
        dangerous_chars = [';', '|', '&', '>', '<', '`', '\n', '\r', '$']
        if any(char in emulator_path for char in dangerous_chars):
            self._log(f"⚠️ Emulator path contains invalid characters: {emulator_path}", "Warning")
            messagebox.showwarning(
                "Invalid Emulator Path",
                f"The configured emulator path contains invalid characters.\n\n"
                f"Please configure a valid emulator path in Settings."
            )
            return

        try:
            command = self._build_emulator_command(
                emulator_path=emulator_path,
                emulator_args=emulator_args,
                emulator_args_enabled=emulator_args_enabled,
                rom_path=file_path,
            )

            # Log the exact command for debugging
            self._log(f"Launching emulator command: {command}", "Debug")

            # macOS: Prefer launching GUI apps via `open -a` when using a .app bundle.
            # This avoids cases where executing the internal Mach-O directly causes immediate exit.
            bundle_path = self._find_macos_app_bundle(emulator_path)
            if platform.system() == "Darwin" and bundle_path:
                open_command = ["open", "-a", bundle_path, "--args"] + command[1:]
                self._log(f"Launching macOS app bundle via open: {open_command}", "Debug")
                subprocess.Popen(open_command, shell=False)
                self._log(f"🎮 Launched '{hack_title}' with emulator", "Information")
                return

            # Launch emulator
            # Security: Explicitly use shell=False to prevent shell injection attacks
            # Set cwd to emulator directory so relative paths (like 'cores/snes9x.dll') work correctly
            emulator_dir = os.path.dirname(emulator_path)

            if platform.system() == "Windows":
                # Windows: use CREATE_NO_WINDOW to hide console and shell=False for security
                subprocess.Popen(command, shell=False, cwd=emulator_dir, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                # Unix: standard Popen with shell=False for security
                subprocess.Popen(command, shell=False, cwd=emulator_dir)

            self._log(f"🎮 Launched '{hack_title}' with emulator", "Information")

        except Exception as e:
            self._log(f"❌ Failed to launch emulator: {str(e)}", "Error")
            messagebox.showerror(
                "Launch Failed",
                f"Failed to launch emulator:\n\n{str(e)}"
            )

    def _find_hack_data(self, hack_id_str):
        """Find hack data by ID"""
        # Convert to string for comparison to handle both string and integer IDs
        hack_id_str = str(hack_id_str)
        for hack in self.filtered_data:
            if str(hack.get("id")) == hack_id_str:
                return hack
        return None

    def _open_hack_in_explorer(self, hack_id):
        """Open the hack file location in the system file explorer"""

        hack_data = self._find_hack_data(hack_id)
        if not hack_data:
            self._log(f"❌ Could not find hack data for ID: {hack_id}", "Error")
            return

        file_path = hack_data.get("file_path", "")
        hack_title = hack_data.get("title", "Unknown")

        if not file_path:
            self._log(f"📁 No file path available for '{hack_title}' - this hack may not be downloaded yet", "Warning")
            messagebox.showinfo(
                "File Not Available",
                f"No file location found for '{hack_title}'.\n\n"
                f"This hack may not have been downloaded yet, or the file may have been moved."
            )
            return

        if not os.path.exists(file_path):
            self._log(f"📁 File not found: {file_path} for '{hack_title}'", "Warning")
            messagebox.showwarning(
                "File Not Found",
                f"The file for '{hack_title}' could not be found:\n\n"
                f"{file_path}\n\n"
                f"The file may have been moved or deleted."
            )
            return

        # Try to open the file in the system explorer
        success = open_file_in_explorer(file_path)

        if success:
            self._log(f"📁 Opened file location for '{hack_title}' in system explorer", "Information")
        else:
            # Fallback message if the explorer couldn't be opened
            self._log(f"❌ Failed to open file explorer for '{hack_title}'", "Error")
            messagebox.showerror(
                "Explorer Error",
                f"Could not open the file explorer for '{hack_title}'.\n\n"
                f"File location: {file_path}\n\n"
                f"You can manually navigate to this location using your file manager."
            )

    def _show_hack_details(self, hack_data):
        """Show detailed hack information"""
        title = hack_data.get("title", "Unknown Hack")
        details = f"Hack: {title}\n\n"

        # Basic info - Use multi-type display
        hack_types = hack_data.get("hack_types", []) or [hack_data.get("hack_type", "Unknown")]
        type_display = format_types_display(hack_types)
        details += f"Type: {type_display}\n"
        details += f"Difficulty: {hack_data.get('difficulty', 'Unknown')}\n"
        details += (
            "Personal Rating: "
            f"{self._get_rating_display(hack_data.get('personal_rating', 0))}\n"
        )
        details += (
            "SMWC Rating: "
            f"{format_smwc_rating(hack_data.get('rating', 0))}\n"
        )

        # Status
        details += f"Completed: {'Yes' if hack_data.get('completed', False) else 'No'}\n"
        if hack_data.get('completed_date'):
            details += f"Completed on: {hack_data.get('completed_date')}\n"

        # Special flags
        if hack_data.get('hall_of_fame', False):
            details += "Hall of Fame: Yes\n"
        if hack_data.get('sa1_compatibility', False):
            details += "Uses SA-1 chip: Yes\n"
        if hack_data.get('collaboration', False):
            details += "Collaboration project: Yes\n"
        if hack_data.get('demo', False):
            details += "Demo version: Yes\n"

        # Notes
        if hack_data.get('notes'):
            details += f"\nNotes:\n{hack_data.get('notes')}"

        messagebox.showinfo(title, details)

    def _get_rating_display(self, rating):
        """Convert numeric rating to star display"""
        if rating == 0:
            return "☆☆☆☆☆"
        elif rating == 1:
            return "★☆☆☆☆"
        elif rating == 2:
            return "★★☆☆☆"
        elif rating == 3:
            return "★★★☆☆"
        elif rating == 4:
            return "★★★★☆"
        elif rating == 5:
            return "★★★★★"
        else:
            return "☆☆☆☆☆"

    def _format_time_display(self, seconds):
        """Convert seconds to readable time format (Xd Xh Xm Xs)"""
        if seconds == 0:
            return ""  # Empty if not set

        # Convert to days, hours, minutes, seconds
        days = seconds // 86400  # 86400 seconds in a day
        remaining = seconds % 86400
        hours = remaining // 3600
        remaining = remaining % 3600
        minutes = remaining // 60
        secs = remaining % 60

        # Build the display string
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:  # Always show seconds if no other parts, or if seconds > 0
            parts.append(f"{secs}s")

        return " ".join(parts)

    def _parse_time_input(self, time_str):
        """Parse user time input and convert to seconds"""
        if not time_str or time_str.strip() == "":
            return 0

        time_str = time_str.strip()

        # Support flexible input formats
        # HH:MM:SS, MM:SS, MM, "2h 30m", "90m", "150 minutes", etc.
        # NEW: Support shortened formats like "14d 10", "14d 10h 2", "14d 10h 2m 1"

        import re

        # Pattern for "HH:MM:SS" or "MM:SS" - handle this first to avoid regex conflicts
        if ':' in time_str:
            parts = time_str.split(':')
            try:
                if len(parts) == 3:  # HH:MM:SS
                    hours, minutes, seconds = map(int, parts)
                    return hours * 3600 + minutes * 60 + seconds
                elif len(parts) == 2:  # MM:SS
                    minutes, seconds = map(int, parts)
                    return minutes * 60 + seconds
            except ValueError:
                pass

        # Pattern for "150 minutes" or "90 mins"
        pattern_minutes = re.match(r'(\d+)\s*(?:minutes?|mins?)$', time_str.lower())
        if pattern_minutes:
            return int(pattern_minutes.group(1)) * 60

        # Pattern for "2h 30m 15s" or "2h 30m" or "90m" etc. - must have letter suffix
        pattern_units = re.match(r'(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s\s*)?$', time_str.lower())
        if pattern_units and any(pattern_units.groups()) and re.search(r'[hms]', time_str.lower()):
            hours = int(pattern_units.group(1) or 0)
            minutes = int(pattern_units.group(2) or 0)
            seconds = int(pattern_units.group(3) or 0)
            return hours * 3600 + minutes * 60 + seconds

        # NEW: Pattern for flexible shortened formats with days (only if 'd' is present)
        # "14d 10" -> 14 days, 10 hours, 0 minutes, 0 seconds
        # "14d 10h 2" -> 14 days, 10 hours, 2 minutes, 0 seconds
        # "14d 10h 2m 1" -> 14 days, 10 hours, 2 minutes, 1 second
        if 'd' in time_str.lower():
            pattern_flexible = re.match(r'(?:(\d+)d\s*)?(?:(\d+)h?\s*)?(?:(\d+)m?\s*)?(?:(\d+)s?\s*)?$', time_str.lower())
            if pattern_flexible and any(pattern_flexible.groups()):
                days = int(pattern_flexible.group(1) or 0)
                hours = int(pattern_flexible.group(2) or 0)
                minutes = int(pattern_flexible.group(3) or 0)
                seconds = int(pattern_flexible.group(4) or 0)
                return days * 86400 + hours * 3600 + minutes * 60 + seconds

        # Just a number - assume minutes
        if time_str.isdigit():
            return int(time_str) * 60

        raise ValueError(f"Invalid time format: {time_str}")

    def _validate_time_input(self, time_str):
        """Validate and convert time input to seconds for storage"""
        try:
            seconds = self._parse_time_input(time_str)
            if seconds < 0:
                from tkinter import messagebox
                messagebox.showerror("Invalid Time", "Time cannot be negative")
                return None
            if seconds > 999 * 3600:  # 999 hours max
                from tkinter import messagebox
                messagebox.showerror("Invalid Time", "Time cannot exceed 999 hours")
                return None
            return seconds
        except ValueError as e:
            from tkinter import messagebox
            messagebox.showerror("Invalid Time",
                               f"Invalid time format.\n\n"
                               f"Valid formats include:\n"
                               f"• HH:MM:SS (e.g., 1:30:45)\n"
                               f"• MM:SS (e.g., 90:30)\n"
                               f"• 2h 30m (e.g., 1h 30m 15s)\n"
                               f"• 90m or 90 minutes\n"
                               f"• 90 (assumes minutes)\n"
                               f"• 14d 10 (14 days, 10 hours)\n"
                               f"• 14d 10h 2 (14 days, 10 hours, 2 minutes)\n"
                               f"• 14d 10h 2m 1 (14 days, 10 hours, 2 minutes, 1 second)")
            return None

    def _toggle_h_scrollbar(self, scrollbar):
        """Show/hide horizontal scrollbar based on content (debounced)"""
        # Cancel pending timer if exists
        if self.scrollbar_toggle_timer:
            self.frame.after_cancel(self.scrollbar_toggle_timer)

        # Schedule scrollbar update with small delay
        self.scrollbar_toggle_timer = self.frame.after(100, lambda: self._do_toggle_h_scrollbar(scrollbar))

    def _do_toggle_h_scrollbar(self, scrollbar):
        """Actually toggle the scrollbar"""
        self.scrollbar_toggle_timer = None

        tree_width = self.tree.winfo_width()

        # Only sum widths of VISIBLE columns
        visible_cols = self.tree["displaycolumns"]
        if visible_cols:  # displaycolumns can be empty or a list
            content_width = sum(self.tree.column(col)["width"] for col in visible_cols)
        else:
            content_width = 0

        if content_width > tree_width:
            scrollbar.grid(row=1, column=0, sticky="ew")
        else:
            scrollbar.grid_remove()


    def _open_collection_update_discovery(self):
        """Search the current KaizOFF Index for a selected numeric Collection entry."""
        if (
            self._collection_update_discovery_busy
            or self._collection_update_plan_busy
            or self._collection_update_apply_busy
            or self._collection_update_rom_acquisition_busy
        ):
            return
        if self._collection_ingestion_busy:
            messagebox.showinfo(
                "Find Possible SMWC Update",
                "Finish the active Collection import operation before starting a separate "
                "update/replacement search.",
                parent=self.frame.winfo_toplevel(),
            )
            return
        if (
            self.collection_update_plan_preview_dialog is not None
            and self.collection_update_plan_preview_dialog.is_open
        ):
            self.collection_update_plan_preview_dialog.lift()
            return
        if (
            self.collection_current_refresh_preview_dialog is not None
            and self.collection_current_refresh_preview_dialog.is_open
        ):
            self.collection_current_refresh_preview_dialog.lift()
            return
        if (
            self.collection_update_discovery_dialog is not None
            and self.collection_update_discovery_dialog.is_open
        ):
            self.collection_update_discovery_dialog.lift()
            return

        parent = self.frame.winfo_toplevel()
        selected = self.tree.selection()
        if len(selected) != 1:
            messagebox.showinfo(
                "Find Possible SMWC Update",
                "Select one known SMWC Collection entry first.",
                parent=parent,
            )
            return
        tags = self.tree.item(selected[0]).get("tags") or ()
        if not tags:
            return
        source_key = str(tags[0])
        if not source_key.isdigit() or int(source_key) <= 0:
            messagebox.showinfo(
                "Find Possible SMWC Update",
                "Update/replacement discovery is available only for Collection entries "
                "that already have a numeric SMWC submission ID. Local usr_* entries can "
                "be promoted through the Collection import review flow instead.",
                parent=parent,
            )
            return
        if getattr(self.data_manager, "unsaved_changes", False):
            messagebox.showinfo(
                "Find Possible SMWC Update",
                "Collection changes are still waiting for the normal delayed save. "
                "Wait for them to save before starting update discovery so the selected "
                "entry has a stable catalogue snapshot.",
                parent=parent,
            )
            return

        source_record = self.data_manager.data.get(source_key)
        if not isinstance(source_record, dict):
            messagebox.showerror(
                "Find Possible SMWC Update",
                "The selected Collection record is unavailable.",
                parent=parent,
            )
            return

        from ui.collection_update_discovery_dialog import (
            CollectionUpdateDiscoveryProgressDialog,
        )

        frozen_record = copy.deepcopy(source_record)
        existing_keys = tuple(str(key) for key in self.data_manager.data)
        self._collection_update_discovery_busy = True
        self._last_collection_update_selection = None
        self.collection_update_discovery_progress_dialog = (
            CollectionUpdateDiscoveryProgressDialog(parent)
        )
        self.collection_update_discovery_progress_dialog.show()
        self._log(
            f"🔎 Looking for possible SMWC update/replacement candidates for {source_key}",
            "Information",
        )

        def worker():
            try:
                from collection_update_discovery import build_collection_update_discovery
                from kaizoff_provider import KaizOffCatalogueProvider

                processed = Path(self.data_manager.json_path).expanduser().resolve()
                provider = KaizOffCatalogueProvider(
                    cache_dir=processed.with_name("kaizoff_cache")
                )
                # This is an explicit update check, so prefer a current Index. The provider
                # may still return a validated stale cache when the network is unavailable.
                snapshot = provider.get_index(force_refresh=True)
                discovery = build_collection_update_discovery(
                    source_key,
                    frozen_record,
                    snapshot,
                    existing_collection_keys=existing_keys,
                )
                self._collection_update_discovery_queue.put(("ok", discovery))
            except Exception as error:
                self._collection_update_discovery_queue.put(("error", error))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_collection_update_discovery()

    def _poll_collection_update_discovery(self):
        try:
            status, payload = self._collection_update_discovery_queue.get_nowait()
        except queue.Empty:
            self._collection_update_discovery_poll_id = self.frame.after(
                100,
                self._poll_collection_update_discovery,
            )
            return

        self._collection_update_discovery_poll_id = None
        self._collection_update_discovery_busy = False
        if self.collection_update_discovery_progress_dialog is not None:
            self.collection_update_discovery_progress_dialog.close()
            self.collection_update_discovery_progress_dialog = None

        if status != "ok":
            self._log(f"❌ SMWC update discovery failed: {payload}", "Error")
            messagebox.showerror(
                "Find Possible SMWC Update",
                f"Could not load possible related SMWC submissions:\n\n{payload}",
                parent=self.frame.winfo_toplevel(),
            )
            return
        self._show_collection_update_discovery(payload)

    def _show_collection_update_discovery(self, discovery):
        from ui.collection_update_discovery_dialog import CollectionUpdateDiscoveryDialog

        self._log(
            "🔎 SMWC update discovery ready: "
            f"{len(discovery.suggestions)} possible related suggestion(s)",
            "Information",
        )
        self.collection_update_discovery_dialog = CollectionUpdateDiscoveryDialog(
            self.frame.winfo_toplevel(),
            discovery,
            on_select=self._collection_update_candidate_selected,
            on_refresh_current=self._collection_update_current_refresh_requested,
            on_close=self._collection_update_discovery_closed,
        )
        self.collection_update_discovery_dialog.show()

    def _collection_update_candidate_selected(self, selection):
        """Hydrate one explicitly confirmed relationship into a read-only final plan."""
        self._last_collection_update_selection = selection
        self._last_collection_update_plan = None
        target = selection.target_entry
        self._log(
            "🔎 Possible SMWC replacement relationship explicitly confirmed: "
            f"{selection.source_collection_key} -> {target.smwc_submission_id}",
            "Information",
        )
        if selection.target_already_in_collection:
            if getattr(self.data_manager, "unsaved_changes", False):
                messagebox.showinfo(
                    "Review Existing Collection Merge",
                    "Collection changes are still waiting for the normal delayed save. Wait for "
                    "them to save before comparing two existing Collection records.",
                    parent=self.frame.winfo_toplevel(),
                )
                return False
            return self._prepare_collection_update_existing_target_merge_review(selection)
        if not self._collection_update_state_is_saved():
            return False
        return self._start_collection_update_plan_preview(selection)

    def _prepare_collection_update_existing_target_merge_review(self, selection):
        """Freeze two existing Collection records for explicit user/local merge review."""
        try:
            from collection_update_merge_review import (
                build_collection_update_existing_target_merge_review,
            )

            review = build_collection_update_existing_target_merge_review(
                selection,
                self.data_manager,
            )
        except Exception as error:
            self._last_collection_update_merge_review = None
            self._last_collection_update_merge_decision = None
            self._log(f"❌ Existing-target merge review could not be prepared: {error}", "Error")
            messagebox.showerror(
                "Review Existing Collection Merge",
                f"Could not prepare the merge review:\n\n{error}\n\nNothing was changed.",
                parent=self.frame.winfo_toplevel(),
            )
            return False

        self._last_collection_update_merge_review = review
        self._last_collection_update_merge_decision = None
        self._log(
            "📋 Existing numeric replacement target requires explicit Collection merge review",
            "Information",
        )
        # The discovery dialog currently owns the modal grab. Open the merge review on the
        # next Tk turn so discovery can close and release its grab first.
        self.frame.after(0, lambda: self._show_collection_update_existing_target_merge_review(review))
        return True

    def _show_collection_update_existing_target_merge_review(self, review):
        from ui.collection_update_merge_review_dialog import CollectionUpdateMergeReviewDialog

        if (
            self.collection_update_merge_review_dialog is not None
            and self.collection_update_merge_review_dialog.is_open
        ):
            self.collection_update_merge_review_dialog.lift()
            return
        self.collection_update_merge_review_dialog = CollectionUpdateMergeReviewDialog(
            self.frame.winfo_toplevel(),
            review,
            on_save=self._collection_update_existing_target_merge_review_saved,
            on_close=self._collection_update_existing_target_merge_review_closed,
        )
        self.collection_update_merge_review_dialog.show()

    def _collection_update_existing_target_merge_review_saved(self, review, decision):
        self._last_collection_update_merge_review = review
        self._last_collection_update_merge_decision = decision
        self._last_collection_update_plan = None
        self._log(
            "✅ Existing-target Collection merge review completed; preparing immutable preview",
            "Information",
        )
        if not self._collection_update_state_is_saved():
            return False
        return self._start_collection_update_plan_preview(
            review.selection,
            merge_review=review,
            merge_decision=decision,
        )

    def _collection_update_existing_target_merge_review_closed(self):
        self.collection_update_merge_review_dialog = None


    def _start_collection_update_plan_preview(
        self,
        selection,
        *,
        merge_review=None,
        merge_decision=None,
    ):
        if self._collection_update_plan_busy:
            return False
        if (merge_review is None) != (merge_decision is None):
            raise ValueError("Existing-target plan preview requires both merge review and decision.")
        parent = self.frame.winfo_toplevel()
        from ui.collection_update_plan_preview_dialog import (
            CollectionUpdatePlanProgressDialog,
        )

        self._collection_update_plan_busy = True
        self.collection_update_plan_progress_dialog = CollectionUpdatePlanProgressDialog(parent)
        self.collection_update_plan_progress_dialog.show()
        processed_json_path = str(self.data_manager.json_path)
        self._log(
            "📋 Building immutable SMWC replacement plan for read-only preview",
            "Information",
        )

        def worker():
            try:
                if merge_review is None:
                    from collection_update_plan import finalize_collection_update_selection_plan

                    finalized = finalize_collection_update_selection_plan(
                        processed_json_path,
                        selection,
                        force_detail_refresh=True,
                    )
                else:
                    from collection_update_plan import (
                        finalize_collection_update_existing_target_selection_plan,
                    )

                    finalized = finalize_collection_update_existing_target_selection_plan(
                        processed_json_path,
                        merge_review,
                        merge_decision,
                        force_detail_refresh=True,
                    )
                self._collection_update_plan_queue.put(("ready", finalized))
            except Exception as error:
                self._collection_update_plan_queue.put(("error", error))

        threading.Thread(
            target=worker,
            daemon=True,
            name="collection-update-plan-preview",
        ).start()
        self._poll_collection_update_plan()
        return True

    def _poll_collection_update_plan(self):
        try:
            status, payload = self._collection_update_plan_queue.get_nowait()
        except queue.Empty:
            self._collection_update_plan_poll_id = self.frame.after(
                100,
                self._poll_collection_update_plan,
            )
            return

        self._collection_update_plan_poll_id = None
        self._collection_update_plan_busy = False
        if self.collection_update_plan_progress_dialog is not None:
            self.collection_update_plan_progress_dialog.close()
            self.collection_update_plan_progress_dialog = None
        if status != "ready":
            self._last_collection_update_plan = None
            self._log(f"❌ SMWC replacement plan finalization failed: {payload}", "Error")
            messagebox.showerror(
                "SMWC Replacement Plan Preview",
                (
                    "Could not build the read-only replacement plan:\n\n"
                    f"{payload}\n\nNothing was applied. Start update discovery again if "
                    "Collection or dependent state changed."
                ),
                parent=self.frame.winfo_toplevel(),
            )
            return
        self._show_collection_update_plan_preview(payload)

    def _show_collection_update_plan_preview(self, finalized):
        from ui.collection_update_plan_preview_dialog import (
            CollectionUpdatePlanPreviewDialog,
        )

        self._last_collection_update_plan = finalized
        self._log(
            "✅ Immutable SMWC replacement plan ready for read-only preview",
            "Information",
        )
        self.collection_update_plan_preview_dialog = CollectionUpdatePlanPreviewDialog(
            self.frame.winfo_toplevel(),
            finalized,
            on_acquire=self._collection_update_acquire_target_rom_requested,
            on_apply=self._collection_update_apply_requested,
            on_close=self._collection_update_plan_preview_closed,
        )
        self.collection_update_plan_preview_dialog.show()

    def _collection_update_plan_preview_closed(self):
        self.collection_update_plan_preview_dialog = None
        self.collection_update_apply_progress_dialog = None

    def _collection_update_acquire_target_rom_requested(self):
        """Acquire a target ROM before Apply without mutating Collection/user metadata."""
        if (
            self._collection_update_plan_busy
            or self._collection_update_apply_busy
            or self._collection_update_rom_acquisition_busy
        ):
            return False
        finalized = self._last_collection_update_plan
        if finalized is None:
            messagebox.showerror(
                "Acquire Target ROM",
                "The finalized replacement plan is no longer available.",
                parent=self.frame.winfo_toplevel(),
            )
            return False
        if finalized.merge_decision is not None:
            messagebox.showinfo(
                "Acquire Target ROM",
                "This replacement target already existed in Collection and its ROM state was "
                "reviewed explicitly. Target-ROM acquisition is not added after that merge review.",
                parent=self.frame.winfo_toplevel(),
            )
            return False
        if not self._collection_update_state_is_saved():
            return False

        config = ConfigManager()
        base_rom_path = str(config.get("base_rom_path", "") or "")
        output_dir = str(config.get("output_dir", "") or "")
        if not base_rom_path or not os.path.isfile(base_rom_path):
            messagebox.showerror(
                "Acquire Target ROM",
                "Configure a valid clean base ROM in Settings before acquiring the target ROM.",
                parent=self.frame.winfo_toplevel(),
            )
            return False
        if not output_dir or not os.path.isdir(output_dir):
            messagebox.showerror(
                "Acquire Target ROM",
                "Configure a valid ROM output directory in Settings before acquiring the target ROM.",
                parent=self.frame.winfo_toplevel(),
            )
            return False

        from ui.collection_update_plan_preview_dialog import (
            CollectionUpdateRomAcquisitionProgressDialog,
        )
        from ui.components.multi_patch_dialog import make_multi_patch_callback

        parent = self.frame.winfo_toplevel()
        multi_patch_callback = make_multi_patch_callback(parent)
        self._collection_update_rom_acquisition_busy = True
        self.collection_update_rom_acquisition_progress_dialog = (
            CollectionUpdateRomAcquisitionProgressDialog(parent)
        )
        self.collection_update_rom_acquisition_progress_dialog.show()
        self._log(
            "⬇️ Acquiring and validating the explicitly selected SMWC replacement ROM",
            "Information",
        )

        def worker():
            try:
                from collection_update_rom_acquisition import (
                    acquire_collection_update_target_rom,
                )

                result = acquire_collection_update_target_rom(
                    str(self.data_manager.json_path),
                    finalized,
                    base_rom_path=base_rom_path,
                    output_dir=output_dir,
                    include_smwc_id_in_filename=bool(
                        config.get("include_smwc_id_in_filename", False)
                    ),
                    multi_patch_callback=multi_patch_callback,
                )
                self._collection_update_rom_acquisition_queue.put(("ready", result))
            except Exception as error:
                self._collection_update_rom_acquisition_queue.put(("error", error))

        threading.Thread(
            target=worker,
            daemon=True,
            name="collection-update-rom-acquisition",
        ).start()
        self._poll_collection_update_rom_acquisition()
        return True

    def _poll_collection_update_rom_acquisition(self):
        try:
            status, payload = self._collection_update_rom_acquisition_queue.get_nowait()
        except queue.Empty:
            self._collection_update_rom_acquisition_poll_id = self.frame.after(
                100,
                self._poll_collection_update_rom_acquisition,
            )
            return

        self._collection_update_rom_acquisition_poll_id = None
        self._collection_update_rom_acquisition_busy = False
        if self.collection_update_rom_acquisition_progress_dialog is not None:
            self.collection_update_rom_acquisition_progress_dialog.close()
            self.collection_update_rom_acquisition_progress_dialog = None

        if status != "ready":
            from collection_update_rom_acquisition import (
                CollectionUpdateRomAcquisitionStaleStateError,
            )

            if isinstance(payload, CollectionUpdateRomAcquisitionStaleStateError):
                self._log(f"⚠️ Target-ROM acquisition became stale: {payload}", "Warning")
                self._close_collection_update_plan_preview()
                self._clear_collection_update_state()
                messagebox.showerror(
                    "Target ROM Acquisition Changed",
                    f"{payload}\n\nNo Collection replacement was applied. Restart update discovery.",
                    parent=self.frame.winfo_toplevel(),
                )
                return
            if (
                self.collection_update_plan_preview_dialog is not None
                and self.collection_update_plan_preview_dialog.is_open
            ):
                self.collection_update_plan_preview_dialog.set_acquiring(False)
            self._log(f"❌ Target-ROM acquisition failed: {payload}", "Error")
            messagebox.showerror(
                "Target ROM Acquisition Failed",
                (
                    f"Could not acquire the selected target ROM:\n\n{payload}\n\n"
                    "Collection identity was not changed. Existing ROM/save files were not "
                    "overwritten or renamed."
                ),
                parent=self.frame.winfo_toplevel(),
            )
            return

        result = payload
        self._last_collection_update_plan = result.finalized
        self._log(
            f"✅ Target ROM acquired and added to immutable preview: {result.primary_path}",
            "Information",
        )
        self._close_collection_update_plan_preview()
        self._show_collection_update_plan_preview(result.finalized)
        messagebox.showinfo(
            "Target ROM Acquired",
            (
                f"Created {len(result.created_paths)} patched target ROM file(s). The selected "
                "primary ROM is:\n\n"
                f"{result.primary_path}\n\n"
                "The Collection replacement is still not applied. Review the updated immutable "
                "plan before choosing Apply Replacement."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_update_apply_requested(self):
        """Cross the explicit confirmation boundary for the finalized replacement plan."""
        if (
            self._collection_update_plan_busy
            or self._collection_update_apply_busy
            or self._collection_update_rom_acquisition_busy
        ):
            return False
        if self._last_collection_update_plan is None:
            messagebox.showerror(
                "SMWC Replacement",
                "The finalized replacement plan is no longer available.",
                parent=self.frame.winfo_toplevel(),
            )
            return False
        if not self._collection_update_state_is_saved():
            return False

        from ui.collection_update_plan_preview_dialog import (
            CollectionUpdateApplyProgressDialog,
        )

        self._collection_update_apply_busy = True
        parent = self.frame.winfo_toplevel()
        self.collection_update_apply_progress_dialog = CollectionUpdateApplyProgressDialog(parent)
        self.collection_update_apply_progress_dialog.show()
        self._log(
            "💾 Applying finalized SMWC replacement plan transactionally",
            "Information",
        )
        # The local coordinated transaction runs on the Tk thread so it serializes
        # against pending Collection edits on the live HackDataManager instance.
        self.frame.after(1, self._execute_collection_update_apply)
        return True

    def _execute_collection_update_apply(self):
        from collection_plan_apply import (
            CollectionPlanRecoveryError,
            CollectionPlanStaleStateError,
        )

        finalized = self._last_collection_update_plan
        if finalized is None:
            self._collection_update_apply_failed(
                RuntimeError("Finalized SMWC replacement plan is missing.")
            )
            return

        try:
            from collection_update_apply import (
                apply_finalized_collection_update,
                collection_update_apply_recovery_pending,
                recover_collection_update_apply,
            )

            result = apply_finalized_collection_update(
                str(self.data_manager.json_path),
                finalized,
                manager=self.data_manager,
            )
        except CollectionPlanStaleStateError as error:
            self._collection_update_apply_stale(error)
            return
        except CollectionPlanRecoveryError as error:
            self._collection_update_recovery_required(error)
            return
        except Exception as error:
            self._collection_update_apply_failed(error)
            return

        cleanup_error = None
        if collection_update_apply_recovery_pending(self.data_manager.json_path):
            try:
                # A successful return means the journal has crossed its committed point;
                # any remaining journal is cleanup-only for this same application instance.
                recover_collection_update_apply(self.data_manager.json_path)
            except Exception as error:
                cleanup_error = error
        self._collection_update_apply_succeeded(result, cleanup_error)

    def _close_collection_update_apply_progress(self):
        if self.collection_update_apply_progress_dialog is not None:
            self.collection_update_apply_progress_dialog.close()
        self.collection_update_apply_progress_dialog = None

    def _collection_update_apply_succeeded(self, result, cleanup_error=None):
        finalized = self._last_collection_update_plan
        selection = finalized.selection if finalized is not None else None
        source_id = (
            selection.source_entry.smwc_submission_id if selection is not None else "source"
        )
        target_id = (
            selection.target_entry.smwc_submission_id if selection is not None else "target"
        )
        self._close_collection_update_apply_progress()
        self._collection_update_apply_busy = False
        self._reload_collection_ingestion_live_state()
        self._close_collection_update_plan_preview()
        self._clear_collection_update_state()

        cleanup_note = ""
        if cleanup_error is not None:
            cleanup_note = (
                "\n\nThe replacement transaction committed successfully, but its "
                f"journal cleanup failed: {cleanup_error}\n\nDo not start another Collection "
                "transaction until that journal is recovered."
            )
            self._log(
                f"⚠️ SMWC replacement committed but journal cleanup failed: {cleanup_error}",
                "Warning",
            )
        from collection_update_rom_acquisition import finalized_update_has_acquired_target_rom

        acquired_target_rom = bool(
            finalized is not None and finalized_update_has_acquired_target_rom(finalized)
        )
        self._log(
            f"✅ SMWC replacement applied transactionally: {source_id} -> {target_id}",
            "Information",
        )
        rom_status_note = (
            "The target ROM was acquired and validated before Apply; Apply itself performed "
            "no network or patching work. "
            if acquired_target_rom
            else "No target ROM was acquired for this replacement. "
        )
        messagebox.showinfo(
            "SMWC Replacement Applied",
            (
                f"The reviewed Collection replacement SMWC {source_id} → SMWC {target_id} "
                "was applied successfully.\n\n"
                f"Collection records: {result.collection_record_count}\n"
                f"Files written transactionally: {len(result.written_files)}\n"
                f"Identity migrations: {result.identity_migration_count}\n"
                f"Dependent reference stores participating: {result.reference_participant_count}\n\n"
                + rom_status_note
                + "No existing ROM/save files were moved, renamed, deleted, or overwritten. "
                "Retained ROM rows keep the per-ROM SMWC provenance shown in the preview."
                f"{cleanup_note}"
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_update_apply_stale(self, error):
        self._close_collection_update_apply_progress()
        self._collection_update_apply_busy = False
        self._log(f"⚠️ SMWC replacement plan became stale: {error}", "Warning")
        self._close_collection_update_plan_preview()
        self._clear_collection_update_state()
        messagebox.showerror(
            "SMWC Replacement Changed",
            (
                "The reviewed Collection or dependent state changed before Apply, so the "
                f"replacement plan was rejected.\n\n{error}\n\nStart update discovery again. "
                "Nothing from this stale plan was applied."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_update_apply_failed(self, error):
        self._close_collection_update_apply_progress()
        self._collection_update_apply_busy = False
        if (
            self.collection_update_plan_preview_dialog is not None
            and self.collection_update_plan_preview_dialog.is_open
        ):
            self.collection_update_plan_preview_dialog.set_applying(False)
        self._log(f"❌ SMWC replacement Apply failed: {error}", "Error")
        messagebox.showerror(
            "SMWC Replacement Failed",
            (
                "The transactional replacement could not be committed.\n\n"
                f"{error}\n\nNo reviewed replacement change was committed; any prepared "
                "transaction was rolled back. You may close the preview or retry after "
                "correcting the underlying problem."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_update_recovery_required(self, error):
        self._close_collection_update_apply_progress()
        self._collection_update_apply_busy = False
        if (
            self.collection_update_plan_preview_dialog is not None
            and self.collection_update_plan_preview_dialog.is_open
        ):
            self.collection_update_plan_preview_dialog.set_applying(False)
        self._log(f"⚠️ SMWC replacement recovery required: {error}", "Warning")
        recover_now = messagebox.askyesno(
            "Collection Transaction Recovery Required",
            (
                "A coordinated Collection transaction journal already exists. This can mean "
                "another application instance is currently applying changes, or a previous "
                f"transaction was interrupted.\n\n{error}\n\nClose every other SMWC Downloader "
                "& Patcher instance first. Only choose Yes after confirming no other instance "
                "is applying Collection changes. Recovery may roll back a prepared transaction "
                "or finish cleanup for one already committed.\n\nRecover now?"
            ),
            icon="warning",
            parent=self.frame.winfo_toplevel(),
        )
        if recover_now:
            self._run_collection_update_recovery()

    def _run_collection_update_recovery(self):
        from collection_update_apply import recover_collection_update_apply
        from ui.collection_update_plan_preview_dialog import (
            CollectionUpdateApplyProgressDialog,
        )

        self._collection_update_apply_busy = True
        parent = self.frame.winfo_toplevel()
        self.collection_update_apply_progress_dialog = CollectionUpdateApplyProgressDialog(
            parent, recovery=True
        )
        self.collection_update_apply_progress_dialog.show()
        try:
            recovered = recover_collection_update_apply(self.data_manager.json_path)
        except Exception as error:
            self._close_collection_update_apply_progress()
            self._collection_update_apply_busy = False
            self._log(f"❌ Collection replacement recovery failed: {error}", "Error")
            messagebox.showerror(
                "Collection Recovery Failed",
                (
                    "The transaction journal could not be recovered safely.\n\n"
                    f"{error}\n\nDo not start another Collection transaction until the recovery "
                    "issue has been resolved."
                ),
                parent=parent,
            )
            return

        self._close_collection_update_apply_progress()
        self._collection_update_apply_busy = False
        self._reload_collection_ingestion_live_state()
        self._close_collection_update_plan_preview()
        self._clear_collection_update_state()
        self._log("✅ Collection transaction recovery completed", "Information")
        messagebox.showinfo(
            "Collection Recovery Complete",
            (
                "The interrupted Collection transaction was recovered and live application "
                "state was reloaded.\n\n"
                + (
                    "Start a new update/replacement discovery before applying anything else."
                    if recovered
                    else "No recovery journal remained. Start a new discovery if needed."
                )
            ),
            parent=parent,
        )

    def _collection_update_current_refresh_requested(self, discovery):
        """Build a same-SMWC-ID immutable refresh plan from the active discovery snapshot."""
        if (
            self._collection_update_plan_busy
            or self._collection_update_apply_busy
            or self._collection_update_rom_acquisition_busy
        ):
            return False
        if not self._collection_update_state_is_saved():
            return False

        source_key = str(discovery.source_collection_key)
        parent = self.frame.winfo_toplevel()
        from ui.collection_update_current_refresh_dialog import (
            CollectionCurrentRefreshProgressDialog,
        )

        self._collection_update_plan_busy = True
        self._last_collection_current_refresh_plan = None
        self.collection_current_refresh_progress_dialog = CollectionCurrentRefreshProgressDialog(
            parent,
            title="Refresh Current SMWC Submission",
            message=(
                f"Loading current KaizOFF detail for SMWC {source_key} and freezing a same-ID "
                "metadata refresh plan. Collection identity and ROM files are unchanged."
            ),
        )
        self.collection_current_refresh_progress_dialog.show()
        processed_json_path = str(self.data_manager.json_path)
        self._log(
            f"🔄 Building same-ID current-submission refresh plan for SMWC {source_key}",
            "Information",
        )

        def worker():
            try:
                from collection_update_current_refresh import (
                    finalize_current_submission_refresh_plan,
                )

                finalized = finalize_current_submission_refresh_plan(
                    processed_json_path,
                    source_key,
                    force_detail_refresh=True,
                )
                self._collection_current_refresh_queue.put(("plan_ready", finalized))
            except Exception as error:
                self._collection_current_refresh_queue.put(("plan_error", error))

        threading.Thread(
            target=worker,
            daemon=True,
            name="collection-current-submission-refresh-plan",
        ).start()
        self._poll_collection_current_refresh()
        return True

    def _poll_collection_current_refresh(self):
        try:
            status, payload = self._collection_current_refresh_queue.get_nowait()
        except queue.Empty:
            self._collection_current_refresh_poll_id = self.frame.after(
                100,
                self._poll_collection_current_refresh,
            )
            return

        self._collection_current_refresh_poll_id = None
        if self.collection_current_refresh_progress_dialog is not None:
            self.collection_current_refresh_progress_dialog.close()
            self.collection_current_refresh_progress_dialog = None

        if status == "plan_ready":
            self._collection_update_plan_busy = False
            self._show_collection_current_refresh_preview(payload)
            return
        if status == "plan_error":
            self._collection_update_plan_busy = False
            self._last_collection_current_refresh_plan = None
            self._log(f"❌ Current SMWC refresh planning failed: {payload}", "Error")
            messagebox.showerror(
                "Current SMWC Refresh",
                f"Could not build the same-ID refresh plan:\n\n{payload}\n\nNothing was applied.",
                parent=self.frame.winfo_toplevel(),
            )
            return
        if status == "acquire_ready":
            self._collection_update_rom_acquisition_busy = False
            result = payload
            self._last_collection_current_refresh_plan = result.finalized
            self._close_collection_current_refresh_preview()
            self._show_collection_current_refresh_preview(result.finalized)
            if result.identical_to_existing:
                self._log(
                    "✅ Current SMWC download matches existing verified Collection ROM bytes",
                    "Information",
                )
                messagebox.showinfo(
                    "Current ROM Already Matches",
                    (
                        "The current SMWC download patched to bytes already represented by a verified "
                        "ROM asset in Collection. The temporary duplicate was removed.\n\n"
                        "You may still Apply Current Refresh to update the frozen catalogue metadata."
                    ),
                    parent=self.frame.winfo_toplevel(),
                )
            else:
                self._log(
                    f"✅ Current SMWC ROM downloaded for disposition review: {result.primary_path}",
                    "Information",
                )
                self._collection_current_refresh_rom_disposition_requested()
            return
        if status == "acquire_error":
            self._collection_update_rom_acquisition_busy = False
            from collection_update_current_refresh_acquisition import (
                CollectionCurrentRefreshAcquisitionStaleStateError,
            )

            if isinstance(payload, CollectionCurrentRefreshAcquisitionStaleStateError):
                self._log(f"⚠️ Current-ROM acquisition became stale: {payload}", "Warning")
                self._close_collection_current_refresh_preview()
                self._last_collection_current_refresh_plan = None
                messagebox.showerror(
                    "Current ROM Acquisition Changed",
                    f"{payload}\n\nNo Collection refresh was applied. Restart the update check.",
                    parent=self.frame.winfo_toplevel(),
                )
                return
            if (
                self.collection_current_refresh_preview_dialog is not None
                and self.collection_current_refresh_preview_dialog.is_open
            ):
                self.collection_current_refresh_preview_dialog.set_busy(False)
            self._log(f"❌ Current-ROM acquisition failed: {payload}", "Error")
            messagebox.showerror(
                "Current ROM Acquisition Failed",
                (
                    f"Could not acquire the current SMWC ROM:\n\n{payload}\n\n"
                    "Collection state was not changed and existing ROM files were not overwritten."
                ),
                parent=self.frame.winfo_toplevel(),
            )
            return

    def _show_collection_current_refresh_preview(self, finalized):
        from ui.collection_update_current_refresh_dialog import (
            CollectionCurrentRefreshPreviewDialog,
        )

        self._last_collection_current_refresh_plan = finalized
        self.collection_current_refresh_preview_dialog = CollectionCurrentRefreshPreviewDialog(
            self.frame.winfo_toplevel(),
            finalized,
            on_acquire=self._collection_current_refresh_acquire_requested,
            on_review_rom=self._collection_current_refresh_rom_disposition_requested,
            on_apply=self._collection_current_refresh_apply_requested,
            on_close=self._collection_current_refresh_preview_closed,
        )
        self.collection_current_refresh_preview_dialog.show()

    def _collection_current_refresh_preview_closed(self):
        self.collection_current_refresh_preview_dialog = None

    def _collection_current_refresh_acquire_requested(self):
        if (
            self._collection_update_plan_busy
            or self._collection_update_apply_busy
            or self._collection_update_rom_acquisition_busy
        ):
            return False
        finalized = self._last_collection_current_refresh_plan
        if finalized is None:
            return False
        if not self._collection_update_state_is_saved():
            return False

        config = ConfigManager()
        base_rom_path = str(config.get("base_rom_path", "") or "")
        output_dir = str(config.get("output_dir", "") or "")
        if not base_rom_path or not os.path.isfile(base_rom_path):
            messagebox.showerror(
                "Acquire Current ROM",
                "Configure a valid clean base ROM in Settings before acquiring the current ROM.",
                parent=self.frame.winfo_toplevel(),
            )
            return False
        if not output_dir or not os.path.isdir(output_dir):
            messagebox.showerror(
                "Acquire Current ROM",
                "Configure a valid ROM output directory in Settings before acquiring the current ROM.",
                parent=self.frame.winfo_toplevel(),
            )
            return False

        from ui.collection_update_current_refresh_dialog import (
            CollectionCurrentRefreshProgressDialog,
        )
        from ui.components.multi_patch_dialog import make_multi_patch_callback

        parent = self.frame.winfo_toplevel()
        callback = make_multi_patch_callback(parent)
        self._collection_update_rom_acquisition_busy = True
        self.collection_current_refresh_progress_dialog = CollectionCurrentRefreshProgressDialog(
            parent,
            title="Acquire Current SMWC ROM",
            message=(
                "Downloading the current reviewed SMWC archive, patching against the configured "
                "clean base ROM, hashing the result, and publishing without overwriting existing files."
            ),
        )
        self.collection_current_refresh_progress_dialog.show()
        self._log("⬇️ Acquiring current same-ID SMWC ROM", "Information")

        def worker():
            try:
                from collection_update_current_refresh_acquisition import (
                    acquire_current_submission_rom,
                )

                result = acquire_current_submission_rom(
                    str(self.data_manager.json_path),
                    finalized,
                    base_rom_path=base_rom_path,
                    output_dir=output_dir,
                    include_smwc_id_in_filename=bool(
                        config.get("include_smwc_id_in_filename", False)
                    ),
                    multi_patch_callback=callback,
                )
                self._collection_current_refresh_queue.put(("acquire_ready", result))
            except Exception as error:
                self._collection_current_refresh_queue.put(("acquire_error", error))

        threading.Thread(
            target=worker,
            daemon=True,
            name="collection-current-submission-rom-acquisition",
        ).start()
        self._poll_collection_current_refresh()
        return True

    def _collection_current_refresh_rom_disposition_requested(self):
        finalized = self._last_collection_current_refresh_plan
        if finalized is None or self._collection_update_apply_busy or self._collection_update_rom_acquisition_busy:
            return False
        if self.collection_current_rom_disposition_dialog is not None:
            if self.collection_current_rom_disposition_dialog.is_open:
                self.collection_current_rom_disposition_dialog.win.lift()
                return True
            self.collection_current_rom_disposition_dialog = None
        try:
            from collection_update_current_rom_disposition import build_current_rom_disposition_review
            review = build_current_rom_disposition_review(
                str(self.data_manager.json_path),
                finalized,
                manager=self.data_manager,
            )
        except Exception as error:
            self._log(f"❌ Current-ROM disposition review failed: {error}", "Error")
            messagebox.showerror(
                "Choose ROM Handling",
                f"Could not prepare the current-ROM choice:\n\n{error}",
                parent=self.frame.winfo_toplevel(),
            )
            return False
        from ui.collection_update_current_rom_disposition_dialog import CollectionCurrentRomDispositionDialog
        self._last_collection_current_rom_disposition_review = review
        self.collection_current_rom_disposition_dialog = CollectionCurrentRomDispositionDialog(
            self.frame.winfo_toplevel(),
            review,
            on_save=self._collection_current_refresh_rom_disposition_saved,
            on_close=self._collection_current_refresh_rom_disposition_closed,
        )
        self.collection_current_rom_disposition_dialog.show()
        return True

    def _collection_current_refresh_rom_disposition_saved(self, disposition, primary_path):
        finalized = self._last_collection_current_refresh_plan
        review = self._last_collection_current_rom_disposition_review
        if finalized is None or review is None:
            return False
        try:
            from collection_update_current_rom_disposition import finalize_current_rom_disposition
            reviewed = finalize_current_rom_disposition(
                str(self.data_manager.json_path),
                finalized,
                review,
                disposition,
                primary_path=primary_path,
                manager=self.data_manager,
            )
        except Exception as error:
            self._log(f"❌ Current-ROM disposition could not be frozen: {error}", "Error")
            messagebox.showerror(
                "ROM Choice Changed",
                f"Could not save the reviewed ROM choice:\n\n{error}",
                parent=self.frame.winfo_toplevel(),
            )
            return False
        self._last_collection_current_refresh_plan = reviewed
        self._last_collection_current_rom_disposition_review = None
        self._close_collection_current_refresh_preview()
        self._show_collection_current_refresh_preview(reviewed)
        return True

    def _collection_current_refresh_rom_disposition_closed(self):
        self.collection_current_rom_disposition_dialog = None
        self._last_collection_current_rom_disposition_review = None

    def _collection_current_refresh_apply_requested(self):
        if (
            self._collection_update_plan_busy
            or self._collection_update_apply_busy
            or self._collection_update_rom_acquisition_busy
        ):
            return False
        if self._last_collection_current_refresh_plan is None:
            return False
        if not self._collection_update_state_is_saved():
            return False

        from ui.collection_update_current_refresh_dialog import (
            CollectionCurrentRefreshProgressDialog,
        )

        self._collection_update_apply_busy = True
        parent = self.frame.winfo_toplevel()
        self.collection_current_refresh_progress_dialog = CollectionCurrentRefreshProgressDialog(
            parent,
            title="Apply Current SMWC Refresh",
            message=(
                "Applying the frozen same-ID catalogue/ROM plan transactionally. No provider, "
                "download, matching, or patching work occurs during Apply."
            ),
        )
        self.collection_current_refresh_progress_dialog.show()
        self._log("💾 Applying same-ID current SMWC refresh transactionally", "Information")
        self.frame.after(1, self._execute_collection_current_refresh_apply)
        return True

    def _execute_collection_current_refresh_apply(self):
        from collection_plan_apply import CollectionPlanRecoveryError, CollectionPlanStaleStateError

        finalized = self._last_collection_current_refresh_plan
        if finalized is None:
            self._collection_current_refresh_apply_failed(
                RuntimeError("Finalized current-submission refresh plan is missing.")
            )
            return
        try:
            from collection_update_current_refresh_apply import (
                apply_finalized_current_submission_refresh,
            )
            from collection_update_apply import (
                collection_update_apply_recovery_pending,
                recover_collection_update_apply,
            )

            result = apply_finalized_current_submission_refresh(
                str(self.data_manager.json_path),
                finalized,
                manager=self.data_manager,
            )
        except CollectionPlanStaleStateError as error:
            self._collection_current_refresh_apply_stale(error)
            return
        except CollectionPlanRecoveryError as error:
            self._collection_current_refresh_recovery_required(error)
            return
        except Exception as error:
            self._collection_current_refresh_apply_failed(error)
            return

        cleanup_error = None
        if collection_update_apply_recovery_pending(self.data_manager.json_path):
            try:
                recover_collection_update_apply(self.data_manager.json_path)
            except Exception as error:
                cleanup_error = error
        self._collection_current_refresh_apply_succeeded(result, cleanup_error)

    def _close_collection_current_refresh_progress(self):
        if self.collection_current_refresh_progress_dialog is not None:
            self.collection_current_refresh_progress_dialog.close()
        self.collection_current_refresh_progress_dialog = None

    def _collection_current_refresh_apply_succeeded(self, result, cleanup_error=None):
        finalized = self._last_collection_current_refresh_plan
        source_key = finalized.source_collection_key if finalized is not None else "current"
        self._close_collection_current_refresh_progress()
        self._collection_update_apply_busy = False
        self._reload_collection_ingestion_live_state()
        self._close_collection_current_refresh_preview()
        self._last_collection_current_refresh_plan = None
        cleanup_note = ""
        if cleanup_error is not None:
            cleanup_note = (
                f"\n\nThe refresh committed, but journal cleanup failed: {cleanup_error}. "
                "Recover that journal before starting another Collection transaction."
            )
        self._log(f"✅ Current SMWC {source_key} refresh applied transactionally", "Information")
        messagebox.showinfo(
            "Current SMWC Refresh Applied",
            (
                f"SMWC {source_key} was refreshed without changing Collection identity.\n\n"
                f"Files written transactionally: {len(result.written_files)}\n"
                f"Identity migrations: {result.identity_migration_count}\n\n"
                "The reviewed ROM handling choice was applied without changing Collection identity. "
                "Apply itself performed no network or patching work."
                f"{cleanup_note}"
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_current_refresh_apply_stale(self, error):
        self._close_collection_current_refresh_progress()
        self._collection_update_apply_busy = False
        self._log(f"⚠️ Current SMWC refresh became stale: {error}", "Warning")
        self._close_collection_current_refresh_preview()
        self._last_collection_current_refresh_plan = None
        messagebox.showerror(
            "Current SMWC Refresh Changed",
            f"{error}\n\nNothing from the stale same-ID refresh plan was applied. Restart the update check.",
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_current_refresh_apply_failed(self, error):
        self._close_collection_current_refresh_progress()
        self._collection_update_apply_busy = False
        if (
            self.collection_current_refresh_preview_dialog is not None
            and self.collection_current_refresh_preview_dialog.is_open
        ):
            self.collection_current_refresh_preview_dialog.set_busy(False)
        self._log(f"❌ Current SMWC refresh Apply failed: {error}", "Error")
        messagebox.showerror(
            "Current SMWC Refresh Failed",
            (
                f"The transactional same-ID refresh could not be committed.\n\n{error}\n\n"
                "No reviewed refresh change was committed. You may retry after correcting the problem."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_current_refresh_recovery_required(self, error):
        self._close_collection_current_refresh_progress()
        self._collection_update_apply_busy = False
        if (
            self.collection_current_refresh_preview_dialog is not None
            and self.collection_current_refresh_preview_dialog.is_open
        ):
            self.collection_current_refresh_preview_dialog.set_busy(False)
        self._log(f"⚠️ Current SMWC refresh recovery required: {error}", "Warning")
        recover_now = messagebox.askyesno(
            "Collection Transaction Recovery Required",
            (
                "A coordinated Collection transaction journal already exists. Close every other "
                "SMWC Downloader & Patcher instance first. Only recover after confirming no other "
                f"instance is applying Collection changes.\n\n{error}\n\nRecover now?"
            ),
            icon="warning",
            parent=self.frame.winfo_toplevel(),
        )
        if not recover_now:
            return
        try:
            from collection_update_apply import recover_collection_update_apply

            recover_collection_update_apply(self.data_manager.json_path)
        except Exception as recovery_error:
            self._log(f"❌ Current refresh recovery failed: {recovery_error}", "Error")
            messagebox.showerror(
                "Collection Recovery Failed",
                str(recovery_error),
                parent=self.frame.winfo_toplevel(),
            )
            return
        self._reload_collection_ingestion_live_state()
        self._close_collection_current_refresh_preview()
        self._last_collection_current_refresh_plan = None
        messagebox.showinfo(
            "Collection Recovery Complete",
            "The interrupted Collection transaction was recovered. Start a fresh update check before applying anything else.",
            parent=self.frame.winfo_toplevel(),
        )

    def _close_collection_current_refresh_preview(self):
        dialog = self.collection_current_refresh_preview_dialog
        self.collection_current_refresh_preview_dialog = None
        if dialog is not None and dialog.is_open:
            dialog.close()

    def _close_collection_update_plan_preview(self):
        dialog = self.collection_update_plan_preview_dialog
        self.collection_update_plan_preview_dialog = None
        if dialog is not None and dialog.is_open:
            dialog.close()

    def _clear_collection_update_state(self):
        self._last_collection_update_selection = None
        self._last_collection_update_merge_review = None
        self._last_collection_update_merge_decision = None
        self._last_collection_update_plan = None
        self._last_collection_current_refresh_plan = None
        self._last_collection_current_rom_disposition_review = None

    def _collection_update_state_is_saved(self):
        parent = self.frame.winfo_toplevel()
        if getattr(self.data_manager, "unsaved_changes", False):
            messagebox.showinfo(
                "SMWC Replacement Plan Preview",
                "Collection changes are still waiting for the normal delayed save. Wait for "
                "them to save before finalizing the replacement preview.",
                parent=parent,
            )
            return False
        if self._planner_has_unsaved_changes():
            messagebox.showinfo(
                "SMWC Replacement Plan Preview",
                "Planner changes are still unsaved. Save or discard them before finalizing "
                "the replacement preview so Planner Collection-ID references participate in "
                "the same immutable transaction state.",
                parent=parent,
            )
            return False
        return True

    def _collection_update_discovery_closed(self):
        self.collection_update_discovery_dialog = None



    def _open_collection_import(self):
        """Open the real-source import picker without applying any Collection changes."""
        if self._collection_ingestion_busy:
            return
        if (
            self.collection_ingestion_plan_preview_dialog is not None
            and self.collection_ingestion_plan_preview_dialog.is_open
        ):
            self.collection_ingestion_plan_preview_dialog.lift()
            return
        if (
            self.collection_ingestion_review_dialog is not None
            and self.collection_ingestion_review_dialog.is_open
        ):
            self.collection_ingestion_review_dialog.lift()
            return
        if (
            self.collection_ingestion_source_dialog is not None
            and self.collection_ingestion_source_dialog.is_open
        ):
            self.collection_ingestion_source_dialog.lift()
            return

        if not self._collection_ingestion_state_is_saved():
            return

        from ui.collection_ingestion_source_dialog import (
            CollectionIngestionSourceDialog,
        )

        default_root = str(self.config_manager.get("output_dir", "") or "")
        parent = self.frame.winfo_toplevel()
        self.collection_ingestion_source_dialog = CollectionIngestionSourceDialog(
            parent,
            default_rom_root=default_root,
            on_start=self._start_collection_ingestion_review,
            on_close=self._collection_ingestion_source_closed,
        )
        self.collection_ingestion_source_dialog.show()

    def _collection_ingestion_source_closed(self):
        self.collection_ingestion_source_dialog = None

    def _start_collection_ingestion_review(self, selection):
        """Build the immutable ingestion session on a worker thread."""
        if self._collection_ingestion_busy:
            return False
        if not self._collection_ingestion_state_is_saved():
            return False

        from collection_ingestion_entrypoint import known_difficulties_from_config
        from ui.collection_ingestion_source_dialog import (
            CollectionIngestionProgressDialog,
        )

        self._collection_ingestion_busy = True
        self._active_collection_ingestion_session = None
        self._last_collection_ingestion_review_decisions = None
        self._last_collection_ingestion_convergence_decisions = None
        self._last_collection_ingestion_plan = None
        parent = self.frame.winfo_toplevel()
        self.collection_ingestion_progress_dialog = CollectionIngestionProgressDialog(parent)
        self.collection_ingestion_progress_dialog.show()
        processed_json_path = str(self.data_manager.json_path)
        known_difficulties = known_difficulties_from_config(
            dict(self.config_manager.config)
        )
        self._log("📥 Preparing Collection import review session", "Information")

        worker = threading.Thread(
            target=self._collection_ingestion_worker,
            args=(processed_json_path, selection, known_difficulties),
            daemon=True,
            name="collection-ingestion-review",
        )
        worker.start()
        self._schedule_collection_ingestion_poll()
        return True

    def _collection_ingestion_worker(
        self,
        processed_json_path,
        selection,
        known_difficulties,
    ):
        try:
            from collection_ingestion_entrypoint import (
                create_collection_ingestion_review_session,
            )

            session = create_collection_ingestion_review_session(
                processed_json_path,
                selection,
                known_difficulties=known_difficulties,
            )
        except Exception as error:
            self._collection_ingestion_result_queue.put(("error", error))
            return
        self._collection_ingestion_result_queue.put(("ready", session))

    def _schedule_collection_ingestion_poll(self):
        if self._collection_ingestion_poll_id is not None:
            return
        try:
            if self.frame and self.frame.winfo_exists():
                self._collection_ingestion_poll_id = self.frame.after(
                    75,
                    self._poll_collection_ingestion_worker,
                )
        except (tk.TclError, AttributeError):
            self._collection_ingestion_poll_id = None

    def _poll_collection_ingestion_worker(self):
        self._collection_ingestion_poll_id = None
        try:
            state, payload = self._collection_ingestion_result_queue.get_nowait()
        except queue.Empty:
            if self._collection_ingestion_busy:
                self._schedule_collection_ingestion_poll()
            return

        if state == "ready":
            self._collection_ingestion_ready(payload)
        elif state == "plan-ready":
            self._collection_ingestion_plan_ready(payload)
        elif state == "plan-error":
            self._collection_ingestion_plan_failed(payload)
        else:
            self._collection_ingestion_failed(payload)

    def _close_collection_ingestion_progress(self):
        if self.collection_ingestion_progress_dialog is not None:
            self.collection_ingestion_progress_dialog.close()
        self.collection_ingestion_progress_dialog = None

    def _collection_ingestion_failed(self, error):
        self._close_collection_ingestion_progress()
        self._collection_ingestion_busy = False
        self._log(f"❌ Collection import review failed: {error}", "Error")
        messagebox.showerror(
            "Collection Import",
            f"Could not prepare the Collection import review:\n\n{error}",
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_ingestion_ready(self, session):
        self._close_collection_ingestion_progress()
        self._collection_ingestion_busy = False
        self._active_collection_ingestion_session = session
        self._log(
            "📥 Collection import review ready: "
            f"{len(session.groups)} group(s), "
            f"{len(session.blocking_groups)} requiring decisions",
            "Information",
        )

        from ui.collection_ingestion_review_dialog import (
            CollectionIngestionReviewDialog,
        )

        parent = self.frame.winfo_toplevel()
        self.collection_ingestion_review_dialog = CollectionIngestionReviewDialog(
            parent,
            session,
            on_complete=self._collection_ingestion_review_complete,
            on_close=self._collection_ingestion_review_closed,
        )
        self.collection_ingestion_review_dialog.show()

    def _collection_ingestion_review_complete(self, decisions):
        """Resolve any cross-group ROM convergence before plan finalization."""
        if self._collection_ingestion_busy:
            return False
        if not self._collection_ingestion_state_is_saved():
            return False
        session = self._active_collection_ingestion_session
        if session is None:
            messagebox.showerror(
                "Collection Import",
                "The reviewed Collection import session is no longer available.",
                parent=self.frame.winfo_toplevel(),
            )
            return False

        self._last_collection_ingestion_review_decisions = dict(decisions)
        self._last_collection_ingestion_plan = None
        try:
            from collection_ingestion_convergence_review import (
                build_converged_rom_reviews,
            )

            reviews = build_converged_rom_reviews(
                session.groups,
                decisions,
                existing_collection_keys=session.existing_collection_keys,
            )
        except Exception as error:
            self._log(
                f"❌ Collection import convergence review failed: {error}",
                "Error",
            )
            messagebox.showerror(
                "Collection Import",
                f"Could not prepare combined ROM review:\n\n{error}",
                parent=self.frame.winfo_toplevel(),
            )
            return False

        if reviews:
            self._open_collection_ingestion_convergence_review(reviews)
            return True

        self._last_collection_ingestion_convergence_decisions = {}
        dialog = self.collection_ingestion_review_dialog
        if dialog is not None and dialog.is_open:
            dialog.set_converged_rom_decisions({})
        return self._begin_collection_ingestion_finalization(decisions, {})

    def _open_collection_ingestion_convergence_review(self, reviews):
        """Collect one primary-ROM choice across groups sharing a new target."""
        if (
            self.collection_ingestion_convergence_review_dialog is not None
            and self.collection_ingestion_convergence_review_dialog.is_open
        ):
            self.collection_ingestion_convergence_review_dialog.lift()
            return

        from ui.collection_ingestion_convergence_review_dialog import (
            CollectionIngestionConvergenceReviewDialog,
        )

        valid_targets = {review.target_key for review in reviews}
        previous = {
            key: value
            for key, value in dict(
                self._last_collection_ingestion_convergence_decisions or {}
            ).items()
            if key in valid_targets
        }
        parent = (
            self.collection_ingestion_review_dialog.win
            if self.collection_ingestion_review_dialog is not None
            and self.collection_ingestion_review_dialog.is_open
            else self.frame.winfo_toplevel()
        )
        self.collection_ingestion_convergence_review_dialog = (
            CollectionIngestionConvergenceReviewDialog(
                parent,
                reviews,
                decisions=previous,
                on_complete=self._collection_ingestion_convergence_review_complete,
                on_close=self._collection_ingestion_convergence_review_closed,
            )
        )
        self.collection_ingestion_convergence_review_dialog.show()

    def _collection_ingestion_convergence_review_complete(self, decisions):
        if self._collection_ingestion_busy:
            return False
        group_decisions = self._last_collection_ingestion_review_decisions
        if group_decisions is None:
            return False
        self._last_collection_ingestion_convergence_decisions = dict(decisions)
        dialog = self.collection_ingestion_review_dialog
        if dialog is not None and dialog.is_open:
            dialog.set_converged_rom_decisions(decisions)
        return self._begin_collection_ingestion_finalization(
            group_decisions,
            decisions,
        )

    def _collection_ingestion_convergence_review_closed(self):
        self.collection_ingestion_convergence_review_dialog = None
        if not self._collection_ingestion_busy:
            dialog = self.collection_ingestion_review_dialog
            if dialog is not None and dialog.is_open:
                dialog.set_submitting(False)
                dialog.lift()

    def _begin_collection_ingestion_finalization(
        self,
        decisions,
        converged_rom_decisions,
    ):
        """Hydrate completed review into an immutable plan on a worker thread."""
        if self._collection_ingestion_busy:
            return False
        if not self._collection_ingestion_state_is_saved():
            return False
        if self._active_collection_ingestion_session is None:
            return False

        review_dialog = self.collection_ingestion_review_dialog
        if review_dialog is not None and review_dialog.is_open:
            review_dialog.set_submitting(True)

        self._collection_ingestion_busy = True
        parent = self.frame.winfo_toplevel()
        from ui.collection_ingestion_plan_preview_dialog import (
            CollectionIngestionFinalizationProgressDialog,
        )

        self.collection_ingestion_finalization_progress_dialog = (
            CollectionIngestionFinalizationProgressDialog(parent)
        )
        self.collection_ingestion_finalization_progress_dialog.show()
        processed_json_path = str(self.data_manager.json_path)
        self._log(
            "📋 Finalizing reviewed Collection import plan for preview",
            "Information",
        )
        worker = threading.Thread(
            target=self._collection_ingestion_finalization_worker,
            args=(
                processed_json_path,
                self._active_collection_ingestion_session,
                dict(decisions),
                dict(converged_rom_decisions or {}),
            ),
            daemon=True,
            name="collection-ingestion-finalization",
        )
        worker.start()
        self._schedule_collection_ingestion_poll()
        return True

    def _collection_ingestion_finalization_worker(
        self,
        processed_json_path,
        session,
        decisions,
        converged_rom_decisions,
    ):
        try:
            from collection_ingestion_entrypoint import (
                finalize_collection_ingestion_review_plan,
            )

            plan = finalize_collection_ingestion_review_plan(
                processed_json_path,
                session,
                decisions,
                converged_rom_decisions=converged_rom_decisions,
            )
        except Exception as error:
            self._collection_ingestion_result_queue.put(("plan-error", error))
            return
        self._collection_ingestion_result_queue.put(("plan-ready", plan))

    def _close_collection_ingestion_finalization_progress(self):
        if self.collection_ingestion_finalization_progress_dialog is not None:
            self.collection_ingestion_finalization_progress_dialog.close()
        self.collection_ingestion_finalization_progress_dialog = None

    def _collection_ingestion_plan_failed(self, error):
        self._close_collection_ingestion_finalization_progress()
        self._collection_ingestion_busy = False
        self._last_collection_ingestion_plan = None
        review_dialog = self.collection_ingestion_review_dialog
        if review_dialog is not None and review_dialog.is_open:
            review_dialog.set_submitting(False)
            review_dialog.set_diagnostic_error(error)
            review_dialog.lift()
        self._log(f"❌ Collection import plan finalization failed: {error}", "Error")
        messagebox.showerror(
            "Collection Import Preview",
            "Could not build the final Collection import preview:\n\n"
            f"{error}\n\n"
            "Nothing was applied. Your review choices are still open and can be "
            "adjusted or retried. If reviewed Collection or dependent state changed, "
            "start a new import review.",
            parent=(
                review_dialog.win
                if review_dialog is not None and review_dialog.is_open
                else self.frame.winfo_toplevel()
            ),
        )

    def _collection_ingestion_plan_ready(self, plan):
        self._close_collection_ingestion_finalization_progress()
        self._collection_ingestion_busy = False
        self._last_collection_ingestion_plan = plan
        review_dialog = self.collection_ingestion_review_dialog
        if review_dialog is not None and review_dialog.is_open:
            review_dialog.close()
        self._log(
            "✅ Final Collection import plan ready for preview and explicit confirmation",
            "Information",
        )

        from ui.collection_ingestion_plan_preview_dialog import (
            CollectionIngestionPlanPreviewDialog,
        )

        parent = self.frame.winfo_toplevel()
        self.collection_ingestion_plan_preview_dialog = (
            CollectionIngestionPlanPreviewDialog(
                parent,
                plan,
                on_apply=self._collection_ingestion_apply_requested,
                on_close=self._collection_ingestion_plan_preview_closed,
            )
        )
        self.collection_ingestion_plan_preview_dialog.show()


    def _collection_ingestion_apply_requested(self):
        """Cross the explicit final-confirmation boundary for the frozen plan."""
        if self._collection_ingestion_busy:
            return False
        if self._last_collection_ingestion_plan is None:
            messagebox.showerror(
                "Collection Import",
                "The finalized Collection import plan is no longer available.",
                parent=self.frame.winfo_toplevel(),
            )
            return False
        if not self._collection_ingestion_state_is_saved():
            return False

        from ui.collection_ingestion_plan_preview_dialog import (
            CollectionIngestionApplyProgressDialog,
        )

        self._collection_ingestion_busy = True
        parent = self.frame.winfo_toplevel()
        self.collection_ingestion_apply_progress_dialog = (
            CollectionIngestionApplyProgressDialog(parent)
        )
        self.collection_ingestion_apply_progress_dialog.show()
        self._log(
            "💾 Applying finalized Collection import plan transactionally",
            "Information",
        )
        # Apply is intentionally scheduled back onto the Tk thread. It is a short
        # local filesystem transaction and must serialize with the live manager.
        self.frame.after(1, self._execute_collection_ingestion_apply)
        return True

    def _execute_collection_ingestion_apply(self):
        from collection_plan_apply import (
            CollectionPlanRecoveryError,
            CollectionPlanStaleStateError,
        )

        plan = self._last_collection_ingestion_plan
        if plan is None:
            self._collection_ingestion_apply_failed(
                RuntimeError("Finalized Collection import plan is missing.")
            )
            return

        try:
            from collection_ingestion_entrypoint import (
                apply_collection_ingestion_plan,
                collection_ingestion_apply_recovery_pending,
                recover_collection_ingestion_apply,
            )
            result = apply_collection_ingestion_plan(
                str(self.data_manager.json_path),
                plan,
                manager=self.data_manager,
            )
        except CollectionPlanStaleStateError as error:
            self._collection_ingestion_apply_stale(error)
            return
        except CollectionPlanRecoveryError as error:
            self._collection_ingestion_recovery_required(error)
            return
        except Exception as error:
            self._collection_ingestion_apply_failed(error)
            return

        cleanup_error = None
        if collection_ingestion_apply_recovery_pending(self.data_manager.json_path):
            try:
                # apply_collection_change_plan has already crossed its committed
                # journal point if it returned successfully. A remaining journal
                # is therefore cleanup-only and safe to finish in this instance.
                recover_collection_ingestion_apply(self.data_manager.json_path)
            except Exception as error:
                cleanup_error = error
        self._collection_ingestion_apply_succeeded(result, cleanup_error)

    def _close_collection_ingestion_apply_progress(self):
        if self.collection_ingestion_apply_progress_dialog is not None:
            self.collection_ingestion_apply_progress_dialog.close()
        self.collection_ingestion_apply_progress_dialog = None

    def _collection_ingestion_apply_succeeded(self, result, cleanup_error=None):
        self._close_collection_ingestion_apply_progress()
        self._collection_ingestion_busy = False
        self._reload_collection_ingestion_live_state()
        self._close_collection_ingestion_plan_preview()
        self._clear_collection_ingestion_review_state()

        self._log(
            "✅ Collection import applied transactionally: "
            f"{result.collection_record_count} Collection record(s), "
            f"{len(result.written_files)} file(s) written",
            "Information",
        )
        cleanup_note = ""
        if cleanup_error is not None:
            cleanup_note = (
                "\n\nThe transaction itself committed successfully, but its recovery/cleanup "
                f"journal could not be removed: {cleanup_error}\n\n"
                "Do not start another Collection import until that journal is recovered."
            )
            self._log(
                f"⚠️ Collection import committed but journal cleanup failed: {cleanup_error}",
                "Warning",
            )
        messagebox.showinfo(
            "Collection Import Applied",
            (
                "The finalized Collection import was applied successfully.\n\n"
                f"Collection records: {result.collection_record_count}\n"
                f"Files written transactionally: {len(result.written_files)}\n"
                f"Identity migrations: {result.identity_migration_count}\n"
                f"Dependent reference stores participating: {result.reference_participant_count}"
                f"{cleanup_note}"
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_ingestion_apply_stale(self, error):
        self._close_collection_ingestion_apply_progress()
        self._collection_ingestion_busy = False
        self._log(f"⚠️ Collection import plan became stale: {error}", "Warning")
        self._close_collection_ingestion_plan_preview()
        self._clear_collection_ingestion_review_state()
        messagebox.showerror(
            "Collection Import Changed",
            (
                "The reviewed Collection or dependent state changed before Apply, "
                "so the finalized plan was rejected.\n\n"
                f"{error}\n\nStart a new Collection import review. Nothing from this "
                "stale plan was applied."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_ingestion_apply_failed(self, error):
        self._close_collection_ingestion_apply_progress()
        self._collection_ingestion_busy = False
        if (
            self.collection_ingestion_plan_preview_dialog is not None
            and self.collection_ingestion_plan_preview_dialog.is_open
        ):
            self.collection_ingestion_plan_preview_dialog.set_applying(False)
        self._log(f"❌ Collection import Apply failed: {error}", "Error")
        messagebox.showerror(
            "Collection Import Failed",
            (
                "The transactional Collection import could not be committed.\n\n"
                f"{error}\n\nNo reviewed plan change was committed; any prepared "
                "transaction was rolled back. You may close "
                "the preview or retry if the underlying problem has been corrected."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _collection_ingestion_recovery_required(self, error):
        self._close_collection_ingestion_apply_progress()
        self._collection_ingestion_busy = False
        self._log(f"⚠️ Collection import recovery required: {error}", "Warning")
        if (
            self.collection_ingestion_plan_preview_dialog is not None
            and self.collection_ingestion_plan_preview_dialog.is_open
        ):
            self.collection_ingestion_plan_preview_dialog.set_applying(False)

        recover_now = messagebox.askyesno(
            "Collection Import Recovery Required",
            (
                "A coordinated Collection transaction journal still exists. This can "
                "mean another application instance is currently applying changes, or "
                "a previous Apply was interrupted.\n\n"
                f"{error}\n\n"
                "Close every other SMWC Downloader & Patcher instance first. Only "
                "choose Yes after you have confirmed no other instance is applying "
                "Collection changes. Recovery may roll back a prepared transaction "
                "or finish cleanup for an already committed one.\n\nRecover now?"
            ),
            icon="warning",
            parent=self.frame.winfo_toplevel(),
        )
        if not recover_now:
            return
        self._run_collection_ingestion_recovery()

    def _run_collection_ingestion_recovery(self):
        from collection_ingestion_entrypoint import recover_collection_ingestion_apply
        from ui.collection_ingestion_plan_preview_dialog import (
            CollectionIngestionApplyProgressDialog,
        )

        self._collection_ingestion_busy = True
        parent = self.frame.winfo_toplevel()
        self.collection_ingestion_apply_progress_dialog = (
            CollectionIngestionApplyProgressDialog(parent, recovery=True)
        )
        self.collection_ingestion_apply_progress_dialog.show()
        try:
            recovered = recover_collection_ingestion_apply(self.data_manager.json_path)
        except Exception as error:
            self._close_collection_ingestion_apply_progress()
            self._collection_ingestion_busy = False
            self._log(f"❌ Collection import recovery failed: {error}", "Error")
            messagebox.showerror(
                "Collection Import Recovery Failed",
                (
                    "The transaction journal could not be recovered safely.\n\n"
                    f"{error}\n\nDo not start another Collection import until the "
                    "recovery issue has been resolved."
                ),
                parent=parent,
            )
            return

        self._close_collection_ingestion_apply_progress()
        self._collection_ingestion_busy = False
        self._reload_collection_ingestion_live_state()
        self._close_collection_ingestion_plan_preview()
        self._clear_collection_ingestion_review_state()
        self._log(
            "✅ Collection import transaction recovery completed",
            "Information",
        )
        messagebox.showinfo(
            "Collection Import Recovery Complete",
            (
                "The interrupted Collection transaction was recovered and live "
                "application state was reloaded.\n\n"
                + (
                    "Start a new Collection import review before applying anything else."
                    if recovered
                    else "No recovery journal remained. Start a new review if needed."
                )
            ),
            parent=parent,
        )

    def _reload_collection_ingestion_live_state(self):
        """Best-effort reload after a transaction has already committed/recovered."""
        try:
            self.data_manager.reload_data()
            self.config_manager.reload()
            self._emulator_path = self.config_manager.get("emulator_path", "")
            self._show_rom_picker = self.config_manager.get("show_rom_picker", False)
            self.filters.refresh_dropdown_values(self.data_manager)
            if self.tree:
                self._apply_filters()
                self._refresh_table()

            root = self.frame.winfo_toplevel()
            layout = getattr(root, "main_layout", None)
            setup_section = getattr(layout, "setup_section", None)
            setup_config = getattr(setup_section, "config", None)
            if setup_config is not None and hasattr(setup_config, "reload"):
                setup_config.reload()

            settings_page = getattr(layout, "settings_page", None)
            if (
                settings_page is not None
                and hasattr(settings_page, "_load_save_sync_settings")
            ):
                settings_page._load_save_sync_settings()

            planner_page = getattr(layout, "planner_page", None)
            if planner_page is not None and hasattr(planner_page, "refresh"):
                planner_page.refresh(reload_planner=True)
        except Exception as error:
            self._log(
                f"⚠️ Collection transaction completed but a live UI refresh failed: {error}",
                "Warning",
            )

    def _close_collection_ingestion_plan_preview(self):
        dialog = self.collection_ingestion_plan_preview_dialog
        self.collection_ingestion_plan_preview_dialog = None
        if dialog is not None and dialog.is_open:
            dialog.close()

    def _clear_collection_ingestion_review_state(self):
        self._active_collection_ingestion_session = None
        self._last_collection_ingestion_review_decisions = None
        self._last_collection_ingestion_convergence_decisions = None
        self._last_collection_ingestion_plan = None

    def _collection_ingestion_plan_preview_closed(self):
        self.collection_ingestion_plan_preview_dialog = None
        self.collection_ingestion_apply_progress_dialog = None

    def _collection_ingestion_review_closed(self):
        self.collection_ingestion_review_dialog = None

    def _collection_ingestion_state_is_saved(self):
        """Require disk-backed Collection/dependent state before review/finalization."""
        parent = self.frame.winfo_toplevel()
        if self.data_manager.unsaved_changes:
            messagebox.showinfo(
                "Collection Import",
                "Collection edits are still waiting to be saved. "
                "Wait a moment and try again so ingestion uses a stable Collection snapshot.",
                parent=parent,
            )
            return False
        if self._planner_has_unsaved_changes():
            messagebox.showinfo(
                "Collection Import",
                "Planner changes are still unsaved. Save or discard them before "
                "continuing so any Planner Collection-ID references participate in "
                "the same reviewed transaction state.",
                parent=parent,
            )
            return False
        return True

    def _planner_has_unsaved_changes(self):
        """Inspect optional live Planner state without making Planner an ingestion dependency."""
        try:
            root = self.frame.winfo_toplevel()
            layout = getattr(root, "main_layout", None)
            planner_page = getattr(layout, "planner_page", None)
            model = getattr(planner_page, "model", None)
            return bool(getattr(model, "has_unsaved_changes", False))
        except (tk.TclError, AttributeError):
            return False

    def _open_collection_rom_organization_audit(self):
        """Show a read-only audit of Collection ROM layout drift."""
        if self.collection_rom_organization_audit_dialog is not None:
            try:
                self.collection_rom_organization_audit_dialog.dialog.lift()
                self.collection_rom_organization_audit_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_organization_audit_dialog = None

        output_dir = str(self.config_manager.get("output_dir", "") or "").strip()
        if not output_dir:
            messagebox.showinfo(
                "ROM Organization Audit",
                "Configure the ROM output directory in Settings before auditing the "
                "Collection library layout.",
                parent=self.frame,
            )
            return

        try:
            audit = build_collection_rom_organization_audit(
                copy.deepcopy(self.data_manager.data),
                output_dir,
            )
        except (TypeError, ValueError, OSError) as error:
            self._log(f"ROM organization audit failed: {error}", "Error")
            messagebox.showerror(
                "ROM Organization Audit",
                f"The Collection ROM layout could not be audited safely:\n\n{error}",
                parent=self.frame,
            )
            return

        dialog = CollectionRomOrganizationAuditDialog(
            self.frame,
            audit,
            on_close=self._collection_rom_organization_audit_closed,
            on_preview_plan=self._preview_collection_rom_organization_plan,
            on_review_legacy_metadata=self._review_collection_legacy_rom_metadata,
            on_review_historical_provenance=self._review_collection_historical_rom_provenance,
            on_review_missing_provenance=self._review_collection_modern_rom_provenance,
        )
        self.collection_rom_organization_audit_dialog = dialog

    def _review_collection_modern_rom_provenance(self, audit):
        """Review explicit ownership for modern files[] rows missing SMWC provenance."""
        if self.collection_rom_modern_provenance_dialog is not None:
            try:
                self.collection_rom_modern_provenance_dialog.dialog.lift()
                self.collection_rom_modern_provenance_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_modern_provenance_dialog = None

        try:
            from collection_plan_apply import collection_revision_token

            revision = collection_revision_token(self.data_manager)
            review = build_modern_rom_provenance_review(
                audit,
                copy.deepcopy(self.data_manager.data),
                revision,
            )
        except (ModernRomProvenanceReviewError, TypeError, ValueError) as error:
            self._log(f"Modern ROM provenance review failed: {error}", "Error")
            messagebox.showerror(
                "Modern ROM Provenance",
                f"Missing per-ROM provenance could not be reviewed safely:\n\n{error}",
                parent=self.frame,
            )
            return

        self._last_collection_modern_provenance_review = review
        self._last_collection_modern_provenance_decision = None
        self.collection_rom_modern_provenance_dialog = CollectionRomModernProvenanceDialog(
            self.frame,
            review,
            on_close=self._collection_rom_modern_provenance_closed,
            on_saved=self._collection_rom_modern_provenance_saved,
            on_apply=self._apply_collection_modern_rom_provenance,
        )

    def _collection_rom_modern_provenance_saved(self, review, decision):
        self._last_collection_modern_provenance_review = review
        self._last_collection_modern_provenance_decision = decision


    def _apply_collection_modern_rom_provenance(self, review, decision, parent_dialog):
        """Atomically repair only reviewed missing modern per-ROM provenance."""
        dialog = self.collection_rom_modern_provenance_dialog
        if (
            dialog is None
            or dialog.review != review
            or self._last_collection_modern_provenance_decision != decision
        ):
            messagebox.showerror(
                "Apply Modern ROM Provenance",
                "The provenance review is no longer active. Run the ROM organization audit again.",
                parent=parent_dialog,
            )
            return

        if not messagebox.askyesno(
            "Apply Modern ROM Provenance",
            (
                f"Write reviewed SMWC provenance for {len(decision.selections)} ROM asset(s)?\n\n"
                "This changes Collection files[] metadata only. ROM and save files are not moved, renamed, "
                "hashed, downloaded, or otherwise modified."
            ),
            parent=parent_dialog,
        ):
            return

        from collection_rom_modern_provenance_apply import (
            ModernRomProvenanceApplyError,
            ModernRomProvenanceApplyStaleStateError,
            apply_modern_rom_provenance_decision,
        )

        try:
            parent_dialog.configure(cursor="wait")
            parent_dialog.update_idletasks()
            result = apply_modern_rom_provenance_decision(
                review, decision, self.data_manager
            )
        except (
            ModernRomProvenanceApplyStaleStateError,
            ModernRomProvenanceApplyError,
            OSError,
        ) as error:
            self._log(f"Modern ROM provenance repair failed: {error}", "Error")
            messagebox.showerror(
                "Modern ROM Provenance Not Applied",
                (
                    "The reviewed provenance repair could not be applied safely. "
                    "Collection data was not partially changed.\n\n"
                    f"{error}\n\nRun the ROM organization audit again before retrying."
                ),
                parent=parent_dialog,
            )
            return
        finally:
            try:
                if parent_dialog.winfo_exists():
                    parent_dialog.configure(cursor="")
            except tk.TclError:
                pass

        self._reload_collection_ingestion_live_state()
        self._close_collection_rom_organization_workflow()
        self._log(
            f"Repaired SMWC provenance for {result.asset_count} Collection ROM asset(s)",
            "Information",
        )
        messagebox.showinfo(
            "Modern ROM Provenance Updated",
            (
                f"Updated SMWC provenance for {result.asset_count} ROM asset(s) across "
                f"{result.collection_record_count} Collection record(s).\n\n"
                "ROM/save files and unrelated Collection metadata were not changed. "
                "Run the ROM organization audit again to reassess layout."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _review_collection_historical_rom_provenance(self, audit):
        """Fetch only recorded historical submission metadata for read-only layout review."""
        if self._collection_rom_historical_provenance_busy:
            return
        if self.collection_rom_historical_provenance_dialog is not None:
            try:
                self.collection_rom_historical_provenance_dialog.dialog.lift()
                self.collection_rom_historical_provenance_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_historical_provenance_dialog = None

        from collection_plan_apply import collection_revision_token
        from collection_rom_historical_provenance import required_historical_submission_ids
        from ui.collection_rom_historical_provenance_dialog import (
            HistoricalRomProvenanceProgressDialog,
        )

        identifiers = required_historical_submission_ids(audit)
        if not identifiers:
            messagebox.showinfo(
                "Historical ROM Provenance",
                "This audit has no retained ROM assets with an explicit historical SMWC submission ID.",
                parent=self.frame,
            )
            return

        frozen_collection = copy.deepcopy(self.data_manager.data)
        revision = collection_revision_token(self.data_manager)
        processed_path = str(self.data_manager.json_path)
        self._collection_rom_historical_provenance_busy = True
        self.collection_rom_historical_provenance_progress_dialog = (
            HistoricalRomProvenanceProgressDialog(self.frame)
        )
        self._log(
            "Reviewing retained ROM layout from recorded historical SMWC provenance: "
            + ", ".join(str(identifier) for identifier in identifiers),
            "Information",
        )

        def worker():
            try:
                from kaizoff_provider import KaizOffCatalogueProvider
                from collection_rom_historical_provenance import (
                    build_historical_rom_provenance_review,
                )

                processed = Path(processed_path).expanduser().resolve()
                provider = KaizOffCatalogueProvider(
                    cache_dir=processed.with_name("kaizoff_cache")
                )
                details = tuple(provider.get_hack(identifier) for identifier in identifiers)
                review = build_historical_rom_provenance_review(
                    audit, frozen_collection, revision, details
                )
                self._collection_rom_historical_provenance_queue.put(("ok", review))
            except Exception as error:
                self._collection_rom_historical_provenance_queue.put(("error", error))

        threading.Thread(
            target=worker,
            daemon=True,
            name="collection-rom-historical-provenance",
        ).start()
        self._collection_rom_historical_provenance_poll_id = self.frame.after(
            100, self._poll_collection_historical_rom_provenance
        )

    def _poll_collection_historical_rom_provenance(self):
        try:
            status, payload = self._collection_rom_historical_provenance_queue.get_nowait()
        except queue.Empty:
            self._collection_rom_historical_provenance_poll_id = self.frame.after(
                100, self._poll_collection_historical_rom_provenance
            )
            return

        self._collection_rom_historical_provenance_poll_id = None
        self._collection_rom_historical_provenance_busy = False
        if self.collection_rom_historical_provenance_progress_dialog is not None:
            self.collection_rom_historical_provenance_progress_dialog.close()
            self.collection_rom_historical_provenance_progress_dialog = None

        if status != "ok":
            self._log(f"Historical ROM provenance review failed: {payload}", "Error")
            messagebox.showerror(
                "Historical ROM Provenance",
                f"Historical submission metadata could not be reviewed safely:\n\n{payload}",
                parent=self.frame,
            )
            return

        from collection_plan_apply import collection_revision_token
        if collection_revision_token(self.data_manager) != payload.collection_revision_token:
            messagebox.showerror(
                "Historical ROM Provenance",
                "Collection changed while historical metadata was loading. Run the ROM organization audit again.",
                parent=self.frame,
            )
            return

        from ui.collection_rom_historical_provenance_dialog import (
            CollectionRomHistoricalProvenanceDialog,
        )
        self.collection_rom_historical_provenance_dialog = (
            CollectionRomHistoricalProvenanceDialog(
                self.frame,
                payload,
                on_close=self._collection_rom_historical_provenance_closed,
                on_preview_plan=self._preview_collection_historical_rom_organization_plan,
            )
        )

    def _preview_collection_historical_rom_organization_plan(self, review):
        """Freeze historical-review ready rows into an immutable read-only move plan."""
        if self.collection_rom_historical_organization_plan_dialog is not None:
            try:
                self.collection_rom_historical_organization_plan_dialog.dialog.lift()
                self.collection_rom_historical_organization_plan_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_historical_organization_plan_dialog = None

        try:
            from collection_plan_apply import collection_revision_token
            from collection_rom_historical_organization_plan import (
                HistoricalRomOrganizationPlanError,
                build_historical_rom_organization_plan,
            )
            from ui.collection_rom_historical_organization_plan_dialog import (
                CollectionRomHistoricalOrganizationPlanDialog,
            )

            plan = build_historical_rom_organization_plan(
                review,
                copy.deepcopy(self.data_manager.data),
                collection_revision_token(self.data_manager),
            )
        except (HistoricalRomOrganizationPlanError, OSError, ValueError) as error:
            self._log(f"Historical ROM organization plan preview failed: {error}", "Error")
            messagebox.showerror(
                "Historical ROM Organization Plan",
                f"The historical ROM move plan could not be frozen safely:\\n\\n{error}",
                parent=self.frame,
            )
            return

        if self.collection_rom_historical_provenance_dialog is not None:
            self.collection_rom_historical_provenance_dialog.close()

        self._last_collection_historical_rom_save_disposition_review = None
        self._last_collection_historical_rom_save_disposition_decision = None
        self.collection_rom_historical_organization_plan_dialog = (
            CollectionRomHistoricalOrganizationPlanDialog(
                self.frame,
                plan,
                on_close=self._collection_rom_historical_organization_plan_closed,
                on_review_save_impact=self._review_collection_rom_save_impact,
                on_preview_execution_plan=self._preview_collection_historical_rom_organization_execution_plan,
            )
        )

    def _review_collection_legacy_rom_metadata(self):
        """Show a read-only audit of file_path-only Collection ROM records."""
        if self.collection_rom_legacy_metadata_dialog is not None:
            try:
                self.collection_rom_legacy_metadata_dialog.dialog.lift()
                self.collection_rom_legacy_metadata_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_legacy_metadata_dialog = None

        try:
            from collection_plan_apply import collection_revision_token

            audit = build_legacy_rom_metadata_audit(
                copy.deepcopy(self.data_manager.data),
                collection_revision_token(self.data_manager),
            )
        except (TypeError, ValueError, OSError) as error:
            self._log(f"Legacy ROM metadata audit failed: {error}", "Error")
            messagebox.showerror(
                "Legacy ROM Metadata",
                f"Legacy Collection ROM metadata could not be audited safely:\n\n{error}",
                parent=self.frame,
            )
            return

        dialog = CollectionRomLegacyMetadataDialog(
            self.frame,
            audit,
            on_close=self._collection_rom_legacy_metadata_closed,
            on_preview_plan=self._preview_collection_legacy_rom_metadata_plan,
            on_review_provenance=self._review_collection_legacy_rom_provenance,
        )
        self.collection_rom_legacy_metadata_dialog = dialog

    def _review_collection_legacy_rom_provenance(self, audit):
        """Collect explicit provenance decisions for ambiguous migrated legacy ROMs."""
        if self.collection_rom_legacy_provenance_dialog is not None:
            try:
                self.collection_rom_legacy_provenance_dialog.dialog.lift()
                self.collection_rom_legacy_provenance_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_legacy_provenance_dialog = None

        try:
            from collection_plan_apply import collection_revision_token

            review = build_legacy_rom_provenance_review(
                audit,
                copy.deepcopy(self.data_manager.data),
                collection_revision_token(self.data_manager),
            )
        except (LegacyRomProvenanceReviewError, OSError, ValueError) as error:
            self._log(f"Legacy ROM provenance review failed: {error}", "Error")
            messagebox.showerror(
                "Legacy ROM Provenance",
                f"Legacy ROM provenance could not be reviewed safely:\n\n{error}",
                parent=self.frame,
            )
            return

        self._last_collection_legacy_provenance_review = None
        self._last_collection_legacy_provenance_decision = None
        self.collection_rom_legacy_provenance_dialog = CollectionRomLegacyProvenanceDialog(
            self.frame,
            review,
            on_close=self._collection_rom_legacy_provenance_closed,
            on_saved=self._collection_rom_legacy_provenance_saved,
            on_preview_plan=self._preview_collection_legacy_rom_provenance_plan,
        )

    def _collection_rom_legacy_provenance_saved(self, review, decision):
        self._last_collection_legacy_provenance_review = review
        self._last_collection_legacy_provenance_decision = decision
        self._log(
            f"Saved explicit legacy ROM provenance for {len(decision.selections)} record(s)",
            "Information",
        )

    def _preview_collection_legacy_rom_provenance_plan(self, review, decision):
        """Hash/revalidate explicitly attributed ambiguous legacy ROMs into a read-only plan."""
        if self.collection_rom_legacy_provenance_plan_dialog is not None:
            try:
                self.collection_rom_legacy_provenance_plan_dialog.dialog.lift()
                self.collection_rom_legacy_provenance_plan_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_legacy_provenance_plan_dialog = None

        if (
            self._last_collection_legacy_provenance_review != review
            or self._last_collection_legacy_provenance_decision != decision
        ):
            messagebox.showerror(
                "Reviewed Legacy ROM Metadata Plan",
                "The saved provenance review is no longer active. Run the legacy metadata audit again.",
                parent=self.frame,
            )
            return

        audit_dialog = self.collection_rom_legacy_metadata_dialog
        if audit_dialog is None:
            messagebox.showerror(
                "Reviewed Legacy ROM Metadata Plan",
                "The legacy metadata audit is no longer active. Run the audit again.",
                parent=self.frame,
            )
            return

        try:
            from collection_plan_apply import collection_revision_token

            plan = build_reviewed_legacy_rom_metadata_modernization_plan(
                audit_dialog.audit,
                review,
                decision,
                copy.deepcopy(self.data_manager.data),
                collection_revision_token(self.data_manager),
            )
        except (LegacyRomMetadataPlanError, OSError, ValueError) as error:
            self._log(f"Reviewed legacy ROM metadata plan preview failed: {error}", "Error")
            messagebox.showerror(
                "Reviewed Legacy ROM Metadata Plan",
                f"The reviewed legacy ROM metadata modernization plan could not be frozen:\n\n{error}",
                parent=self.frame,
            )
            return

        self.collection_rom_legacy_provenance_plan_dialog = CollectionRomLegacyProvenancePlanDialog(
            self.frame,
            plan,
            on_close=self._collection_rom_legacy_provenance_plan_closed,
            on_apply=self._apply_collection_legacy_rom_provenance_plan,
        )

    def _apply_collection_legacy_rom_provenance_plan(self, plan, parent_dialog):
        """Apply only the frozen reviewed-provenance metadata backfill plan."""
        dialog = self.collection_rom_legacy_provenance_plan_dialog
        if dialog is None or dialog.plan != plan:
            messagebox.showerror(
                "Apply Reviewed Legacy ROM Metadata",
                "The reviewed modernization preview is no longer active. Run the legacy metadata audit again.",
                parent=parent_dialog,
            )
            return

        if not messagebox.askyesno(
            "Apply Reviewed Legacy ROM Metadata",
            (
                f"Write modern files[] metadata for {len(plan.operations)} explicitly attributed ROM(s)?\n\n"
                "This changes Collection metadata only. The selected SMWC provenance and exact ROM bytes "
                "will be verified again. ROM files, save files, file_path, and additional_paths will not "
                "be moved, renamed, or rewritten."
            ),
            parent=parent_dialog,
        ):
            return

        from collection_rom_legacy_metadata_apply import (
            LegacyRomMetadataApplyError,
            LegacyRomMetadataApplyStaleStateError,
            apply_reviewed_legacy_rom_metadata_modernization_plan,
        )

        try:
            parent_dialog.configure(cursor="wait")
            parent_dialog.update_idletasks()
            result = apply_reviewed_legacy_rom_metadata_modernization_plan(
                plan, self.data_manager
            )
        except (
            LegacyRomMetadataApplyStaleStateError,
            LegacyRomMetadataApplyError,
            OSError,
        ) as error:
            self._log(f"Reviewed legacy ROM metadata Apply failed: {error}", "Error")
            messagebox.showerror(
                "Reviewed Legacy ROM Metadata Not Applied",
                (
                    "The frozen reviewed metadata backfill could not be applied safely. "
                    "Collection data was not partially modernized.\n\n"
                    f"{error}\n\nRun the legacy metadata audit again before retrying."
                ),
                parent=parent_dialog,
            )
            return
        finally:
            try:
                if parent_dialog.winfo_exists():
                    parent_dialog.configure(cursor="")
            except tk.TclError:
                pass

        self._reload_collection_ingestion_live_state()
        self._close_collection_rom_organization_workflow()
        self._log(
            f"Modernized reviewed ROM metadata for {result.collection_record_count} Collection record(s)",
            "Information",
        )
        messagebox.showinfo(
            "Reviewed Legacy ROM Metadata Updated",
            (
                f"Modern files[] metadata was written for {result.collection_record_count} "
                "explicitly attributed Collection record(s). ROM and save files were not changed.\n\n"
                "Run the ROM organization audit again to reassess these records."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _preview_collection_legacy_rom_metadata_plan(self, audit):
        """Hash/revalidate audit-ready legacy ROMs into an immutable preview plan."""
        if self.collection_rom_legacy_metadata_plan_dialog is not None:
            try:
                self.collection_rom_legacy_metadata_plan_dialog.dialog.lift()
                self.collection_rom_legacy_metadata_plan_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_legacy_metadata_plan_dialog = None

        try:
            from collection_plan_apply import collection_revision_token

            plan = build_legacy_rom_metadata_modernization_plan(
                audit,
                copy.deepcopy(self.data_manager.data),
                collection_revision_token(self.data_manager),
            )
        except (LegacyRomMetadataPlanError, OSError, ValueError) as error:
            self._log(f"Legacy ROM metadata plan preview failed: {error}", "Error")
            messagebox.showerror(
                "Legacy ROM Metadata Plan",
                f"The legacy ROM metadata modernization plan could not be frozen:\n\n{error}",
                parent=self.frame,
            )
            return

        dialog = CollectionRomLegacyMetadataPlanDialog(
            self.frame,
            plan,
            on_close=self._collection_rom_legacy_metadata_plan_closed,
            on_apply=self._apply_collection_legacy_rom_metadata_plan,
        )
        self.collection_rom_legacy_metadata_plan_dialog = dialog

    def _apply_collection_legacy_rom_metadata_plan(self, plan, parent_dialog):
        """Apply only the already-frozen legacy ROM metadata backfill plan."""
        dialog = self.collection_rom_legacy_metadata_plan_dialog
        if dialog is None or dialog.plan != plan:
            messagebox.showerror(
                "Apply Legacy ROM Metadata",
                "The modernization preview is no longer active. Run the legacy metadata audit again.",
                parent=parent_dialog,
            )
            return

        if not messagebox.askyesno(
            "Apply Legacy ROM Metadata",
            (
                f"Write modern files[] metadata for {len(plan.operations)} reviewed ROM(s)?\n\n"
                "This changes Collection metadata only. ROM files, save files, file_path, "
                "and additional_paths will not be moved, renamed, or rewritten."
            ),
            parent=parent_dialog,
        ):
            return

        from collection_rom_legacy_metadata_apply import (
            LegacyRomMetadataApplyError,
            LegacyRomMetadataApplyStaleStateError,
            apply_legacy_rom_metadata_modernization_plan,
        )

        try:
            parent_dialog.configure(cursor="wait")
            parent_dialog.update_idletasks()
            result = apply_legacy_rom_metadata_modernization_plan(plan, self.data_manager)
        except (
            LegacyRomMetadataApplyStaleStateError,
            LegacyRomMetadataApplyError,
            OSError,
        ) as error:
            self._log(f"Legacy ROM metadata Apply failed: {error}", "Error")
            messagebox.showerror(
                "Legacy ROM Metadata Not Applied",
                (
                    "The frozen metadata backfill could not be applied safely. "
                    "Collection data was not partially modernized.\n\n"
                    f"{error}\n\nRun the legacy metadata audit again before retrying."
                ),
                parent=parent_dialog,
            )
            return
        finally:
            try:
                if parent_dialog.winfo_exists():
                    parent_dialog.configure(cursor="")
            except tk.TclError:
                pass

        self._reload_collection_ingestion_live_state()
        self._close_collection_rom_organization_workflow()
        self._log(
            f"Modernized ROM metadata for {result.collection_record_count} Collection record(s)",
            "Information",
        )
        messagebox.showinfo(
            "Legacy ROM Metadata Updated",
            (
                f"Modern files[] metadata was written for {result.collection_record_count} "
                "Collection record(s). ROM and save files were not changed.\n\n"
                "Run the ROM organization audit again to reassess these records."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _preview_collection_rom_organization_plan(self, audit):
        """Freeze the audit's safe move rows into an immutable read-only plan."""
        if self.collection_rom_organization_plan_dialog is not None:
            try:
                self.collection_rom_organization_plan_dialog.dialog.lift()
                self.collection_rom_organization_plan_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_organization_plan_dialog = None

        try:
            from collection_plan_apply import collection_revision_token

            revision = collection_revision_token(self.data_manager)
            plan = build_collection_rom_organization_plan(
                audit,
                copy.deepcopy(self.data_manager.data),
                revision,
            )
        except (CollectionRomOrganizationPlanError, OSError, ValueError) as error:
            self._log(f"ROM organization plan preview failed: {error}", "Error")
            messagebox.showerror(
                "ROM Organization Plan",
                f"The safe ROM move plan could not be frozen:\n\n{error}",
                parent=self.frame,
            )
            return

        if self.collection_rom_organization_audit_dialog is not None:
            self.collection_rom_organization_audit_dialog.close()

        self._last_collection_rom_save_disposition_review = None
        self._last_collection_rom_save_disposition_decision = None
        dialog = CollectionRomOrganizationPlanDialog(
            self.frame,
            plan,
            on_close=self._collection_rom_organization_plan_closed,
            on_review_save_impact=self._review_collection_rom_save_impact,
            on_preview_execution_plan=self._preview_collection_rom_organization_execution_plan,
        )
        self.collection_rom_organization_plan_dialog = dialog

    def _review_collection_rom_save_impact(self, plan, parent_dialog):
        """Review and explicitly disposition save evidence for an immutable ROM move plan."""
        if self.collection_rom_save_impact_dialog is not None:
            try:
                self.collection_rom_save_impact_dialog.dialog.lift()
                self.collection_rom_save_impact_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_save_impact_dialog = None

        try:
            from save_sync import clean_save_associations, clean_save_directories

            stored_directories = self.config_manager.get("save_sync_dirs", [])
            legacy_directory = self.config_manager.get("save_sync_dir", "")
            directories = clean_save_directories(
                stored_directories,
                legacy_directory=legacy_directory,
            )
            associations = clean_save_associations(
                self.config_manager.get("save_sync_associations", {})
            )
            review = build_collection_rom_save_impact_review(
                plan,
                configured_save_directories=directories,
                save_associations=associations,
            )
        except (CollectionRomSaveImpactError, OSError, ValueError) as error:
            self._log(f"ROM organization save-impact review failed: {error}", "Error")
            messagebox.showerror(
                "ROM Organization Save Dispositions",
                f"Save impact could not be reviewed safely:\n\n{error}",
                parent=parent_dialog,
            )
            return

        dialog = CollectionRomSaveImpactDialog(
            parent_dialog,
            review,
            on_save=self._collection_rom_save_dispositions_saved,
            on_close=self._collection_rom_save_impact_closed,
        )
        self.collection_rom_save_impact_dialog = dialog

    def _collection_rom_save_dispositions_saved(self, review, decision):
        """Retain detached save choices for the matching current or historical move plan."""
        normal_dialog = self.collection_rom_organization_plan_dialog
        historical_dialog = self.collection_rom_historical_organization_plan_dialog

        if normal_dialog is not None and review.plan == normal_dialog.plan:
            if self.collection_rom_organization_execution_plan_dialog is not None:
                self.collection_rom_organization_execution_plan_dialog.close()
                self.collection_rom_organization_execution_plan_dialog = None
            self._last_collection_rom_save_disposition_review = review
            self._last_collection_rom_save_disposition_decision = decision
            normal_dialog.set_save_disposition_decision(decision)
            return True

        if historical_dialog is not None and review.plan == historical_dialog.plan:
            if self.collection_rom_historical_organization_execution_plan_dialog is not None:
                self.collection_rom_historical_organization_execution_plan_dialog.close()
                self.collection_rom_historical_organization_execution_plan_dialog = None
            self._last_collection_historical_rom_save_disposition_review = review
            self._last_collection_historical_rom_save_disposition_decision = decision
            historical_dialog.set_save_disposition_decision(decision)
            return True

        messagebox.showerror(
            "ROM Organization Save Dispositions",
            "The ROM organization plan changed while save dispositions were open. "
            "Review save impact again.",
            parent=self.frame,
        )
        return False

    def _preview_collection_historical_rom_organization_execution_plan(
        self,
        plan,
        decision,
        parent_dialog,
    ):
        """Freeze the final historical ROM/save execution preview without applying it."""
        if self.collection_rom_historical_organization_execution_plan_dialog is not None:
            try:
                self.collection_rom_historical_organization_execution_plan_dialog.dialog.lift()
                self.collection_rom_historical_organization_execution_plan_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_historical_organization_execution_plan_dialog = None

        if (
            self.collection_rom_historical_organization_plan_dialog is None
            or self.collection_rom_historical_organization_plan_dialog.plan != plan
            or self._last_collection_historical_rom_save_disposition_decision != decision
        ):
            messagebox.showerror(
                "Final Historical ROM Organization Plan",
                "The reviewed historical ROM/save decisions no longer belong to the current move plan. "
                "Review save dispositions again.",
                parent=parent_dialog,
            )
            return

        try:
            from collection_plan_apply import collection_revision_token
            from save_sync import clean_save_associations, clean_save_directories

            stored_directories = self.config_manager.get("save_sync_dirs", [])
            legacy_directory = self.config_manager.get("save_sync_dir", "")
            directories = clean_save_directories(
                stored_directories,
                legacy_directory=legacy_directory,
            )
            associations = clean_save_associations(
                self.config_manager.get("save_sync_associations", {})
            )
            execution_plan = build_historical_rom_organization_execution_plan(
                plan,
                decision,
                current_collection_revision_token=collection_revision_token(self.data_manager),
                configured_save_directories=directories,
                save_associations=associations,
            )
        except (
            HistoricalRomOrganizationExecutionPlanError,
            OSError,
            ValueError,
        ) as error:
            self._log(f"Final historical ROM organization plan failed: {error}", "Error")
            messagebox.showerror(
                "Final Historical ROM Organization Plan",
                f"The reviewed historical ROM/save plan is stale or unsafe:\n\n{error}",
                parent=parent_dialog,
            )
            return

        self.collection_rom_historical_organization_execution_plan_dialog = (
            HistoricalRomOrganizationExecutionPlanDialog(
                parent_dialog,
                execution_plan,
                on_close=self._collection_rom_historical_organization_execution_plan_closed,
                on_apply=self._apply_collection_historical_rom_organization_execution_plan,
            )
        )


    def _apply_collection_historical_rom_organization_execution_plan(
        self, execution_plan, parent_dialog
    ):
        """Execute only the active finalized historical ROM/save organization plan."""
        dialog = self.collection_rom_historical_organization_execution_plan_dialog
        if dialog is None or dialog.plan != execution_plan:
            messagebox.showerror(
                "Apply Historical ROM Organization",
                "The final historical organization preview is no longer active. Run the audit again.",
                parent=parent_dialog,
            )
            return

        try:
            from download_state_manager import is_download_active
            if is_download_active():
                messagebox.showwarning(
                    "Download in Progress",
                    "ROM organization cannot run while a download/patch operation is active.",
                    parent=parent_dialog,
                )
                return
        except ImportError:
            pass

        from collection_rom_historical_organization_apply import (
            HistoricalRomOrganizationApplyError,
            apply_historical_rom_organization_execution_plan,
        )
        from collection_rom_organization_apply import (
            CollectionRomOrganizationApplyError,
            CollectionRomOrganizationRecoveryError,
            CollectionRomOrganizationRecoveryRequiredError,
            CollectionRomOrganizationStaleStateError,
        )

        try:
            parent_dialog.configure(cursor="wait")
            parent_dialog.update_idletasks()
            result = apply_historical_rom_organization_execution_plan(
                execution_plan, self.data_manager
            )
        except CollectionRomOrganizationRecoveryRequiredError as error:
            self._reload_collection_ingestion_live_state()
            self._close_collection_rom_organization_workflow()
            self._log(f"Historical ROM organization committed but cleanup requires recovery: {error}", "Error")
            messagebox.showerror(
                "ROM Organization Recovery Required",
                (
                    "The reviewed historical Collection path changes were committed, but cleanup of "
                    "the old source files did not finish. A recovery journal remains.\n\n"
                    f"{error}\n\nClose the application and resolve the prompted startup recovery before making further Collection changes."
                ),
                parent=self.frame.winfo_toplevel(),
            )
            return
        except (
            CollectionRomOrganizationStaleStateError,
            CollectionRomOrganizationRecoveryError,
            CollectionRomOrganizationApplyError,
            HistoricalRomOrganizationApplyError,
            OSError,
        ) as error:
            self._log(f"Historical ROM organization Apply failed: {error}", "Error")
            messagebox.showerror(
                "Historical ROM Organization Not Applied",
                (
                    "The finalized historical ROM/save plan could not be applied safely. "
                    "Any pre-commit filesystem changes were rolled back when possible.\n\n"
                    f"{error}\n\nRun the ROM layout audit again before retrying."
                ),
                parent=parent_dialog,
            )
            return
        finally:
            try:
                if parent_dialog.winfo_exists():
                    parent_dialog.configure(cursor="")
            except tk.TclError:
                pass

        self._reload_collection_ingestion_live_state()
        self._close_collection_rom_organization_workflow()
        self._log(
            f"Organized {result.rom_move_count} historical ROM(s) and {result.save_move_count} save(s)",
            "Information",
        )
        messagebox.showinfo(
            "Historical ROM Organization Complete",
            (
                f"Moved {result.rom_move_count} historical-provenance ROM(s) and "
                f"{result.save_move_count} reviewed save(s). Collection paths now reference the verified targets.\n\n"
                "Per-ROM historical SMWC provenance was preserved."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _preview_collection_rom_organization_execution_plan(
        self,
        plan,
        decision,
        parent_dialog,
    ):
        """Revalidate review evidence and show the final immutable execution preview."""
        if self.collection_rom_organization_execution_plan_dialog is not None:
            try:
                self.collection_rom_organization_execution_plan_dialog.dialog.lift()
                self.collection_rom_organization_execution_plan_dialog.dialog.focus_force()
                return
            except tk.TclError:
                self.collection_rom_organization_execution_plan_dialog = None

        if (
            self.collection_rom_organization_plan_dialog is None
            or self.collection_rom_organization_plan_dialog.plan != plan
            or self._last_collection_rom_save_disposition_decision != decision
        ):
            messagebox.showerror(
                "Final ROM Organization Plan",
                "The reviewed ROM/save decisions no longer belong to the current move plan. "
                "Review save dispositions again.",
                parent=parent_dialog,
            )
            return

        try:
            from collection_plan_apply import collection_revision_token
            from save_sync import clean_save_associations, clean_save_directories

            stored_directories = self.config_manager.get("save_sync_dirs", [])
            legacy_directory = self.config_manager.get("save_sync_dir", "")
            directories = clean_save_directories(
                stored_directories,
                legacy_directory=legacy_directory,
            )
            associations = clean_save_associations(
                self.config_manager.get("save_sync_associations", {})
            )
            execution_plan = build_collection_rom_organization_execution_plan(
                plan,
                decision,
                current_collection_revision_token=collection_revision_token(self.data_manager),
                configured_save_directories=directories,
                save_associations=associations,
            )
        except (
            CollectionRomOrganizationExecutionPlanError,
            OSError,
            ValueError,
        ) as error:
            self._log(f"Final ROM organization plan failed: {error}", "Error")
            messagebox.showerror(
                "Final ROM Organization Plan",
                f"The reviewed ROM/save plan is stale or unsafe:\n\n{error}",
                parent=parent_dialog,
            )
            return

        self.collection_rom_organization_execution_plan_dialog = (
            CollectionRomOrganizationExecutionPlanDialog(
                parent_dialog,
                execution_plan,
                on_close=self._collection_rom_organization_execution_plan_closed,
                on_apply=self._apply_collection_rom_organization_execution_plan,
            )
        )

    def _apply_collection_rom_organization_execution_plan(
        self,
        execution_plan,
        parent_dialog,
    ):
        """Execute only the already-finalized ROM/save organization plan."""
        dialog = self.collection_rom_organization_execution_plan_dialog
        if dialog is None or dialog.plan != execution_plan:
            messagebox.showerror(
                "Apply ROM Organization",
                "The final organization preview is no longer active. Run the audit again.",
                parent=parent_dialog,
            )
            return

        try:
            from download_state_manager import is_download_active

            if is_download_active():
                messagebox.showwarning(
                    "Download in Progress",
                    "ROM organization cannot run while a download/patch operation is active.",
                    parent=parent_dialog,
                )
                return
        except ImportError:
            pass

        from collection_rom_organization_apply import (
            CollectionRomOrganizationApplyError,
            CollectionRomOrganizationRecoveryError,
            CollectionRomOrganizationRecoveryRequiredError,
            CollectionRomOrganizationStaleStateError,
            apply_collection_rom_organization_execution_plan,
        )

        try:
            parent_dialog.configure(cursor="wait")
            parent_dialog.update_idletasks()
            result = apply_collection_rom_organization_execution_plan(
                execution_plan,
                self.data_manager,
            )
        except CollectionRomOrganizationRecoveryRequiredError as error:
            self._reload_collection_ingestion_live_state()
            self._close_collection_rom_organization_workflow()
            self._log(f"ROM organization committed but cleanup requires recovery: {error}", "Error")
            messagebox.showerror(
                "ROM Organization Recovery Required",
                (
                    "The reviewed Collection path changes were committed, but cleanup of "
                    "the old source files did not finish. A recovery journal remains.\n\n"
                    f"{error}\n\nClose the application and resolve the prompted startup "
                    "recovery before making further Collection changes."
                ),
                parent=self.frame.winfo_toplevel(),
            )
            return
        except (
            CollectionRomOrganizationStaleStateError,
            CollectionRomOrganizationRecoveryError,
            CollectionRomOrganizationApplyError,
            OSError,
        ) as error:
            self._log(f"ROM organization Apply failed: {error}", "Error")
            messagebox.showerror(
                "ROM Organization Not Applied",
                (
                    "The finalized ROM/save organization plan could not be applied safely. "
                    "Any pre-commit filesystem changes were rolled back when possible.\n\n"
                    f"{error}\n\nRun the ROM layout audit again before retrying."
                ),
                parent=parent_dialog,
            )
            return
        finally:
            try:
                if parent_dialog.winfo_exists():
                    parent_dialog.configure(cursor="")
            except tk.TclError:
                pass

        self._reload_collection_ingestion_live_state()
        self._close_collection_rom_organization_workflow()
        self._log(
            f"Organized {result.rom_move_count} ROM(s) and {result.save_move_count} save(s)",
            "Information",
        )
        messagebox.showinfo(
            "ROM Organization Complete",
            (
                f"Moved {result.rom_move_count} ROM(s) and {result.save_move_count} "
                "reviewed save(s). Collection paths now reference the verified targets.\n\n"
                "Saves explicitly left in place were not changed."
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _close_collection_rom_organization_workflow(self):
        """Close all detached organizer dialogs/review state after Apply or recovery."""
        for attr in (
            "collection_rom_organization_execution_plan_dialog",
            "collection_rom_historical_organization_execution_plan_dialog",
            "collection_rom_save_impact_dialog",
            "collection_rom_organization_plan_dialog",
            "collection_rom_organization_audit_dialog",
            "collection_rom_modern_provenance_dialog",
            "collection_rom_legacy_metadata_dialog",
            "collection_rom_legacy_metadata_plan_dialog",
            "collection_rom_legacy_provenance_dialog",
            "collection_rom_legacy_provenance_plan_dialog",
            "collection_rom_historical_provenance_dialog",
            "collection_rom_historical_organization_plan_dialog",
            "collection_rom_historical_provenance_progress_dialog",
        ):
            dialog = getattr(self, attr, None)
            setattr(self, attr, None)
            if dialog is not None:
                try:
                    dialog.close()
                except tk.TclError:
                    pass
        self._last_collection_rom_save_disposition_review = None
        self._last_collection_rom_save_disposition_decision = None
        self._last_collection_historical_rom_save_disposition_review = None
        self._last_collection_historical_rom_save_disposition_decision = None
        self._last_collection_modern_provenance_review = None
        self._last_collection_modern_provenance_decision = None

    def _collection_rom_organization_execution_plan_closed(self):
        self.collection_rom_organization_execution_plan_dialog = None

    def _collection_rom_historical_organization_execution_plan_closed(self):
        self.collection_rom_historical_organization_execution_plan_dialog = None

    def _collection_rom_save_impact_closed(self):
        self.collection_rom_save_impact_dialog = None

    def _collection_rom_organization_plan_closed(self):
        if self.collection_rom_organization_execution_plan_dialog is not None:
            self.collection_rom_organization_execution_plan_dialog.close()
            self.collection_rom_organization_execution_plan_dialog = None
        if self.collection_rom_save_impact_dialog is not None:
            self.collection_rom_save_impact_dialog.close()
            self.collection_rom_save_impact_dialog = None
        self._last_collection_rom_save_disposition_review = None
        self._last_collection_rom_save_disposition_decision = None
        self.collection_rom_organization_plan_dialog = None

    def _collection_rom_modern_provenance_closed(self):
        self.collection_rom_modern_provenance_dialog = None
        self._last_collection_modern_provenance_review = None
        self._last_collection_modern_provenance_decision = None

    def _collection_rom_organization_audit_closed(self):
        self.collection_rom_organization_audit_dialog = None

    def _collection_rom_legacy_metadata_closed(self):
        self.collection_rom_legacy_metadata_dialog = None

    def _collection_rom_legacy_metadata_plan_closed(self):
        self.collection_rom_legacy_metadata_plan_dialog = None

    def _collection_rom_legacy_provenance_closed(self):
        if self.collection_rom_legacy_provenance_plan_dialog is not None:
            self.collection_rom_legacy_provenance_plan_dialog.close()
            self.collection_rom_legacy_provenance_plan_dialog = None
        self.collection_rom_legacy_provenance_dialog = None
        self._last_collection_legacy_provenance_review = None
        self._last_collection_legacy_provenance_decision = None

    def _collection_rom_legacy_provenance_plan_closed(self):
        self.collection_rom_legacy_provenance_plan_dialog = None

    def _collection_rom_historical_provenance_closed(self):
        self.collection_rom_historical_provenance_dialog = None

    def _collection_rom_historical_organization_plan_closed(self):
        if self.collection_rom_historical_organization_execution_plan_dialog is not None:
            self.collection_rom_historical_organization_execution_plan_dialog.close()
            self.collection_rom_historical_organization_execution_plan_dialog = None
        historical_dialog = self.collection_rom_historical_organization_plan_dialog
        save_dialog = self.collection_rom_save_impact_dialog
        if (
            historical_dialog is not None
            and save_dialog is not None
            and save_dialog.review.plan == historical_dialog.plan
        ):
            save_dialog.close()
            self.collection_rom_save_impact_dialog = None
        self._last_collection_historical_rom_save_disposition_review = None
        self._last_collection_historical_rom_save_disposition_decision = None
        self.collection_rom_historical_organization_plan_dialog = None

    def _create_pagination_controls(self):
        """Create pagination controls"""
        pagination_frame = ttk.Frame(self.frame)
        pagination_frame.pack(fill="x", pady=(0, 10))

        # Left side - Page size selector
        left_frame = ttk.Frame(pagination_frame)
        left_frame.pack(side="left")



        ttk.Label(left_frame, text="Show:").pack(side="left", padx=(0, 5))

        self.page_size_var = tk.StringVar(value="50")
        page_size_combo = ttk.Combobox(left_frame, textvariable=self.page_size_var,
                                      values=["25", "50", "100", "200"], width=8, state="readonly")
        page_size_combo.pack(side="left", padx=(0, 5))
        page_size_combo.bind("<<ComboboxSelected>>", self._on_page_size_change)

        ttk.Label(left_frame, text="").pack(side="left")

        self.collection_import_button = ttk.Button(
            left_frame,
            text="Import...",
            command=self._open_collection_import,
        )
        self.collection_import_button.pack(side="left", padx=(0, 8))

        self.collection_update_button = ttk.Button(
            left_frame,
            text="Find Update...",
            command=self._open_collection_update_discovery,
        )
        self.collection_update_button.pack(side="left", padx=(0, 8))

        self.collection_rom_audit_button = ttk.Button(
            left_frame,
            text="Audit ROM Layout...",
            command=self._open_collection_rom_organization_audit,
        )
        self.collection_rom_audit_button.pack(side="left", padx=(0, 10))

        # Add Columns button
        ttk.Button(left_frame, text="⚙ Columns", command=self._show_column_config).pack(side="left", padx=(0, 15))

        # Center - Page info
        center_frame = ttk.Frame(pagination_frame)
        center_frame.pack(side="left", expand=True)

        self.page_info_label = ttk.Label(center_frame, text="Page 1 of 1")
        self.page_info_label.pack()

        # Right side - Navigation buttons
        right_frame = ttk.Frame(pagination_frame)
        right_frame.pack(side="right")

        self.first_btn = ttk.Button(right_frame, text="⏮", width=3, command=self._go_to_first_page)
        self.first_btn.pack(side="left", padx=(0, 2))

        self.prev_btn = ttk.Button(right_frame, text="◀", width=3, command=self._go_to_prev_page)
        self.prev_btn.pack(side="left", padx=(0, 2))

        # Page input
        self.page_var = tk.StringVar(value="1")
        self.page_entry = ttk.Entry(right_frame, textvariable=self.page_var, width=5, justify="center")
        self.page_entry.pack(side="left", padx=(0, 2))
        self.page_entry.bind("<Return>", self._on_page_entry_change)
        self.page_entry.bind("<FocusOut>", self._on_page_entry_change)

        self.next_btn = ttk.Button(right_frame, text="▶", width=3, command=self._go_to_next_page)
        self.next_btn.pack(side="left", padx=(0, 2))

        self.last_btn = ttk.Button(right_frame, text="⏭", width=3, command=self._go_to_last_page)
        self.last_btn.pack(side="left")

    def _on_page_size_change(self, event=None):
        """Handle page size change"""
        try:
            new_size = int(self.page_size_var.get())
            if new_size != self.page_size:
                self.page_size = new_size
                self.current_page = 1  # Reset to first page
                self._refresh_table()
        except ValueError:
            pass

    def _on_page_entry_change(self, event=None):
        """Handle manual page entry"""
        try:
            new_page = int(self.page_var.get())
            if 1 <= new_page <= self.total_pages and new_page != self.current_page:
                self.current_page = new_page
                self._refresh_table()
            else:
                # Reset to current page if invalid
                self.page_var.set(str(self.current_page))
        except ValueError:
            self.page_var.set(str(self.current_page))

    def _go_to_first_page(self):
        """Go to first page"""
        if self.current_page != 1:
            self.current_page = 1
            self.page_var.set("1")
            self._refresh_table()

    def _go_to_prev_page(self):
        """Go to previous page"""
        if self.current_page > 1:
            self.current_page -= 1
            self.page_var.set(str(self.current_page))
            self._refresh_table()

    def _go_to_next_page(self):
        """Go to next page"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.page_var.set(str(self.current_page))
            self._refresh_table()

    def _go_to_last_page(self):
        """Go to last page"""
        if self.current_page != self.total_pages:
            self.current_page = self.total_pages
            self.page_var.set(str(self.total_pages))
            self._refresh_table()

    def _update_pagination_controls(self):
        """Update pagination control states"""
        # Update page info
        self.page_info_label.configure(text=f"Page {self.current_page} of {self.total_pages}")

        # Update button states
        first_page = self.current_page == 1
        last_page = self.current_page == self.total_pages

        self.first_btn.configure(state="disabled" if first_page else "normal")
        self.prev_btn.configure(state="disabled" if first_page else "normal")
        self.next_btn.configure(state="disabled" if last_page else "normal")
        self.last_btn.configure(state="disabled" if last_page else "normal")

    def _sort_by_column(self, column):
        """Sort the data by the specified column"""
        # Toggle sort direction if clicking the same column
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False

        # Update header to show sort direction
        self._update_column_headers()

        # Apply sort and refresh table
        self._refresh_table()

    def _update_column_headers(self):
        """Update column headers to show sort indicators.

        Previously used hardcoded column/header tuples which only covered 9 of the
        11 columns and did not respect user-defined column ordering.  Now we derive
        the header text from DEFAULT_COLUMNS (the authoritative header definitions)
        and iterate over every column in the treeview so all columns get the correct
        sort indicator and command regardless of the current display configuration.
        """
        # Build a stable header-text lookup from the original column definitions.
        header_map = {col["id"]: col["header"] for col in self.DEFAULT_COLUMNS}

        for col_id in self.tree["columns"]:
            base_header = header_map.get(col_id, col_id)
            if col_id == self.sort_column:
                indicator = " ▼" if self.sort_reverse else " ▲"
                header_text = base_header + indicator
            else:
                header_text = base_header

            self.tree.heading(col_id, text=header_text, command=lambda c=col_id: self._sort_by_column(c))

    def _sort_filtered_data(self):
        """Sort the filtered data based on current sort settings"""
        if not self.sort_column or not self.filtered_data:
            return

        def get_sort_key(hack):
            value = hack.get(self.sort_column, "")

            # Handle different data types for proper sorting
            if self.sort_column == "completed":
                # Sort completed status: completed items first, then uncompleted
                return (not hack.get("completed", False), hack.get("title", "").lower())
            elif self.sort_column == "rating":
                # Sort the user-assigned Personal Rating numerically.
                rating = hack.get("personal_rating", 0)
                try:
                    return float(rating) if rating else 0
                except (ValueError, TypeError):
                    return 0
            elif self.sort_column == "smwc_rating":
                return smwc_rating_sort_value(hack.get("rating", 0))
            elif self.sort_column == "completed_date":
                # Date sorting - handle empty dates
                if not value:
                    return "0000-00-00"  # Empty dates sort first
                return value
            elif self.sort_column == "time_to_beat":
                # Time sorting - convert to numeric for proper ordering
                if not value:
                    return 0
                try:
                    # If it's already numeric (seconds), use it
                    if isinstance(value, (int, float)):
                        return value
                    # If it's a string, try to parse it
                    return float(value)
                except (ValueError, TypeError):
                    return 0
            elif self.sort_column == "release_date":
                # Release date sorting - use numeric timestamp for proper chronological ordering
                timestamp = hack.get("time", 0)
                try:
                    return int(timestamp) if timestamp else 0
                except (ValueError, TypeError):
                    return 0
            else:
                # String sorting (case-insensitive)
                return str(value).lower()

        self.filtered_data.sort(key=get_sort_key, reverse=self.sort_reverse)
