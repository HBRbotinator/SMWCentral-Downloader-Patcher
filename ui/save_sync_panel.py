"""Persistent Save Data Sync controls and review-only scan scheduling."""
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from ui_constants import (
    STATUS_COLOR_INFO, STATUS_COLOR_SUCCESS, STATUS_COLOR_WARNING, STATUS_COLOR_ERROR,
)


class SaveSyncPanel:
    """One shared Collection manager and scan lifecycle, independent of navigation."""

    def __init__(self, parent, setup_section, data_manager, logger=None, on_applied=None):
        self.parent = parent
        self.setup_section = setup_section
        self.data_manager = data_manager
        self.logger = logger
        self.reload_collection_callback = on_applied
        self.frame = None
        # Opt-in startup scan state. Automatic scans only prepare a review;
        # they never write collection data without the existing dialog.
        self._auto_scan_started = False
        self._scan_running = False
        self._pending_auto_scan_candidates = []
        self._pending_auto_scan_lookup_service = None
        self._periodic_scan_job = None

        self._startup_jobs = []
        self._closed = False
        self._review_dialog = None

    def create(self):
        if self.frame is not None:
            return self.frame
        # Created once for the lifetime of the application, including while hidden.
        save_sync_frame = ttk.LabelFrame(self.parent, text="Save Data Sync", padding=(15, 10, 15, 15))
        self.frame = save_sync_frame
        self.frame.bind("<Destroy>", self._on_destroy, add="+")

        ttk.Label(
            save_sync_frame,
            text="Review progress from emulator or console saves (.srm / .sav). "
                 "Completion dates use the save file's last-modified time. "
                 "Save files do not provide play time.",
            style="Custom.TLabel",
            wraplength=680
        ).pack(anchor="w", pady=(0, 10))

        # Persisted save source folders
        ttk.Label(
            save_sync_frame,
            text="Save Folders:",
            style="Custom.TLabel",
        ).pack(anchor="w", pady=(0, 4))

        save_dirs_frame = ttk.Frame(save_sync_frame)
        save_dirs_frame.pack(fill="x", pady=(0, 8))

        save_dirs_list_frame = ttk.Frame(save_dirs_frame)
        save_dirs_list_frame.pack(side="left", fill="both", expand=True)

        self.save_sync_dirs_listbox = tk.Listbox(
            save_dirs_list_frame,
            height=4,
            exportselection=False,
        )
        save_dirs_scrollbar = ttk.Scrollbar(
            save_dirs_list_frame,
            orient="vertical",
            command=self.save_sync_dirs_listbox.yview,
        )
        self.save_sync_dirs_listbox.configure(
            yscrollcommand=save_dirs_scrollbar.set
        )
        self.save_sync_dirs_listbox.pack(side="left", fill="both", expand=True)
        save_dirs_scrollbar.pack(side="right", fill="y")
        self.save_sync_dirs_listbox.bind(
            "<<ListboxSelect>>", self._on_save_sync_folder_selected
        )

        save_dirs_buttons = ttk.Frame(save_dirs_frame)
        save_dirs_buttons.pack(side="left", padx=(10, 0), anchor="n")

        ttk.Button(
            save_dirs_buttons,
            text="Add Folder...",
            command=self._add_save_dir,
            style="Custom.TButton",
        ).pack(fill="x", pady=(0, 5))

        ttk.Button(
            save_dirs_buttons,
            text="Remove Selected",
            command=self._remove_save_dir,
            style="Custom.TButton",
        ).pack(fill="x", pady=(0, 8))

        self.save_sync_recursive_var = tk.BooleanVar(value=False)
        self.save_sync_recursive_checkbox = ttk.Checkbutton(
            save_dirs_buttons,
            text="Include subfolders",
            variable=self.save_sync_recursive_var,
            style="Custom.TCheckbutton",
            command=self._toggle_save_sync_recursive,
            state="disabled",
        )
        self.save_sync_recursive_checkbox.pack(fill="x")

        ttk.Label(
            save_sync_frame,
            text=(
                "Select a folder to change whether its subfolders are included. "
                "Removing a folder from this list leaves its files in place."
            ),
            style="Custom.TLabel",
            foreground="gray",
            wraplength=680,
        ).pack(anchor="w", pady=(0, 8))

        # Mark-all toggle
        self.save_sync_mark_all_var = tk.BooleanVar()
        ttk.Checkbutton(
            save_sync_frame,
            text="Mark ALL matched saves as completed "
                 "(off: only when collected exits ≥ the hack's exit count)",
            variable=self.save_sync_mark_all_var,
            style="Custom.TCheckbutton",
            command=self._save_save_sync_settings
        ).pack(anchor="w", pady=(0, 8))

        self.save_sync_auto_scan_var = tk.BooleanVar()
        ttk.Checkbutton(
            save_sync_frame,
            text="Check save folders automatically on startup "
                 "(review required; nothing is applied automatically)",
            variable=self.save_sync_auto_scan_var,
            style="Custom.TCheckbutton",
            command=self._save_save_sync_settings,
        ).pack(anchor="w", pady=(0, 5))

        periodic_row = ttk.Frame(save_sync_frame)
        periodic_row.pack(fill="x", pady=(0, 8))
        self.save_sync_periodic_scan_var = tk.BooleanVar()
        ttk.Checkbutton(
            periodic_row,
            text="Continue checking while the application is open "
                 "(review required)",
            variable=self.save_sync_periodic_scan_var,
            style="Custom.TCheckbutton",
            command=self._save_periodic_scan_settings,
        ).pack(side="left")

        ttk.Label(
            periodic_row,
            text="Every:",
            style="Custom.TLabel",
        ).pack(side="left", padx=(16, 5))
        self.save_sync_scan_interval_var = tk.StringVar()
        self.save_sync_scan_interval_combo = ttk.Combobox(
            periodic_row,
            textvariable=self.save_sync_scan_interval_var,
            values=("5", "15", "30", "60"),
            state="readonly",
            width=5,
        )
        self.save_sync_scan_interval_combo.pack(side="left")
        self.save_sync_scan_interval_combo.bind(
            "<<ComboboxSelected>>",
            self._save_periodic_scan_settings,
        )
        ttk.Label(
            periodic_row,
            text="minutes",
            style="Custom.TLabel",
        ).pack(side="left", padx=(5, 0))

        # Scan button + status
        scan_row = ttk.Frame(save_sync_frame)
        scan_row.pack(fill="x")

        self.scan_saves_button = ttk.Button(
            scan_row,
            text="Scan Saves",
            command=self._scan_saves,
            style="Accent.TButton"
        )
        self.scan_saves_button.pack(side="left")

        self.review_auto_scan_button = ttk.Button(
            scan_row,
            text="Review Auto-Scan...",
            command=self._review_auto_scan,
            style="Custom.TButton",
            state="disabled",
        )
        self.review_auto_scan_button.pack(side="left", padx=(8, 0))

        self.save_sync_status_label = ttk.Label(
            scan_row,
            text="",
            style="Custom.TLabel"
        )
        self.save_sync_status_label.pack(side="left", padx=(12, 0))

        # Load persisted save-sync settings
        self._load_save_sync_settings()
        self._update_periodic_scan_controls()
        self._startup_jobs.append(self.frame.after(2000, self.start_save_sync_auto_scan))
        self._startup_jobs.append(self.frame.after(2500, self.start_save_sync_periodic_scan))

        return self.frame

    # ------------------------------------------------------------------ #
    # Save Data Sync
    # ------------------------------------------------------------------ #

    def _save_sync_directories_from_widget(self):
        """Return the configured source paths behind the annotated list."""

        return list(getattr(self, "_save_sync_directory_paths", []))

    def _selected_save_sync_directory(self):
        selected = self.save_sync_dirs_listbox.curselection()
        paths = self._save_sync_directories_from_widget()
        if len(selected) != 1 or selected[0] >= len(paths):
            return ""
        return paths[selected[0]]

    def _populate_save_sync_directories(self, directories, select_index=None):
        """Replace the source list and show which folders include subfolders."""

        import save_sync_sources

        self._save_sync_directory_paths = list(directories)
        recursive_ids = {
            os.path.normcase(os.path.realpath(directory))
            for directory in save_sync_sources.get_recursive_save_directories(
                self.setup_section.config, directories
            )
        }
        self.save_sync_dirs_listbox.delete(0, tk.END)
        for directory in self._save_sync_directory_paths:
            marker = (
                "[Subfolders] "
                if os.path.normcase(os.path.realpath(directory)) in recursive_ids
                else ""
            )
            self.save_sync_dirs_listbox.insert(tk.END, marker + directory)
        if (
            select_index is not None
            and 0 <= select_index < len(self._save_sync_directory_paths)
        ):
            self.save_sync_dirs_listbox.selection_set(select_index)
            self.save_sync_dirs_listbox.activate(select_index)
        self._on_save_sync_folder_selected()

    def _on_save_sync_folder_selected(self, _event=None):
        """Reflect the selected folder's recursive-scan setting."""

        import save_sync_sources

        directory = self._selected_save_sync_directory()
        if not directory:
            self.save_sync_recursive_var.set(False)
            self.save_sync_recursive_checkbox.config(state="disabled")
            return
        self.save_sync_recursive_var.set(
            save_sync_sources.is_save_directory_recursive(
                self.setup_section.config, directory
            )
        )
        self.save_sync_recursive_checkbox.config(state="normal")

    def _toggle_save_sync_recursive(self):
        """Enable or disable recursive discovery for the selected source only."""

        try:
            import save_sync_sources

            selected = self.save_sync_dirs_listbox.curselection()
            directory = self._selected_save_sync_directory()
            if not directory or len(selected) != 1:
                return
            save_sync_sources.set_save_directory_recursive(
                self.setup_section.config,
                directory,
                self.save_sync_recursive_var.get(),
            )
            self._populate_save_sync_directories(
                self._save_sync_directories_from_widget(),
                select_index=selected[0],
            )
        except Exception as e:
            messagebox.showerror(
                "Save Data Sync",
                f"Failed to update folder scan options: {e}",
            )

    def _load_save_sync_settings(self):
        """Load save-sync settings from config into the widgets."""

        try:
            import save_sync

            config = self.setup_section.config
            directories = save_sync.get_save_directories(config)
            self._populate_save_sync_directories(directories)
            self.save_sync_mark_all_var.set(
                config.get("save_sync_mark_all", False)
            )
            self.save_sync_auto_scan_var.set(
                config.get("save_sync_auto_scan", False)
            )
            self.save_sync_periodic_scan_var.set(
                config.get("save_sync_periodic_scan", False)
            )
            self.save_sync_scan_interval_var.set(
                str(
                    save_sync.normalize_auto_scan_interval(
                        config.get(
                            "save_sync_scan_interval_minutes", 15
                        )
                    )
                )
            )
        except Exception as e:
            print(f"Error loading save sync settings: {e}")

    def _save_save_sync_settings(self, event=None):
        """Persist save-sync settings to config."""

        try:
            import save_sync

            config = self.setup_section.config
            save_sync.set_save_directories(
                config,
                self._save_sync_directories_from_widget(),
            )
            config.set("save_sync_mark_all", self.save_sync_mark_all_var.get())
            config.set(
                "save_sync_auto_scan",
                self.save_sync_auto_scan_var.get(),
            )
            config.set(
                "save_sync_periodic_scan",
                self.save_sync_periodic_scan_var.get(),
            )
            config.set(
                "save_sync_scan_interval_minutes",
                save_sync.normalize_auto_scan_interval(
                    self.save_sync_scan_interval_var.get()
                ),
            )
        except Exception as e:
            print(f"Error saving save sync settings: {e}")

    def _update_periodic_scan_controls(self):
        """Enable interval selection only while periodic review scans are on."""

        state = (
            "readonly"
            if self.save_sync_periodic_scan_var.get()
            else "disabled"
        )
        self.save_sync_scan_interval_combo.config(state=state)

    def _save_periodic_scan_settings(self, event=None):
        """Persist and reschedule the review-only periodic scan."""

        self._update_periodic_scan_controls()
        self._save_save_sync_settings()
        self._restart_periodic_save_sync_scan()

    def _add_save_dir(self):
        """Add another emulator or console save source folder."""

        try:
            import save_sync
            from platform_utils import pick_directory

            directories = self._save_sync_directories_from_widget()
            current = self._selected_save_sync_directory()
            if not current:
                current = directories[0] if directories else ""

            selected = pick_directory(
                title="Add Save Folder",
                initial_dir=(
                    current if current and os.path.isdir(current) else None
                ),
            )
            if not selected:
                return

            # Re-adding an existing source selects it without resetting its options.
            selected_id = os.path.normcase(os.path.realpath(selected))
            for index, directory in enumerate(directories):
                if os.path.normcase(os.path.realpath(directory)) == selected_id:
                    self._populate_save_sync_directories(directories, select_index=index)
                    return

            from ui.save_sync_folder_dialog import ask_include_save_subfolders
            import save_sync_sources

            include_subfolders = ask_include_save_subfolders(
                self.frame.winfo_toplevel(), selected
            )
            if include_subfolders is None:
                return
            save_sync.add_save_directory(self.setup_section.config, selected)
            save_sync_sources.set_save_directory_recursive(
                self.setup_section.config, selected, include_subfolders
            )
            updated = save_sync.get_save_directories(self.setup_section.config)
            index = next(
                i for i, directory in enumerate(updated)
                if os.path.normcase(os.path.realpath(directory)) == selected_id
            )
            self._populate_save_sync_directories(updated, select_index=index)
        except Exception as e:
            messagebox.showerror(
                "Save Data Sync",
                f"Failed to add save folder: {e}",
            )

    def _remove_save_dir(self):
        """Remove the selected source without touching files on disk."""

        selected_indices = self.save_sync_dirs_listbox.curselection()
        if not selected_indices:
            messagebox.showinfo(
                "Save Data Sync",
                "Select a save folder to remove first.",
            )
            return

        try:
            import save_sync
            import save_sync_sources

            directory = self._selected_save_sync_directory()
            if not directory:
                return
            save_sync.remove_save_directory(
                self.setup_section.config,
                directory,
            )
            save_sync_sources.remove_source_state(
                self.setup_section.config, directory
            )
            self._populate_save_sync_directories(
                save_sync.get_save_directories(self.setup_section.config)
            )
        except Exception as e:
            messagebox.showerror(
                "Save Data Sync",
                f"Failed to remove save folder: {e}",
            )

    def _available_save_directories(self, interactive):
        """Return available configured sources for manual or startup scans."""

        import save_sync

        directories = save_sync.get_save_directories(
            self.setup_section.config
        )
        if not directories:
            if interactive:
                messagebox.showerror(
                    "Save Data Sync",
                    "Add at least one save folder first.",
                )
            else:
                self.save_sync_status_label.config(
                    text="Auto-scan skipped: no save folders",
                    foreground=STATUS_COLOR_WARNING,
                )
            return []

        available = [
            directory for directory in directories if os.path.isdir(directory)
        ]
        unavailable = [
            directory for directory in directories
            if not os.path.isdir(directory)
        ]
        if not available:
            if interactive:
                messagebox.showerror(
                    "Save Data Sync",
                    "None of the configured save folders are currently "
                    "available.",
                )
            else:
                self.save_sync_status_label.config(
                    text="Auto-scan skipped: folders unavailable",
                    foreground=STATUS_COLOR_WARNING,
                )
                if self.logger:
                    self.logger.log(
                        "Save Data Sync automatic scan skipped because no "
                        "configured folder was available.",
                        "Information",
                    )
            return []

        if unavailable and interactive:
            missing_names = "\n".join(
                f"• {directory}" for directory in unavailable
            )
            proceed = messagebox.askyesno(
                "Unavailable Save Folders",
                "These configured folders are unavailable and will be "
                "skipped:\n\n"
                f"{missing_names}\n\n"
                f"Continue with the {len(available)} available folder(s)?",
            )
            if not proceed:
                return []
        elif unavailable and self.logger:
            self.logger.log(
                "Save Data Sync automatic scan skipped "
                f"{len(unavailable)} unavailable configured folder(s).",
                "Information",
            )

        return available

    def start_save_sync_periodic_scan(self):
        """Schedule opt-in review scans throughout the application session."""

        self._restart_periodic_save_sync_scan()

    def _restart_periodic_save_sync_scan(self):
        """Cancel the old timer and schedule the current configured interval."""

        if self._periodic_scan_job is not None:
            try:
                self.frame.after_cancel(self._periodic_scan_job)
            except (AttributeError, tk.TclError):
                pass
            self._periodic_scan_job = None

        if self._closed or not self.save_sync_periodic_scan_var.get():
            return

        import save_sync

        minutes = save_sync.normalize_auto_scan_interval(
            self.save_sync_scan_interval_var.get()
        )
        self._periodic_scan_job = self.frame.after(
            minutes * 60 * 1000,
            self._run_periodic_save_sync_scan,
        )

    def _run_periodic_save_sync_scan(self):
        """Run a noninteractive scan unless work or review is already pending."""

        self._periodic_scan_job = None
        if self._closed or not self.save_sync_periodic_scan_var.get():
            return

        if not self._scan_running and not self._pending_auto_scan_candidates:
            self._scan_saves(auto=True)

        self._restart_periodic_save_sync_scan()

    def start_save_sync_auto_scan(self):
        """Run one opt-in startup scan without opening or applying a dialog."""

        if self._closed or self._auto_scan_started:
            return
        self._auto_scan_started = True
        if not self.save_sync_auto_scan_var.get():
            return
        self._scan_saves(auto=True)

    def _scan_saves(self, auto=False):
        """Scan configured sources manually or prepare an opt-in review."""

        import save_sync

        if self._closed or self._scan_running or self._review_is_open():
            return
        if not auto:
            self._pending_auto_scan_candidates = []
            self._pending_auto_scan_lookup_service = None

        available = self._available_save_directories(interactive=not auto)
        if not available:
            return

        data_manager = getattr(self, "data_manager", None)
        if data_manager is None:
            if auto:
                self.save_sync_status_label.config(
                    text="Auto-scan skipped: collection unavailable",
                    foreground=STATUS_COLOR_WARNING,
                )
            else:
                messagebox.showerror(
                    "Save Data Sync",
                    "Collection data is not available yet. Open the Collection "
                    "tab once, then try again.",
                )
            return

        self._save_save_sync_settings()
        mark_all = self.save_sync_mark_all_var.get()
        self._scan_running = True
        self.scan_saves_button.config(state="disabled", text="Scanning...")
        self.review_auto_scan_button.config(state="disabled")
        prefix = "Auto-scanning" if auto else "Scanning"
        self.save_sync_status_label.config(
            text=f"⏳ {prefix} {len(available)} folder(s)...",
            foreground=STATUS_COLOR_INFO,
        )
        self.frame.update_idletasks()

        def worker():
            error = None
            candidates = []
            lookup_service = None
            try:
                hacks = data_manager.get_all_hacks(include_obsolete=False)
                existing_ids = {str(hack.get("id", "")) for hack in hacks}
                associations, removed = save_sync.prune_save_associations(
                    self.setup_section.config.get(
                        save_sync.ASSOCIATION_CONFIG_KEY, {}
                    ),
                    existing_ids,
                )
                if removed:
                    self.setup_section.config.set(
                        save_sync.ASSOCIATION_CONFIG_KEY,
                        associations,
                    )

                import save_sync_sources

                path_associations, path_removed = (
                    save_sync_sources.prune_path_associations(
                        self.setup_section.config.get(
                            save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY, {}
                        ),
                        existing_ids,
                    )
                )
                if path_removed:
                    self.setup_section.config.set(
                        save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY,
                        path_associations,
                    )

                candidates = save_sync_sources.scan_save_directories(
                    self.setup_section.config,
                    available,
                    hacks,
                    mark_all=mark_all,
                    associations=associations,
                )

                unmatched = [candidate for candidate in candidates if not candidate.hack_id]
                if unmatched:
                    try:
                        from save_sync_catalogue import SaveSyncCatalogueLookup

                        lookup_service = SaveSyncCatalogueLookup(
                            processed_json_path=getattr(data_manager, "json_path", None),
                            log=self.logger.log if self.logger else None,
                        )
                        resolutions = lookup_service.resolve_automatic_many(
                            [candidate.save_name for candidate in unmatched],
                            existing_ids,
                        )
                        for candidate, resolution in zip(unmatched, resolutions):
                            save_sync.attach_resolution(
                                candidate, resolution, data_manager, mark_all
                            )
                    except Exception as lookup_error:
                        if self.logger:
                            self.logger.log(
                                f"Save Data Sync initial catalogue lookup failed: {lookup_error}",
                                "Warning",
                            )
            except Exception as exc:
                error = exc

            if not self._closed:
                try:
                    self.frame.after(
                        0,
                        lambda: self._on_scan_complete(
                            candidates, error, auto=auto, lookup_service=lookup_service
                        ),
                    )
                except (tk.TclError, RuntimeError):
                    # The application may have closed during the worker scan.
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_complete(self, candidates, error, auto=False, lookup_service=None):
        """Handle manual results or retain startup results for later review."""

        import save_sync

        self._scan_running = False
        if self._closed:
            return
        self.scan_saves_button.config(state="normal", text="Scan Saves")

        if error is not None:
            label = "Auto-scan failed" if auto else "Scan failed"
            self.save_sync_status_label.config(
                text=f"❌ {label}",
                foreground=STATUS_COLOR_ERROR,
            )
            if not auto:
                messagebox.showerror(
                    "Save Data Sync",
                    f"Failed to scan saves:\n{error}",
                )
            if self.logger:
                self.logger.log(
                    f"Save data scan failed: {error}",
                    "Error",
                )
            return

        if auto:
            collection = getattr(self.data_manager, "data", {})
            review_candidates = save_sync.auto_review_candidates(
                candidates,
                collection=collection,
            )
            self._pending_auto_scan_candidates = review_candidates
            self._pending_auto_scan_lookup_service = lookup_service
            if not review_candidates:
                self._pending_auto_scan_lookup_service = None
                self.review_auto_scan_button.config(state="disabled")
                self.save_sync_status_label.config(
                    text="Auto-scan: no changes to review",
                    foreground=STATUS_COLOR_SUCCESS,
                )
                return

            completions = sum(
                candidate.status == save_sync.STATUS_COMPLETED
                for candidate in review_candidates
            )
            imports_or_review = sum(
                not candidate.hack_id for candidate in review_candidates
            )
            self.review_auto_scan_button.config(state="normal")
            self.save_sync_status_label.config(
                text=(
                    f"Auto-scan ready: {completions} completion(s) · "
                    f"{imports_or_review} import/review"
                ),
                foreground=STATUS_COLOR_SUCCESS,
            )
            return

        if not candidates:
            self.save_sync_status_label.config(
                text="No .srm/.sav files found",
                foreground=STATUS_COLOR_WARNING,
            )
            messagebox.showinfo(
                "Save Data Sync",
                "No .srm or .sav files were found in the configured folders.",
            )
            return

        matched = [
            candidate for candidate in candidates if candidate.hack_id
        ]
        unmatched = [
            candidate for candidate in candidates if not candidate.hack_id
        ]
        self.save_sync_status_label.config(
            text=(
                f"{len(matched)} collection match(es) · "
                f"{len(unmatched)} import/review"
            ),
            foreground=STATUS_COLOR_SUCCESS,
        )
        self._show_save_sync_dialog(candidates, lookup_service=lookup_service)

    def _review_auto_scan(self):
        """Open retained results only when they still require review."""

        import save_sync

        collection = getattr(self.data_manager, "data", {})
        candidates = save_sync.auto_review_candidates(
            self._pending_auto_scan_candidates,
            collection=collection,
        )
        self._pending_auto_scan_candidates = []
        lookup_service = self._pending_auto_scan_lookup_service
        self._pending_auto_scan_lookup_service = None
        self.review_auto_scan_button.config(state="disabled")
        if not candidates:
            self.save_sync_status_label.config(
                text="Auto-scan: no changes to review",
                foreground=STATUS_COLOR_SUCCESS,
            )
            return
        self._show_save_sync_dialog(candidates, lookup_service=lookup_service)

    def _show_save_sync_dialog(self, candidates, lookup_service=None):
        """Open the existing review dialog; no scan path applies directly."""

        from ui.save_sync_dialog import SaveSyncDialog

        reload_cb = getattr(self, "reload_collection_callback", None)
        if self._review_is_open():
            self._review_dialog.win.lift()
            return
        dialog = SaveSyncDialog(
            self.frame.winfo_toplevel(),
            candidates,
            self.data_manager,
            logger=self.logger,
            on_applied=reload_cb,
            mark_all=self.save_sync_mark_all_var.get(),
            config_manager=self.setup_section.config,
            lookup_service=lookup_service,
        )
        self._review_dialog = dialog
        dialog.show()

    def _review_is_open(self):
        try:
            return bool(self._review_dialog and self._review_dialog.win
                        and self._review_dialog.win.winfo_exists())
        except tk.TclError:
            return False

    def _on_destroy(self, event):
        if event.widget is self.frame:
            self.cleanup()

    def cleanup(self):
        """Cancel owned timers when the application destroys this panel."""
        if self._closed:
            return
        self._closed = True
        jobs = self._startup_jobs + [self._periodic_scan_job]
        self._startup_jobs = []
        self._periodic_scan_job = None
        for job in jobs:
            if job is not None:
                try:
                    self.frame.after_cancel(job)
                except (AttributeError, tk.TclError):
                    pass
