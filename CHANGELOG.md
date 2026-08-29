# Changelog

- Added transactional repair for reviewed modern ROM assets whose `files[]` rows are missing `smwc_submission_id`; Apply writes only the reviewed per-ROM provenance and preserves all other Collection/file metadata.

All notable changes to SMWC Downloader & Patcher will be documented in this file.

## [Unreleased]

### Modern ROM missing-provenance review

- Numeric modern `files[]` ROM assets that are missing per-ROM `smwc_submission_id` can now open **Review Missing Provenance...** directly from the ROM organization audit.
- Each ROM asset is reviewed independently, so multiple ROMs on the same Collection entry can receive different explicit provenance decisions without collapsing to one record-level choice.
- Allowed choices come only from the Collection record's current numeric SMWC ID plus numeric IDs already present in prior-submission or identity-migration history; arbitrary/free-form submission IDs are not accepted.
- The review revalidates the exact audited asset path, primary flag, SHA-256, byte size, and still-missing provenance before accepting detached decisions.
- This boundary is decision-only: it performs no provider lookup, ROM hashing, Collection write, filesystem mutation, or organization planning.

### Transactional reviewed legacy ROM metadata Apply

- Reviewed-provenance modernization previews now expose **Apply Reviewed Metadata Backfill...** as an explicit Collection-only write boundary.
- Apply accepts only the dedicated reviewed modernization plan and revalidates that each selected SMWC submission ID is still present in the Collection record's current/prior numeric identity history.
- The exact Collection revision, legacy `file_path` ownership, duplicate ownership, regular non-symlink source state, byte size, source modification time, and SHA-256 are rechecked before the atomic commit, with ROM bytes verified again immediately before replacement.
- Only the frozen primary `files[]` row is written. ROM/save files, `file_path`, `additional_paths`, user-owned metadata, and unknown/future fields remain unchanged.
- All reviewed rows are committed through the same atomic `processed.json` transaction used by the unambiguous legacy backfill path; stale state or injected transaction failure cannot leave a partial modernization.

### Reviewed legacy ROM metadata modernization preview

- Explicit legacy provenance decisions can now continue to **Preview Modernization Plan...** after every ambiguous row has a saved recorded-history SMWC selection.
- Planning requires the exact legacy audit, provenance review, saved decision, and live Collection revision to agree before any ROM is accepted.
- Each reviewed ROM is revalidated as the same regular non-symlink `file_path` owner, duplicate ownership is rejected, and exact SHA-256/size/mtime evidence is frozen under stable before/after filesystem-stat checks.
- The proposed primary `files[]` row preserves the user-selected current/prior SMWC submission ID and records `legacy_collection_backfill_reviewed_provenance` as the backfill source.
- This boundary is deliberately read-only and uses a dedicated plan/preview type with no Apply action; Collection writes remain a later explicit commit.

### Explicit legacy ROM provenance review

- Legacy `file_path` records that are blocked because their numeric Collection entry has prior identity-migration provenance can now open **Review Provenance...** from the legacy metadata audit.
- Each row requires an explicit choice between the current numeric SMWC ID and numeric prior/history IDs already recorded on that Collection record; no provider search or inferred submission relationship is introduced.
- The review is bound to the exact Collection revision captured by the legacy audit and fails closed if Collection state changes before the choice boundary is opened.
- Saved choices are detached review state only. This commit does not hash ROMs, create `files[]`, move files, or persist Collection metadata; a later immutable modernization-plan boundary must consume and revalidate the decision.
- Unknown legacy identity forms and migrated records without a recorded alternative numeric SMWC ID remain blocked rather than receiving a guessed choice.

### Transactional historical ROM organization Apply

- Final historical ROM/save execution plans can now be applied explicitly through the proven journaled organization transaction engine.
- Apply maps each historical ROM's frozen `historical_smwc_submission_id` to the exact matching Collection `files[]` provenance precondition, preserving the current Collection identity while refusing stale or re-attributed assets.
- Historical Apply inherits copy-and-verify-before-commit, no-overwrite targets, atomic Collection path updates, post-commit source cleanup, rollback, and startup recovery semantics.
- No provider calls, layout discovery, save rediscovery decisions, or new semantic choices occur during Apply.

### Final historical ROM/save execution preview

- Historical ROM organization plans with completed save dispositions can now continue to **Preview Final Execution Plan...**.
- Finalization re-discovers save evidence, verifies the detached review fingerprint, rechecks Collection revision and historical ROM SHA-256/size/mtime/target vacancy, and hashes each migrated save under stable filesystem-stat checks.
- The immutable final plan retains the historical ROM submission/layout metadata together with exact ROM/save filesystem operations and Save Sync coverage-loss acknowledgements.
- This remains a read-only boundary: no Collection or filesystem mutation and no Apply action are introduced yet.

### Historical ROM save-impact review

- Immutable historical ROM move plans can now continue to **Review Save Dispositions...** using the same non-recursive colocated and configured Save Sync evidence rules as ordinary organization plans.
- Save discovery uses the historical plan's already-frozen source and target paths; it does not recompute catalogue layout or borrow current-submission metadata.
- Detached save-review fingerprints now include the historical SMWC submission ID, historical title, hack type, difficulty, and exact ROM byte preconditions so historically different plans cannot collapse to the same review identity.
- Historical save choices can be retained on the historical plan preview, including Save Sync coverage-loss acknowledgement, but no final execution-plan or Apply action is exposed yet.
- This boundary remains read-only and performs no ROM/save filesystem mutation, Collection rewrite, provider call, or Save Sync configuration change.

### Immutable historical ROM organization plan preview

- Historical provenance review rows marked **Ready for plan** can now be frozen through **Preview Historical Move Plan...** into a dedicated immutable read-only plan.
- Planning preserves the exact historical SMWC submission ID, catalogue title, hack type, and difficulty that justified each target instead of borrowing current Collection metadata.
- The planner rechecks the same Collection revision, exact modern `files[]` ownership/provenance, regular non-symlink source state, target vacancy, byte size, stable filesystem identity, and exact SHA-256 before freezing a move.
- The historical plan preview exposes no save review, final execution plan, or Apply action yet; connecting these frozen historical moves to the existing save-aware transactional organizer remains a later explicit boundary.

### Read-only historical ROM provenance organization review

- The ROM organization audit now exposes **Review Historical Provenance...** for modern `files[]` assets whose explicit per-ROM SMWC submission differs from the Collection record's current numeric submission.
- The review fetches rich metadata only for those already-recorded historical submission IDs and derives type/difficulty layout from each ROM's own submission metadata rather than borrowing current Collection metadata.
- The exact Collection revision is captured before metadata loading and the review is discarded if Collection state changes before presentation.
- Historical targets remain read-only: the review reports ready, already-in-place, missing, occupied, collision, and metadata-review states but exposes no move-plan or Apply action.
- Target collisions are checked both between historical assets and against ordinary current-submission move candidates from the same organization audit.
- Numeric assets with missing/unknown per-ROM provenance remain explicitly excluded; this workflow does not guess their submission identity or resolve ambiguous legacy migration provenance.

### Transactional legacy ROM metadata modernization Apply

- The immutable legacy ROM metadata preview now exposes an explicit **Apply Metadata Backfill...** confirmation boundary.
- Apply consumes only the frozen modernization plan and performs no provider/network discovery, matching, ROM/save movement, rename, copy, delete, or `additional_paths` reinterpretation.
- The exact Collection revision, legacy `file_path`, path ownership, regular non-symlink source state, byte size, source modification time, and SHA-256 are revalidated before the atomic Collection commit.
- Apply writes only the proposed primary `files[]` row and preserves `file_path`, `additional_paths`, user-owned fields, and unknown/future record fields unchanged.
- All selected records are published through one atomic `processed.json` transaction; stale state or pre-commit failure leaves the Collection unmodernized rather than partially backfilled.
- After success the organizer can be audited again and the newly modernized records can participate in the normal modern ROM organization workflow.

### Immutable legacy ROM metadata modernization preview

- Audit-ready legacy `file_path` ROMs can now proceed to **Preview Modernization Plan...** without changing Collection data.
- Planning revalidates the exact Collection revision, legacy path ownership, supported regular-file state, non-symlink status, and duplicate ownership before accepting a row.
- Each accepted ROM is SHA-256 hashed with stable before/after filesystem-stat checks and frozen with exact byte size and source modification time.
- The preview proposes one modern primary `files[]` row using the canonical ROM path, basename, SHA-256, byte size, `legacy_collection_backfill` ingestion provenance, and the audit-approved SMWC submission provenance when applicable.
- `file_path` remains unchanged as the compatibility projection, and legacy `additional_paths` are intentionally not reinterpreted as launchable modern ROM variants.
- This boundary is still read-only: there is no Collection write or filesystem mutation. A later explicit transactional Apply must verify the frozen preconditions again.

### Read-only legacy Collection ROM metadata audit

- The ROM organization audit now exposes **Review Legacy ROM Metadata...** when Collection still contains `file_path`-only ROM records.
- The legacy audit is read-only and intentionally performs no hashing, Collection writes, ROM/save moves, copies, renames, deletes, or directory creation.
- Existing numeric records without identity-migration provenance can be marked ready for a later metadata-backfill plan with the current Collection SMWC ID as proposed per-ROM provenance.
- Local opaque `usr_*` records can be marked ready without inventing numeric SMWC provenance.
- Numeric records that already carry prior-submission or identity-migration provenance remain review-only because the legacy `file_path` cannot safely be attributed to the current numeric ID automatically.
- Missing ROMs, symbolic links, unsupported file types, malformed `files` metadata, unknown legacy identity forms, and the same path claimed by multiple Collection records are explicit blockers.
- Ready rows still require exact SHA-256 hashing and a later immutable modernization plan before any `files[]` metadata is written.

### Save Sync coverage-aware ROM organization

- Colocated save review now distinguishes whether the save's current directory and planned destination directory are configured Save Sync scan sources.
- Because Save Sync scans configured folders non-recursively, migrating a colocated save out of its configured source may remove it from later Save Sync discovery.
- A **Migrate with ROM** choice that would leave configured Save Sync coverage now requires a second explicit acknowledgement; **Leave in place** and **Block this ROM move** remain available without that acknowledgement.
- Save Sync coverage-loss acknowledgement is frozen into the detached review decision and final execution plan, and stale/configuration-changed evidence fails closed during final planning.
- The final execution preview repeats the coverage-loss warning. Save Sync folders are never added, removed, or rewritten automatically by ROM organization.

### Transactional ROM/save organization Apply

- The finalized ROM/save organization preview now exposes an explicit **Apply Organization...** confirmation boundary.
- Apply consumes only the immutable final execution plan; it does not rerun layout decisions or save-disposition semantics.
- Reviewed ROM/save bytes are revalidated immediately before mutation, target paths must still be absent, and the current colocated `.srm`/`.sav` set must still match the reviewed plan.
- Files are copied to exclusively-created targets and verified first; Collection `files[]` paths and the primary `file_path` projection are committed only after all target copies are ready.
- Existing targets are never overwritten, and a finalized ROM destination already referenced elsewhere in Collection metadata fails closed.
- Old reviewed ROM/save sources are deleted only after a journaled commit point. Prepared interruptions roll back Collection/targets; committed interruptions keep the new state and finish source cleanup during recovery.
- Startup recovery now recognizes both Collection metadata Apply journals and ROM-organization journals, requires the same explicit other-instance confirmation, and refuses to guess recovery order if both journal types somehow exist.
- Collection metadata Apply also refuses to start while a ROM-organization journal is pending.

### Final immutable ROM/save organization execution preview

- Reviewed ROM organization plans can now produce a **Preview Final Execution Plan...** after save dispositions are complete.
- Final planning rechecks the exact Collection revision and rebuilds the save-impact review; changed save evidence invalidates the saved disposition fingerprint and must be reviewed again.
- Every approved ROM source is SHA-256 verified against its recorded modern `files[]` hash in addition to its recorded size and source modification time.
- Every colocated save selected for migration is SHA-256 hashed and frozen with exact source/target, size, and modification-time preconditions.
- Explicit **Leave in place** save choices are retained in the final preview, while ROM moves blocked during save review and all associated save actions are excluded.
- ROM and save targets are required to remain absent and inside the configured ROM output root; duplicate execution targets fail closed.
- The final preview contains no Apply/Execute action and performs no move, copy, rename, delete, directory creation, Collection rewrite, or Save Sync persistence.

### Explicit save dispositions for ROM organization

- The immutable ROM organization preview now opens **Review Save Dispositions...** and requires explicit user choices before save-aware filesystem planning can continue.
- Every detected colocated `.srm`/`.sav` companion must be marked **Migrate with ROM**, **Leave in place**, or **Block this ROM move**.
- A colocated save whose possible target is already occupied cannot be selected for migration; leaving it or blocking the ROM move remain explicit options.
- ROM moves with no detected colocated companion require an acknowledgement that the review found no colocated save but cannot prove emulator save state is absent elsewhere.
- Matching/associated saves in configured Save Sync folders remain informational evidence only and cannot receive migration dispositions because the emulator storage policy is unknown.
- Saved choices are detached and immutable, bound to a fingerprint of the exact organization plan and save-impact evidence so a later planning boundary can reject stale review state.
- This boundary still performs no ROM/save filesystem mutation, Collection rewrite, Save Sync persistence, or Apply/Execute action.

### Read-only ROM organization save-impact review

- The immutable ROM organization move preview now exposes **Review Save Impact...** before any filesystem execution exists.
- Save-impact discovery reports same-basename `.srm`/`.sav` files beside planned ROM sources, plus matching or explicitly associated saves found in configured Save Sync folders.
- Colocated saves receive only a hypothetical same-directory target beside the planned ROM destination; occupied targets are reported as conflicts rather than overwritten or merged.
- Configured/associated Save Sync files are treated as external/central evidence and are never assigned a migration destination because emulator save-location policy cannot be inferred from Save Sync settings.
- A review with no detected save still warns that emulator-specific save state may exist elsewhere.
- This boundary performs no ROM/save move, rename, copy, delete, directory creation, Collection rewrite, or config persistence.

### Immutable Collection ROM organization move preview

- The read-only ROM layout audit can now freeze its safe **Would move** rows into an immutable move plan without touching ROM/save files or Collection metadata.
- Move candidates now require exact modern `files[]` byte identity: a lowercase SHA-256, recorded byte size, a present non-symlink source, and a current source size that still matches Collection state.
- The move plan captures the current Collection revision plus each source path, target path, SHA-256, byte size, source modification time, primary flag, and per-ROM SMWC provenance.
- Plan finalization rechecks that Collection layout metadata still resolves to the audited destination and that the target path is still absent; stale audit state fails closed and must be audited again.
- Audit blockers remain explicitly excluded from the safe move plan rather than being silently converted into filesystem actions.
- The plan preview has no Apply/Execute action. Save migration and filesystem execution remain separate later boundaries.

### Read-only Collection ROM organization audit

- Added **Audit ROM Layout...** to the Collection page for comparing recorded ROM assets with the configured type/difficulty output layout without changing disk or Collection state.
- The audit shows already-organized assets, safe future move candidates, missing sources, occupied targets, target collisions, malformed modern ROM metadata, and legacy references that require review.
- Numeric Collection assets are only given a move candidate when per-ROM SMWC provenance matches the current numeric Collection identity; retained historical-submission ROMs remain review-only.
- Local `usr_*` modern assets can be assessed from their user-owned type/difficulty metadata, while legacy `file_path`-only entries remain visible but are not promoted into move candidates.
- No ROM/save move, rename, copy, delete, hashing, directory creation, metadata rewrite, or save migration is performed by this audit.

### Non-destructive ROM metadata refresh

- Refreshing an already-downloaded hack no longer moves its existing ROM when SMWCentral difficulty metadata points at a different configured output folder.
- The refresh updates catalogue metadata while leaving `file_path`, modern `files[]`, `additional_paths`, ROM bytes, and save files in place.
- A new read-only ROM-location assessment reports configured layout drift without creating directories or changing Collection state.
- Explicit ROM organization/consolidation remains a separate workflow; metadata refresh never performs a hidden relocation.

### ROM matcher calibration hardening

- Added a read-only developer calibration tool for comparing known numeric Collection ROM filenames against a lightweight KaizOFF/SMWC catalogue without printing local filesystem paths.
- Calibrated the current conservative matcher against the supplied legacy Collection snapshot and current 2,820-entry KaizOFF Index: 152 eligible known-ROM cases produced 140 correct automatic matches, 12 review cases with the correct top suggestion, zero wrong automatic matches, and zero wrong top suggestions.
- Added regression cases for the ambiguous, abbreviated, partial-title, and sequel-sensitive filenames that correctly remained review-only; matcher thresholds were intentionally left unchanged.

### Collection transaction startup recovery

- The application now checks for an existing coordinated Collection Apply journal before constructing Collection, Planner, or Save Sync UI/store owners.
- Journals are inspected and validated read-only first; startup distinguishes `prepared` transactions from already-`committed` cleanup state.
- Recovery is never automatic because the journal may belong to another still-running application instance. The user must confirm every other instance is closed before recovery runs.
- Choosing not to recover exits before Collection-dependent features start and leaves the journal, rollback material, and store files untouched.
- Invalid or unrecoverable journals fail closed and stop startup rather than allowing new Collection edits on uncertain cross-store state.
- Difficulty/config initialization now occurs after the recovery gate because `config.json` may participate in Collection identity migrations.

<!-- collection-update-discovery:start -->
### Collection update/replacement discovery

- Added an explicit **Find Update...** action for existing numeric SMWC Collection entries.
- Refreshes the lightweight KaizOFF Index in the background and shows only possible related
  submissions; it never claims that a different SMWC ID is automatically newer.
- Supports local frozen-Index search by title or SMWC ID, including targets that already exist
  in Collection.
- After explicit relationship confirmation, hydrates only the selected target's rich KaizOFF
  detail and builds an immutable numeric-to-numeric replacement plan for read-only preview.
- The replacement preview shows the exact Collection identity/catalogue/reference changes while
  remaining non-applying; no target ROM is downloaded or patched and no filesystem data moves.
- Existing numeric targets now open a separate read-only merge review before any replacement
  plan is built. The review requires explicit choices for conflicting user-owned fields, first-clear
  references, and competing primary ROMs while preserving safely combinable ROM/history state.
- Unknown conflicting fields, conflicting imported playthrough identities, the same ROM path
  carrying different SHA-256 values, and distinct legacy file_path-only primaries fail closed instead
  of falling through to generic merge rules that could lose local state.
- A completed existing-target merge review now hydrates only the explicitly selected target,
  freezes Collection/hints/Save Sync/optional Planner state, and builds an immutable replacement
  merge plan for read-only preview.
- The merge plan records every reviewed user-state choice plus any reviewed primary-ROM selection
  after the structural identity merge, so preview and a later Apply cannot disagree.
- Finalized replacement and reviewed existing-target merge plans can now cross an explicit
  **Apply Replacement...** confirmation boundary. Apply consumes only the immutable reviewed plan,
  writes Collection/hints/Save Sync/optional Planner references through the existing coordinated
  transaction journal, and reloads live application state after commit/recovery.
- Replacement Apply performs no discovery, KaizOFF hydration, target-ROM download/patching, or
  filesystem organization. Retained ROM/save files stay in place.
- Replacement plans now preserve per-ROM SMWC submission provenance explicitly for retained
  modern `files[]` rows before a numeric identity migration. Source-only ROMs with no prior
  provenance are associated with the old/source SMWC ID; existing-target ROMs are associated
  with the target ID, while already explicit provenance is never silently relabeled.
- Conflicting explicit provenance for the same retained ROM path fails closed, and the exact
  provenance changes are visible in the immutable replacement preview before Apply.
- Replacement Apply shares the Collection transaction recovery journal and stale-state checks used
  by ingestion; an existing journal is never assumed abandoned without explicit user confirmation.
- Replacement previews for targets that do not already exist in Collection can now **Acquire Target ROM...** before Apply.
- Acquisition uses the already-hydrated validated SMWCentral download URL, the configured clean base ROM, the normal output directory, and the shared optional SMWC-ID filename policy.
- Archives are downloaded with bounded response and extracted sizes, patched ROM outputs are size-bounded in staging, and all selected outputs are hashed before the immutable replacement plan is rebuilt.
- Multi-patch archives reuse the existing explicit patch-selection/default-ROM dialog; acquisition never guesses between multiple patch files.
- New ROM outputs are published with exclusive-create semantics only after reviewed Collection/hints/Save Sync/Planner preconditions are rechecked, so existing files are never overwritten.
- The acquired target ROM is recorded with SHA-256, size, `tool_patch` source provenance, and the selected target SMWC submission ID, and becomes the reviewed primary ROM.
- Apply verifies the acquired ROM bytes again before any Collection write and remains network/patch-free. If acquisition succeeds but the user later cancels the replacement, the newly created ROM remains on disk as an ordinary user file.
- Existing-target merge reviews do not accept a new acquisition afterward because that would introduce a new primary-ROM decision outside the completed merge review.

<!-- collection-update-discovery:end -->

### Collection ROM asset visibility and primary selection

- The Edit Hack dialog now shows modern `files[]` ROM assets for both numeric SMWC entries and local/manual `usr_*` entries.
- ROM rows expose availability, recorded size, abbreviated SHA-256, per-ROM SMWC provenance, ingestion source, and full path without changing filesystem data.
- Multi-ROM Collection entries can explicitly change the primary ROM; saving updates `files[].primary` and the compatibility `file_path` projection together.
- Local/manual entries that already own modern `files[]` no longer expose a separate editable `file_path` field that could diverge from the authoritative asset list.
- Unknown per-ROM fields are preserved when primary selection changes, and malformed/duplicate ROM asset state fails closed in the UI helper layer.

### Modern ROM asset persistence

- Newly patched normal-download ROMs now enter Collection `files[]` with SHA-256, exact byte size, `tool_patch` source provenance, and their known SMWC submission ID.
- Single-patch downloads now use the same modern multi-file structure as ingestion/replacement flows while keeping `file_path` as the compatibility projection of the selected primary ROM.
- Re-downloads merge newly patched assets with existing modern ROM rows instead of discarding other retained variants, and the newly patched output becomes primary.
- Refreshing/re-downloading an existing SMWC entry overlays provider/download facts onto the existing Collection record so imported history, completion, notes, personal rating, and unknown future/local fields survive.
- Multi-type distribution copies remain represented by the existing `additional_paths` compatibility field; this commit does not reinterpret those copies as separate launchable variants.

### Optional SMWC-ID ROM filenames

- Added a **Settings → ROM File Naming** option to include the known SMWC submission ID in newly patched ROM filenames.
- The option defaults OFF and uses the portable form `Hack [SMWC-ID-43123].sfc` when enabled.
- Existing ROMs and save files are never renamed or moved when the setting changes.
- Normal single-patch and multi-patch download paths share one filename policy so future replacement-ROM acquisition can use the same rule.
- The application warns that emulator save associations commonly depend on ROM basename, which is why the setting is opt-in.

<!-- collection-wheel:start -->
### Collection Wheel

- Added independent Collection filters for completion, type, difficulty,
  download status, SMWC Rating, and release year.
- Added optional Planner refinements for lifecycle, planning horizon, and
  custom lists.
- Added a non-blocking animated circular Wheel, Spin Again, stable pointer
  landing, and Collection result focus.
- Synchronized and displayed SMWC Rating separately from Personal Rating.
- Kept Wheel filtering and selection read-only.
- Added a separate managed Browser / OBS runtime while keeping native selection authoritative.

<!-- collection-wheel:end -->

<!-- wheel-browser-runtime:start -->
### Browser / OBS Wheel

- Added a managed loopback-only Browser / OBS Wheel owned by the Collection
  Wheel dialog.
- Kept the browser synchronized with the exact filtered and reroll pools.
- Animated the Python-authored predetermined winner without browser-side
  selection.
- Added a full preview URL and a transparent OBS overlay that hides while idle.
- Finalized a continuous 5.5-second, nine-turn show animation with smooth
  acceleration, a high-speed middle, and deceleration tapering to zero.
- Added nine weighted landing bands, including hairline-edge finishes, while
  keeping the winner and landing offset Python-authored.
- Synchronized the native Wheel to the same show timing and exact landing offset
  whenever the managed Browser runtime is active.
- Preserved the quick five-turn, 61-frame native-only animation while the
  Browser runtime is stopped.
- Kept rotating segment labels upright.
- Wrapped and responsively sized complete winner titles.
- Added an eight-second result hold and spin-seeded celebration variation for
  sparks, rings, card tilt, and winner emphasis.
- Added a read-only health, snapshot, and spin-state API.
- Added a self-contained browser renderer with no external assets.
- Kept standalone operation, Streamer.bot commands, and remote access outside
  the current scope.

<!-- wheel-browser-runtime:end -->
<!-- planner-foundation:start -->
### Planner foundation

- Added a Planner page that projects existing collection records into separate
  lifecycle status, Someday/Soon/Next planning horizon, ordered Next queue, and
  multi-membership custom-list fields.
- Added staged single and bulk edits with explicit **Save Changes** and
  **Discard Changes** boundaries.
- Added custom-list creation, renaming, deletion, and bulk membership editing
  with stable internal list IDs.
- Added composable search and filtering shared by the Planner and the intended
  future filter-driven Wheel pool.
- Kept Planner state in a separate versioned `planner_state.json`, preserving
  `processed.json` and inferring Completed for legacy completed records.
- Replaced the prototype's fixed priority and per-hack wheel-eligibility model
  with Someday/Soon/Next and filter-driven selection.
- Documented the Planner workflow, compatibility behavior, persistence safety,
  and current Wheel limitation in `PLANNER.md`.
- Added an optional Planner visibility setting that hides Planner UI surfaces
  while preserving Planner-owned state and Collection-ID migration participation.
<!-- planner-foundation:end -->

<!-- save-data-sync-expansion:start -->
### Save Data Sync expansion

- Added structured save-analysis evidence for standard slots, backup copies,
  low-confidence legacy counters, and fail-closed expanded SRAM handling.
- Added privacy-safe diagnostic JSON export with effective matching summaries.
- Added explicit manual SMWCentral search and remembered filename associations,
  including a safe **Forget Saved Match** lifecycle.
- Added ordered multiple save-source folders with legacy-setting migration,
  deduplication, and unavailable-source handling.
- Added opt-in startup and periodic review scans that never apply collection
  changes automatically.
- Added local save-backed collection entries for non-SMWCentral hacks, including
  stable IDs, metadata editing, safe association removal, and record removal
  that never deletes save or ROM files.
- Preserved **Apply Selected** as the required boundary for every collection
  write.
- Documented the full workflow, confidence model, privacy boundary, and known
  limitations in `SAVE_DATA_SYNC.md`.
<!-- save-data-sync-expansion:end -->

## [5.1] - 2026-07-01

### Added
- **Save Data Sync**: New Settings utility to sync completion status from your emulator/console save files
  - Point it at a folder of `.srm`/`.sav` battery saves; matching hacks in your collection are marked completed
  - Completion is detected by reading the SMW SRAM collected-exit count (byte `0x8C`) and comparing it to each hack's total `exits` — or optionally marking every matched save as completed via a toggle
  - `completed_date` is taken from each save file's last-modified timestamp
  - `.srm` and `.sav` files are read identically (same raw SMW SRAM layout); play time is not stored in SNES saves, so `time_to_beat` is left untouched
  - Preview & confirm dialog lists every proposed change with per-row checkboxes; unmatched files are shown in a readable, scrollable list and nothing is written until you apply
  - Garbage/oversized reads (e.g. FXPak-padded files) are flagged "uncertain" rather than falsely completed
  - **Import from SMWC**: unmatched saves can be looked up on SMWCentral by name and imported as full collection entries — keyed by the real SMWC ID (with difficulty/type/exits/authors/date), so a later download or update merges into the same entry instead of creating a duplicate. Ambiguous or no-match lookups are reported, never guessed; saves that resolve to a hack already in your collection just update its completion.

### Fixed
- **Settings page now scrolls**: the Settings page is wrapped in a scrollable container so content (including the log window) is never clipped on smaller/minimum-size windows. The mouse wheel scrolls the page, except over the log area where it scrolls the log's own contents.

## [5.0] - 2026-03-15

### Added
- **Multi-BPS File Support**: When a hack ZIP contains multiple BPS patch files, a dialog lets you choose which versions to download and which to set as the default
  - Checkbox per file to include/exclude
  - Radio button to select the default file (opens automatically when launching from Collection)
  - Output filenames are auto-suggested from the BPS filename with proper title-casing
  - All selected files are patched and saved; `processed.json` records the full `files` array with `primary` flags
- **ROM Files Section in Edit Hack Dialog**: For downloaded hacks with multiple patch files, the Edit Hack dialog now shows a ROM Files section
  - Lists all patched ROMs for that hack
  - Radio button to change which file is the default
  - Saving updates both the `files` array and `file_path` in `processed.json`
- **Multi-ROM Picker in Collection**: Clicking play (▶) on a multi-file hack shows a picker dialog to choose which ROM version to launch

### Fixed
- **Emulator Play Icon Not Appearing After Setup**: Configuring an emulator in Settings now immediately refreshes play icons in the Collection table without requiring an app restart
  - `emulator_settings_callback` is now wired to `refresh_emulator_cache()` in layout initialization

### Changed
- **`title_case` Improvements**:
  - Version tokens (`v1.10`, `v2.0`, etc.) always stay lowercase-v regardless of position
  - Words starting with `(`, `[`, `{` are always capitalised (e.g. `(Not` not `(not`)
  - Words ending with `)`, `]`, `}` are always capitalised
  - `not` added to lowercase words list
  - `so` removed from lowercase words list (now capitalises normally)
- **Dialog Height**: Edit Hack dialog auto-sizes to fit the ROM Files section when present

## [4.9] - 2026-01-12

### Added
- **Column Configuration**: Customize which columns are visible in the Collection page
  - Drag-and-drop reordering with visual feedback (floating label shows column being dragged)
  - Show/hide individual columns with checkboxes
  - "Reset to Default" button restores original column order
  - Settings persist across app sessions in config.json
  - Widget lifecycle protection prevents TclError crashes during drag operations
- **Fetch Metadata Feature**: Bulk update missing release dates and other metadata from SMWC
  - Optimized bulk API fetching (60-100x faster than individual calls)
  - Checks both moderated AND waiting sections
  - Fallback to individual API calls for obsolete/unlisted hacks
  - Cancellable operation (safe to cancel during API fetch phase)
  - Completes in under 1 minute for most collections vs 30+ minutes previously
  - Accessible via Settings → Data Migration section
- **UI Color Theme Constants**: Consistent status message colors across the application
  - Info/In-Progress: `#4FC3F7` (light cyan - much more readable than previous blue)
  - Success: `#66BB6A` (green)
  - Warning: `#FFA726` (orange)
  - Error: `#EF5350` (red)
  - Centralized in `ui_constants.py` for easy theming
- **Collection Page Locking**: Prevents data corruption during background operations
  - Locks Collection page during: Fetch Metadata, Difficulty Migrations, Silent Migrations
  - User sees "⏸️ Collection locked" message with reason during operations
  - Automatic unlock when operation completes, fails, or is cancelled

### Changed
- **Simplified Log Messages**: Cleaner, more concise logging
  - "🔄 Reloaded X hacks from disk" (removed debug caller information)
  - Shortened migration status messages to prevent UI layout issues
  - "✅ Everything is up to date!" instead of verbose success messages
- **Data Migration Section Layout**: Reduced text wrap length (428→380px) to prevent cutoff
- **Metadata Fetch Dialog**: Updated text to reflect optimization and cancellation support

### Fixed
- **Drag-and-Drop Column Configuration**:
  - Fixed TclError crashes when widgets were destroyed during rebuild
  - Added `winfo_exists()` checks before configuring widgets
  - Added try-except blocks for robust error handling
- **Reset to Default Button**:
  - Fixed button doing nothing (column_order/visible_columns not in config whitelist)
  - Now properly restores DEFAULT_COLUMNS constant
- **Duplicate Reload Logging**: Fixed "Reloaded X hacks" appearing twice when clicking Refresh List
  - Added `_is_refreshing` guard flag with try-finally protection
  - Removed duplicate `show()` refresh call
- **Obsolete Hack Metadata**: Fixed hacks with old/replaced IDs not getting metadata updates
  - Added fallback individual API lookups for hacks not found in bulk fetch
  - Properly detects and handles unlisted/obsolete versions
  - Warns users about hacks that couldn't be updated

### Technical
- Added `DEFAULT_COLUMNS` constant to preserve original column order
- Column configuration uses `default_columns` parameter for true defaults
- Enhanced `backfill_metadata()` with `cancel_check` parameter
- Cancellation safe during API fetch, prevents cancel during file write
- Returns -1 when cancelled for proper UI state handling

## [4.8] - 2025-12-29

### Added
- **Emulator Integration**: Launch ROMs directly from the Collection page with one click
  - Configure any emulator (RetroArch, Snes9x, bsnes, etc.) in Settings
  - Custom command-line arguments with `%1` placeholder support for ROM file path
  - Cross-platform support: Windows, macOS (.app bundles), and Linux
  - Play icon (▶) appears next to downloaded hacks when emulator is configured
  - Quick launch functionality integrated into Collection page interface
- **macOS .app Bundle Support**: Automatic conversion of `.app` bundles to executable paths
  - Select `Snes9x.app` and the app automatically finds `Snes9x.app/Contents/MacOS/Snes9x`
  - Works with all standard macOS application bundles
  - Seamless integration with macOS application structure
- **Live Difficulty Mapping from SMWC API**: Automatically fetches current difficulty categories from SMWC on app startup
  - Difficulty mappings cached in config.json for offline use
  - Ensures app always uses latest SMWC difficulty names without code updates
  - Falls back to hardcoded defaults if API unavailable
- **Difficulty Migration System**: Automatic detection and migration of SMWC difficulty category renames
  - Auto-detects when difficulty names have changed by comparing against live SMWC data
  - Migration UI in Settings page with check/apply buttons
  - Shows affected hack counts before applying changes
  - Automatically renames difficulty folders and updates file paths
  - Creates automatic backups before making any changes
  - Zero configuration needed - fully data-driven detection
- **Difficulty ID Tracking**: Store raw difficulty IDs (`diff_1`, `diff_2`, etc.) for reliable rename detection
  - Enables automatic detection of future SMWC difficulty renames
  - Backward compatible with existing data via automatic v4.8 migration
- **Automatic v4.8 Migration**: Seamless upgrade from v4.7
  - Automatically adds `current_difficulty` and `difficulty_id` fields to existing hacks
  - Silent migration on first launch - no user intervention needed
  - Creates backup at `processed.json.pre-v4.8.backup`

### Changed
- **Settings Page Layout**: Optimized layout with Emulator and Difficulty Migration sections side-by-side for better space utilization
- **Enhanced log section**: More vertical space for better readability
- **Improved cross-platform emulator path handling**: Better detection and handling of different emulator formats
- **Difficulty Data Model Consolidation**:
  - Removed redundant `difficulty` field
  - Now uses only `difficulty_id` (source) and `current_difficulty` (display)
  - Collection page and filters updated to use new field structure
- Updated difficulty category from "Skilled" to "Intermediate" to match SMWC
- All UI components now use "Intermediate" instead of "Skilled"
- Updated difficulty lists in download page, filters, charts, and data manager
- Difficulty mappings now fetched from SMWC API instead of hardcoded

### Fixed
- **macOS/Linux Difficulty Migration Fix**: Fixed difficulty migration not working on macOS and Linux
  - DifficultyMigrator now uses platform-specific processed.json path by default
  - Windows stores processed.json next to executable (portable mode)
  - macOS stores in ~/Library/Application Support/SMWC Downloader/
  - Linux stores in ~/.smwc-downloader/
  - Added difficulty_migration and difficulty_lookup_manager to PyInstaller hiddenimports
- Collection page Type filter now correctly finds multi-type hacks (e.g., searching "Puzzle" finds "Standard, Puzzle")
- Collection page difficulty filter now works correctly with new data model
- Removed obsolete difficulty field sync that was causing false migration warnings

### Technical
- New `difficulty_lookup_manager.py` module for fetching difficulty mappings from SMWC API
- Enhanced `difficulty_migration.py` with backfill and API-based detection
- New `migrate_to_v48()` function in `migration_manager.py` for automatic upgrades
- `ConfigManager` extended to store and retrieve difficulty lookup cache
- Global `DIFFICULTY_LOOKUP` in utils.py updated on app startup with live data
- `hack_data_manager.get_all_hacks()` transforms data for UI consumption
- Comprehensive migration documentation in DIFFICULTY_MIGRATION_README.md
- Migration system compares stored difficulty_id vs live SMWC API data
- Backward compatibility maintained with "skilled" search term
- Type filter uses containment check for multi-type hack support

## [4.7] - 2025-01-XX

### Added
- Enhanced download selection and filter controls
- Improved layout and responsiveness of UI components

- Improved UI responsiveness and scrolling
- Better error handling and stability
- Threading cleanup improvements
- Download completion messaging
- Obsolete records filtering

### Fixed
- Fixed threading cleanup errors during shutdown
- Improved font consistency across themes
- Better navigation update handling

### Changed
- Updated version to v4.4
- Streamlined GitHub Actions workflows

## [4.3] - Previous Release

### Added
- Previous features...

### Fixed
- Previous fixes...
