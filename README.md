# SMWC Downloader & Patcher

🎮 **Download and play Super Mario World ROM hacks with one click**

A simple desktop app that automatically downloads, patches, and organizes ROM hacks from SMWCentral. Works on Windows, Mac, and Linux.

> [!NOTE]
> This branch is the v5.1 development line. Candidate packages are built and verified by GitHub Actions for Windows x64, Linux x64, macOS Apple Silicon, and macOS Intel. Development builds do not check for or install updates in place.

Developer documentation: [CONTRIBUTING.md](CONTRIBUTING.md), [Build and Release Instructions](.github/BUILD_INSTRUCTIONS.md), and [Product Identity and Version Management](VERSION_MANAGEMENT.md).

![Dashboard](images/application-5.0-dashboard.png)

## 📋 Table of Contents

- [📥 Download & Install](#-download--install)
- [🚀 How to Use](#-how-to-use)
- [🗂️ Planner](PLANNER.md)
- [🛠️ Troubleshooting](#️-troubleshooting)
- [📝 What You Need](#-what-you-need)
- [📝 Changelog](#-changelog)

## 📥 Download & Install

Download the package matching your operating system from the [Releases page](../../releases) or, for development testing, from a successful **v5.1 Candidate CI** workflow run. Artifact filenames include the manifest version.

### Windows 10/11 x64

1. Download `SMWC-Downloader-<version>-Windows-x64.zip`.
2. Extract the ZIP into a normal writable folder.
3. Launch `SMWC Downloader.exe`.
4. For an unsigned development build, Windows may require **More info → Run anyway**.

### macOS 10.15+

Choose the package matching the Mac:

- Apple Silicon: `SMWC-Downloader-<version>-macOS-arm64.dmg`
- Intel: `SMWC-Downloader-<version>-macOS-x86_64.dmg`

Open the DMG and copy the application to Applications. Unsigned builds may require right-clicking the application and choosing **Open** the first time. The project does not currently publish a Universal macOS package.

### Linux x86_64

1. Download `SMWC-Downloader-<version>-Linux-x64.tar.gz`.
2. Extract it: `tar -xzf SMWC-Downloader-*-Linux-x64.tar.gz`.
3. Run the packaged executable from the extracted directory.

The current build contract publishes a native tarball rather than an AppImage. Extract development candidates into a fresh folder when testing so the packaged files are not mixed with an older candidate.

## 🚀 How to Use

### First Time Setup
1. **Launch the app** - it will open to the main dashboard
2. **Go to Settings**: Click the "Settings" tab at the top of the app
3. **Set your ROM folder**: Click the folder icon to choose where you want your patched ROMs saved
4. **Add your base ROM**: Click "Browse" next to "Super Mario World ROM" and select your clean SMW ROM file
5. **You're ready!** The app will remember these settings and you can return to the main dashboard

### Downloading ROM Hacks
1. **Set your filters**: Use the filter options to narrow down what you want to search for (difficulty, type, author, etc.)
2. **Choose display mode**: Use the "Show only non-downloaded hacks" checkbox to hide hacks you already own, making it easier to find new content
3. **Search for hacks**: Click the "Search Hacks" button to pull data from the SMWCentral API based on your filters
4. **Browse results as they load**: Results appear progressively as each page loads - no need to wait for all data to finish loading
5. **Select hacks to download**: Click the checkmark in the first column for each hack you want to download
   - **Tip**: Click the column header to select ALL hacks at once
   - **Already downloaded hacks** are shown in italic with muted colors to help you identify what you already own
6. **Start downloading**: Click "Download & Patch" to begin downloading and patching your selected hacks
   - Optional: Settings → ROM File Naming can add portable `[SMWC-ID-<id>]` evidence to **new** patched ROM filenames. This is OFF by default.
   - Enabling it does not rename existing ROMs or saves; many emulators associate saves by ROM basename, so existing save-name behavior is intentionally left untouched.
7. **Multi-BPS dialog**: If a hack contains multiple patch files (e.g. different versions), a dialog will appear letting you choose which files to download and which is the default
8. **Wait for completion**: The app will automatically download each hack and apply it to your base ROM
   - Newly patched ROMs are recorded in Collection with SHA-256, exact size, `tool_patch` acquisition provenance, and the known SMWC submission ID even when the optional ID-in-filename setting is OFF.
   - Re-downloading an existing Collection entry preserves its user-owned/local state (completion, notes, personal rating, imported history, and newer unknown fields) while refreshing provider/download facts.
   - Refreshing catalogue metadata does **not** relocate an already-existing ROM merely because its SMWC difficulty/type folder changed. Existing ROM/save locations are left untouched for a separate explicit organization workflow.
9. **Play**: Your patched ROMs will be saved to your chosen folder, ready to play in any emulator

![Download Page](images/application-5.0-download.png)

![Multi-BPS Dialog](images/application-5.0-download-multiple-bps.png)

### Interrupted Collection transaction recovery

Collection imports and explicit SMWC replacement migrations can update Collection state together with dependent Save Sync, identity-hint, and optional Planner references. These coordinated writes use a recovery journal.

If the application starts and finds such a journal, it **does not recover automatically**. The journal could still belong to another application instance that is actively applying changes. Startup instead:

1. validates and inspects the journal without changing any store;
2. tells you whether the transaction is still `prepared` (rollback may be required) or already `committed` (cleanup remains);
3. asks you to close every other SMWC Downloader & Patcher instance before explicitly choosing recovery;
4. exits without touching the journal or Collection-dependent stores if you choose not to recover;
5. blocks startup if the journal is malformed or cannot be recovered safely.

This gate runs before Collection, Planner, and Save Sync UI/store owners are constructed, so normal edits cannot race or overwrite rollback material from an interrupted transaction.

### ROM title matcher calibration

ROM-folder ingestion intentionally prefers review over a risky automatic identity decision. The developer tool `tools/rom_match_calibration.py` can compare numeric Collection entries with recorded ROM paths against a lightweight KaizOFF/SMWC catalogue and report aggregate matching outcomes. It is read-only and does not print local filesystem paths.

Example:

```bash
python tools/rom_match_calibration.py processed.json KaizOFF-API-Public-v1-Hacks-Index.json
```

The current matcher was calibrated against a legacy real-world Collection snapshot and the supplied 2,820-entry KaizOFF Index. Of 152 eligible known-ROM records, 140 were safely auto-selected and the remaining 12 were held for review; all 152 still had the correct known submission as the top suggestion, with zero wrong automatic matches. Because the held cases were ambiguous abbreviations, short/partial titles, or sequel-sensitive names, the thresholds remain deliberately conservative.

### Managing Your Collection
1. **View your collection**: Click the "Collection" tab to see all your downloaded ROMs
2. **Customize columns**: Click the "⚙ Columns" button to show/hide columns and reorder them via drag-and-drop
   - Drag column names to reorder (visual feedback shows what you're moving)
   - Check/uncheck boxes to show/hide specific columns
   - Click "Reset to Default" to restore original layout
   - Your preferences are saved automatically
3. **Add hacks manually**: Use the "Add Hack" button to track hacks you've played from other sources
4. **Track progress**: Mark hacks as completed, rate them (1-5 stars), and add personal notes
5. **Quick editing**: Click directly on completion dates, time to beat, or notes to edit them
6. **Advanced editing**: Double-click any hack to open the full edit dialog
7. **�️ Delete a hack**: Inside the edit dialog, click **Delete** to permanently remove a hack from your collection
   - If a ROM file is associated with the hack, it will also be deleted from your file system
   - A clear confirmation prompt tells you exactly what will be removed before you confirm
   - Works for both downloaded SMWC hacks and manually added hacks
8. **📁 Quick file access**: Click the folder icon next to any hack name to instantly open its file location in your system's file manager
9. **🎮 Quick launch**: Click the play icon (▶) next to any hack to launch it directly in your configured emulator
   - For hacks with multiple versions, clicking ▶ opens the default version immediately
   - Enable "Show version picker" in Settings to get a picker dialog instead, letting you choose which ROM to launch
   - Change the default version any time via the Edit Hack dialog → ROM Files section
10. **Filter and sort**: Use filters to find specific hacks, or click column headers to sort
11. **Check a known SMWC entry for a possible replacement**: Select a numeric SMWC Collection row and click **Find Update...**
   - The app refreshes the lightweight KaizOFF Index and ranks/searches possible related submissions
   - A different SMWC ID is never automatically treated as a newer version; you must recognize and confirm the relationship yourself
   - After you explicitly confirm a relationship, only that target's rich KaizOFF detail is hydrated and an immutable replacement plan is shown
   - The replacement plan preview now requires an explicit **Apply Replacement...** confirmation before the reviewed numeric identity migration is written transactionally
   - If the selected target does not already exist in Collection, **Acquire Target ROM...** can download and patch it before Apply using your configured clean base ROM/output directory and the same optional SMWC-ID filename policy as normal downloads
   - Acquisition bounds both the downloaded archive and its extracted contents, stages and size-checks patched ROMs first, never overwrites an existing ROM filename, hashes the resulting ROM, and rebuilds the immutable preview with that target ROM as the reviewed primary
   - Multi-patch target archives reuse the normal explicit patch-selection dialog; the app never guesses which of several patches should become the replacement ROM
   - Apply does not rerun discovery, provider hydration, downloading, or patching. When a target ROM was acquired, Apply verifies its exact size/SHA-256 again before writing Collection state
   - If you acquire a target ROM and then close/cancel the replacement instead of applying it, the new ROM stays on disk; Collection identity remains unchanged
   - If the target already exists in Collection, the app opens an explicit read-only merge review instead of choosing between independent user-owned state
   - Post-review target-ROM acquisition is intentionally unavailable for an existing-target merge, because adding a new ROM afterward would create a new primary-ROM choice outside the completed merge review
   - Conflicting notes, rating, time/completion-date/first-clear values and different primary ROMs require explicit source/target choices; safely combinable ROM/history state is retained together
   - Unsupported conflicting state fails closed; after a valid merge review, the app hydrates only the selected target and shows an immutable read-only merge plan containing the exact reviewed choices
   - The reviewed merge plan uses the same explicit transactional Apply boundary; no ROM/save files are downloaded, patched, moved, renamed, or deleted
   - Retained modern ROM rows preserve explicit SMWC submission provenance in the plan, so an old/source ROM does not silently become attributed to the newly selected numeric submission after a future migration
   - Existing explicit per-ROM provenance is preserved; contradictory provenance for the same retained path fails closed instead of being guessed
12. **Audit and preview ROM library organization**: Click **Audit ROM Layout...** to compare recorded modern ROM assets with the configured output directory and type/difficulty folder layout
   - The audit is read-only: it does not move, rename, copy, delete, hash, or modify ROM/save files or Collection metadata
   - Assets already in place and safe future move candidates are shown separately from missing files, occupied targets, target collisions, and metadata/provenance review states
   - A ROM becomes **Would move** only when modern `files[]` contains exact SHA-256 + byte-size identity and the current non-symlink source still matches its recorded size
   - Click **Preview Safe Move Plan...** to freeze only those safe rows into an immutable read-only plan bound to the current Collection revision and exact source/target preconditions
   - The plan records source and destination paths, SHA-256, byte size, source modification time, primary selection, and per-ROM SMWC provenance; it still exposes no Apply/Execute action
   - Click **Review Save Dispositions...** to inspect plausible `.srm`/`.sav` relationships and record explicit detached choices before any move execution exists. Same-basename saves beside a planned ROM must be marked **Migrate with ROM**, **Leave in place**, or **Block this ROM move**
   - A colocated save whose hypothetical destination is already occupied cannot be selected for migration; configured or explicitly associated Save Sync files remain external evidence with no proposed migration path or disposition
   - If a colocated save currently sits directly in a configured Save Sync source but its planned destination directory is not configured, the review flags that migration would leave Save Sync scan coverage and requires a second explicit acknowledgement before **Migrate with ROM** can be saved
   - Save Sync scans configured directories non-recursively, so the organizer compares exact current/destination directories; it may also report when coverage is retained or gained
   - ROM organization never rewrites the configured Save Sync folder list automatically, even after an explicitly acknowledged coverage-loss migration
   - If no colocated save is detected for a planned ROM, explicitly acknowledge that result before saving the review. This means only that the known review found no colocated `.srm`/`.sav`; it does not prove emulator save state is absent elsewhere
   - Saved dispositions are bound to a fingerprint of the exact immutable ROM plan and discovered save evidence so a later execution-plan boundary can fail closed if the review becomes stale
   - After a complete review, **Preview Final Execution Plan...** re-discovers save evidence, rechecks the live Collection revision, SHA-256 verifies every approved ROM, and hashes every colocated save selected for migration before freezing the exact ROM/save source → target operations
   - The final preview retains explicit saves that will be left in place and excludes ROM moves blocked during review; use **Apply Organization...** only after reviewing those exact final operations
   - Apply rechecks the Collection revision, exact ROM/save hashes/sizes/mtimes, target absence, and the colocated `.srm`/`.sav` set. A new or changed companion save makes the plan stale instead of being ignored
   - Organization uses a journaled copy → Collection commit → old-source cleanup sequence. Targets are created exclusively and never overwrite existing files; pre-commit failures roll back target copies and Collection state
   - After the commit marker, Collection points at the verified targets and recovery only finishes deleting the reviewed old sources. Startup detects an interrupted organization journal and requires explicit confirmation that every other application instance is closed before recovery
   - Retained ROMs whose per-file SMWC provenance belongs to a different submission are intentionally review-only rather than inheriting the current record's catalogue layout
   - For those retained modern assets, **Review Historical Provenance...** fetches metadata only for the explicitly recorded historical SMWC IDs and previews the type/difficulty layout derived from each ROM's own submission
   - Review rows marked **Ready for plan** can continue to **Preview Historical Move Plan...**, which revalidates the exact Collection revision, modern asset ownership/provenance, target vacancy, regular non-symlink source state, stable filesystem identity, byte size, and SHA-256 before freezing a read-only historical move plan
   - After explicit save dispositions, **Preview Final Execution Plan...** re-discovers the exact save evidence, revalidates ROM bytes/targets, hashes migrated saves, and freezes a final historical ROM/save execution preview while still exposing no Apply action
   - Historical move plans can then **Review Save Dispositions...** through the same conservative save-impact workflow as ordinary plans. The review uses the already-frozen historical targets and binds decisions to the exact historical SMWC ID/layout metadata plus ROM byte preconditions; final execution planning and filesystem Apply are still deliberately unavailable for historical plans
   - Numeric modern ROMs with missing provenance and legacy `file_path`-only entries are also review-only; the app does not invent migration semantics for them
   - Only colocated saves explicitly marked **Migrate with ROM** become filesystem operations. **Leave in place** saves and configured/associated Save Sync evidence are not moved or rewritten

![Collection Page](images/application-5.0-collection.png)

- [Collection Wheel guide](docs/COLLECTION_WHEEL.md) — filters, Planner refinements, ratings, spins, and safety boundaries
- [Browser / OBS Wheel guide](docs/WHEEL_BROWSER_RUNTIME.md) — OBS setup, runtime lifecycle, API routes, security, and troubleshooting

#### Input Format Guide

When editing **Completed Date** and **Time to Beat** fields, the app supports flexible input formats:

**📅 Date Formats:**
- `MM/DD/YYYY` - Example: `12/25/2024`
- `MM-DD-YYYY` - Example: `12-25-2024`
- `MM.DD.YYYY` - Example: `12.25.2024`
- `YYYY/MM/DD` - Example: `2024/12/25`
- `YYYY-MM-DD` - Example: `2024-12-25`

**⏱️ Time to Beat Formats:**

| Format Type | Pattern | Examples | Description |
|-------------|---------|----------|-------------|
| **Colon-Separated** | `HH:MM:SS` | `1:30:45`, `12:05:30` | Hours:Minutes:Seconds |
| | `MM:SS` | `90:30`, `5:15` | Minutes:Seconds |
| **Letter Suffix** | `XhYmZs` | `2h 30m 15s`, `1h 45m`, `90m`, `45s` | Hours/minutes/seconds with letters |
| | *Flexible spacing* | `2h30m15s` = `2h 30m 15s` | Spaces optional |
| **Day Formats** | `XdYhZmWs` | `14d 10h 2m 1s`, `7d 12h`, `2d` | Days/hours/minutes/seconds |
| | *Shortened* | `14d 10` (assumes hours) | Advanced shorthand |
| **Word-Based** | `X minutes/mins` | `150 minutes`, `90 mins` | Full word formats |
| **Simple Number** | `X` | `90`, `5`, `120` | Just a number (assumes minutes) |

### App Settings
- **Download location**: Change where ROMs are saved
- **Multi-type downloads**: Configure how hacks with multiple types (like "Kaizo, Tool-Assisted") are handled
  - **Primary only**: Download to the main type folder only
  - **Copy to all folders**: Create copies in each applicable type folder
- **Emulator integration**: Configure your favorite emulator to launch games directly from the Collection page
  - Supports RetroArch, Snes9x, and any other emulator
  - Custom command-line arguments with `%1` placeholder support
  - Cross-platform: Windows, macOS (.app bundles), and Linux
  - **Version picker**: For hacks with multiple versions, ▶ launches the default by default. Enable "When launching a hack with multiple versions, show a version picker" to always be prompted
- **Data Migration**: Keep your collection metadata up-to-date
  - **Check Difficulties**: Detect outdated difficulty categories from SMWC renames
  - **Apply Fixes**: Automatically migrate folders and update metadata
  - **Fetch Metadata**: Bulk update missing release dates for your entire collection
    - Optimized bulk API (completes in under 1 minute for most collections)
    - Finds metadata for obsolete/unlisted hacks via fallback lookups
    - Cancellable operation (safe to cancel during fetch phase)
- **Auto-updates**: Available for stable/release builds. Development candidates display disabled update controls and must be replaced manually
- **Theme**: Switch between light and dark modes with instant, smooth transitions and optimized performance
- **API Delay Slider**: Set delay from 0.0 to 3.0 seconds between API requests to avoid rate limiting issues

![Settings Page](images/application-5.0-settings.png)

### Emulator Configuration

The app supports launching ROMs directly in your favorite emulator with one click!

#### Setup Instructions

1. **Go to Settings** → **Emulator Configuration**
2. **Browse for your emulator executable**:
   - **Windows**: Select the `.exe` file (e.g., `snes9x-x64.exe`, `retroarch.exe`)
   - **macOS**: Select the `.app` bundle (e.g., `Snes9x.app`) - the app will automatically find the executable inside
   - **Linux**: Select the binary (e.g., `/usr/bin/snes9x-gtk`, `/usr/games/retroarch`)
3. **Optional: Add command-line arguments**
   - Check "Use Custom Command Line Arguments"
   - Enter your desired arguments (see examples below)
4. **Save and test**: The play icon (▶) will appear next to downloaded hacks in your Collection

#### Command-Line Arguments Examples

**RetroArch (Windows):**
```
-L cores/snes9x_libretro.dll "%1"
```

**RetroArch (macOS):**
- Emulator Path: `/Applications/RetroArch.app/Contents/MacOS/RetroArch`
- Command Line Arguments:
```
-L "~/Library/Application Support/RetroArch/cores/snes9x_libretro.dylib" "%1"
```

**RetroArch (Linux):**
```
-L ~/.config/retroarch/cores/snes9x_libretro.so "%1"
```

**Snes9x:**
```
--fullscreen
```

**Custom Arguments:**
- Use `%1` as a placeholder for the ROM file path
- If you don't use `%1`, the ROM will be automatically added at the end
- Arguments are parsed with proper quote handling

#### Platform-Specific Notes

**Windows:**
- Browse for `.exe` files
- Emulator runs without console window

**macOS:**
- Browse for `.app` bundles (e.g., `Snes9x.app`, `RetroArch.app`)
- The app automatically converts `.app` paths to the actual executable inside
- Example: `Snes9x.app` → `Snes9x.app/Contents/MacOS/Snes9x`

**Linux:**
- Browse for binaries in `/usr/bin/`, `/usr/games/`, or custom locations
- Make sure the binary has execute permissions
- Folder picker dialogs use the native system chooser (GTK/KDE portal) instead of the built-in Tk widget, giving you a proper vertical-scroll file browser on both X11 and Wayland

## 🛠️ Troubleshooting

### Windows Security Warning
Windows may show "Windows protected your PC" when running the app. This is normal for new applications. Click "More info" → "Run anyway" to continue.

### Mac Security Warning
macOS may say the app is from an "unidentified developer." Right-click the app → "Open" → "Open" to bypass this. You only need to do this once.

### Linux: App Won't Start
If the app won't launch, install these packages:
- **Ubuntu/Debian**: `sudo apt install python3-tk`
- **Fedora**: `sudo dnf install tkinter`

### Can't Find Downloaded ROMs
Check the folder path shown in Settings. By default, ROMs are saved to:
- **Windows**: `Desktop\SMWCentral Hacks\`
- **Mac**: `Desktop/SMWCentral Hacks/`
- **Linux**: `~/Desktop/SMWCentral Hacks/`

### Emulator Won't Launch
If clicking the play icon doesn't work:
1. **Check emulator path**: Go to Settings → Emulator Configuration and verify the path is correct
2. **macOS users**: Make sure you selected the `.app` file, not the executable inside
3. **Check arguments**: Disable "Use Custom Command Line Arguments" to test without arguments first
4. **Test manually**: Try launching your emulator with a ROM file manually to ensure it works
5. **Check logs**: Go to Settings page and check the log output for error messages

## 📝 What You Need

- **Your Operating System**: Windows 10+, macOS 10.15+, or modern Linux
- **A clean SMW ROM**: Unmodified Super Mario World ROM file (.smc or .sfc)
- **Storage space**: About 20 MB for the app, plus space for your ROM collection
- **Internet connection**: Required for downloading hacks; stable releases may also use it for update checks
- **Optional - Emulator**: Any SNES emulator (Snes9x, RetroArch, bsnes, etc.) for the quick-launch feature

##  Changelog

</details>

<details open>
<summary><strong>Version 5.0 - Latest Release (March 2026)</strong></summary>

### 🆕 New Features

**Multi-BPS File Support**
- **Download multiple patch versions at once**: When a hack ZIP contains more than one BPS file, you're now shown a selection dialog before patching begins
  - Check/uncheck each file to include or exclude it
  - Pick which version is the "Default" — it opens automatically when you click play from your Collection
  - Output filenames are auto-suggested from the BPS filename with proper title-casing (e.g. `Hack Name v1.10`)
  - All selected files are patched and saved; your Collection tracks all of them

**ROM Files in Edit Hack Dialog**
- **Inspect modern Collection ROM assets**: Any entry with modern `files[]` data—downloaded SMWC entries or local/manual imports—shows a "ROM Files" section
  - Shows each recorded ROM's path, on-disk availability, size, abbreviated SHA-256, acquisition source, and per-ROM SMWC submission provenance when known
  - For multi-ROM entries, select a new primary via radio button and click Update; `files[].primary` and compatibility `file_path` are updated together
  - Changing the primary never moves, renames, deletes, or re-hashes ROM files
  - Local/manual entries with modern `files[]` use that asset list as the source of truth instead of exposing a second editable `file_path` that could drift out of sync

**Multi-ROM Picker**
- **Smart launch behavior**: Clicking the play icon (▶) on a hack with multiple versions immediately opens the default version — no extra clicks needed
- **Optional picker dialog**: Enable "Show version picker" in Settings → Emulator Configuration to get a selection dialog instead
  - Redesigned to match the multi-BPS download dialog: radio buttons, separators, and a clean spacious layout
  - Pre-selects the current default (★) so you can just hit Enter to launch it
- **Change the default any time**: Open the Edit Hack dialog → ROM Files section, select a different radio, and save

### 🐛 Bug Fixes
- **Emulator play icon not appearing after setup**: Configuring an emulator path in Settings now immediately refreshes the play icon column in the Collection — no restart needed

### 🔧 Improvements
- **Smarter title-casing**: ROM filenames are cleaned up more accurately
  - Version tokens like `v1.10` and `v2.0` always stay lowercase
  - Parenthetical words like `(Not`, `(Super)` are capitalised correctly
  - `not` is now treated as a lowercase article; `so` capitalises normally

</details>

<details>
<summary><strong>Version 4.9 - Previous Release (January 2026)</strong></summary>

### 🆕 New Features

**Column Configuration**
- **Customizable Collection View**: Show/hide columns and reorder them via intuitive drag-and-drop
  - Click "⚙ Columns" button above the Collection table to configure
  - Visual feedback shows column name while dragging
  - Check/uncheck boxes to control column visibility
  - "Reset to Default" restores original layout
  - Preferences persist across app sessions

**Fetch Metadata - Supercharged**
- **Bulk Metadata Updates**: Update missing release dates for your entire collection from SMWCentral
  - **60-100x faster** than previous versions (under 1 minute vs 30+ minutes)
  - Uses optimized bulk API fetching for active hacks
  - Fallback individual lookups for obsolete/unlisted hacks
  - Checks both moderated AND waiting sections
  - **Cancellable operation** - safe to cancel during API fetch phase
  - Access via Settings → Data Migration → "Fetch Metadata"

**Delete Any Hack**
- **Expanded deletion support**: The Delete button in the edit dialog now works for all hacks, not just manually added ones
  - Permanently removes the entry from your collection history
  - If a ROM file is linked to the hack, it is also deleted from your file system
  - Confirmation prompt clearly states whether a file will be deleted
  - Handles orphaned records (JSON entry exists but file is already gone) gracefully

**Linux Native Folder Picker**
- **Better folder selection on Linux**: Folder browse dialogs now use the native system picker instead of Tk's built-in horizontal-scroll widget
  - Automatically uses `zenity` (GNOME/GTK) or `kdialog` (KDE) via XDG Desktop Portals
  - Works correctly on both X11 and Wayland
  - Falls back silently to the Tk dialog if neither tool is available
  - No impact on Windows or macOS behaviour

**UI Consistency & Polish**
- **Themed Status Colors**: Consistent, readable colors across all status messages
  - Info/In-Progress: Light cyan (`#4FC3F7`) - much more visible than previous blue
  - Success: Green (`#66BB6A`)
  - Warning: Orange (`#FFA726`)
  - Error: Red (`#EF5350`)
  - Centralized theme constants in `ui_constants.py`

**Data Protection**
- **Collection Page Locking**: Prevents editing during background operations
  - Locks during: Fetch Metadata, Difficulty Migrations, Silent Updates
  - Shows "⏸️ Collection locked" message with operation reason
  - Auto-unlocks when operation completes, fails, or is cancelled

### 🔧 Improvements
- **Cleaner Logging**: Simplified messages prevent UI clutter
  - "🔄 Reloaded X hacks from disk" (removed debug paths)
  - Shortened migration messages to prevent layout overflow
- **Layout Optimizations**: Data Migration text wrapping adjusted to prevent cutoff
- **Metadata Dialog**: Updated to reflect bulk optimization and cancellation features

### 🐛 Bug Fixes
- **Column Configuration**: Fixed TclError crashes during drag-and-drop
  - Added widget existence checks before updates
  - Robust error handling prevents UI freezes
- **Column Sort After Reorder**: Fixed data jumbling when sorting after reordering columns
  - Reordering columns (e.g. moving the ✓ Completed column) and then sorting by any header no longer scrambles row data
  - Sort indicators and click commands now correctly reflect the actual displayed column order
- **Reset to Default**: Fixed button not working (config validation issue)
- **Duplicate Logging**: Fixed "Reloaded X hacks" appearing twice on Refresh
- **Obsolete Hacks**: Fixed metadata fetch not updating old/replaced hack versions
  - Now uses individual API lookups as fallback
  - Warns about hacks that couldn't be updated

</details>

<details>
<summary><strong>Version 4.8</strong></summary>

### 🆕 New Features
- **Emulator Integration**: Launch ROMs directly from the Collection page with one click
  - Configure any emulator (RetroArch, Snes9x, bsnes, etc.)
  - Custom command-line arguments with `%1` placeholder support
  - Cross-platform support: Windows, macOS (.app bundles), and Linux
  - Play icon (▶) appears next to downloaded hacks when emulator is configured
- **macOS .app Bundle Support**: Automatic conversion of `.app` bundles to executable paths
  - Select `Snes9x.app` and the app automatically finds `Snes9x.app/Contents/MacOS/Snes9x`
  - Works with all standard macOS application bundles
- **Live Difficulty Mapping from SMWC API**: Automatically fetches current difficulty categories from SMWC on app startup
  - Difficulty mappings cached in config.json for offline use
  - Ensures app always uses latest SMWC difficulty names without code updates
- **Difficulty Migration System**: Automatic detection and migration of SMWC difficulty category renames
  - Auto-detects when difficulty names have changed by comparing against live SMWC data
  - Migration UI in Settings page with check/apply buttons
  - Automatically renames difficulty folders and updates file paths
- **Automatic v4.8 Migration**: Seamless upgrade from v4.7
  - Automatically adds new fields to existing hacks on first launch
  - Silent migration - no user intervention needed

### 🔧 Improvements
- Settings page layout optimized: Emulator and Difficulty Migration sections now side-by-side for better space utilization
- Enhanced log section with more vertical space
- Improved cross-platform emulator path handling
- Updated difficulty category from "Skilled" to "Intermediate" to match SMWC
- Collection page Type filter now correctly finds multi-type hacks
- Difficulty data model consolidated for better performance

### 🐛 Bug Fixes
- Fixed Type filter not finding multi-type hacks (e.g., searching "Puzzle" now finds "Standard, Puzzle")
- Fixed Collection page difficulty filter with new data model
- Removed false migration warnings

</details>

<details>
<summary><strong>Previous Versions</strong></summary>

### v4.7.0

### 🔧 Improvements
- **Enhanced Download Selection**: Click anywhere on a search result row to select/deselect hacks for download
- **Improved Filter Layout**: Responsive filter sections work better when window is maximized
- **Clearer Filter Controls**: Renamed "Search Criteria" to "Show/Hide Filters" for better clarity


### v4.6.0

### 🐛 Bug Fixes
- **Time Parsing Accuracy**: Fixed critical bug where time inputs like "27m 22s" were incorrectly parsed as "2h 7m 22s"
- **Input Format Reliability**: Improved regex pattern matching order to handle all time formats correctly
- **Data Integrity**: Ensures accurate time-to-beat tracking in Collection page

### 🔧 Improvements
- **Auto-Refresh on Navigation**: Dashboard and Collection pages now automatically refresh data when navigating between tabs
- **Enhanced Input Validation**: Better handling of edge cases in time parsing (supports days, overflow values, etc.)

### v4.5.0

### 🚀 New Features
- **Progressive Data Loading**: Results display as each page loads from the API for instant review
- **Already Downloaded Indicator**: Downloaded hacks shown in italic with muted colors
- **Smart Collection Filtering**: "Show only non-downloaded hacks" checkbox for faster browsing
- **Enhanced Theme System**: Improved color management and visual consistency
- **Performance Optimizations**: Faster theme updates and UI responsiveness

### 🔧 Improvements
- **Search Experience**: Browse results immediately as data loads
- **Collection Management**: Better visual distinction and filtering for owned content
- **Theme Performance**: Optimized color updates across light and dark modes
- **UI Polish**: Consistent visual elements during theme transitions

### 🐛 Bug Fixes
- Fixed dark gray selection colors appearing in light mode
- Resolved delays in theme color updates for downloaded indicators
- Fixed visual inconsistencies during theme switching

### v4.5.0

### 🚀 New Features
- **Progressive Data Loading**: Results display as each page loads from the API for instant review
- **Already Downloaded Indicator**: Downloaded hacks shown in italic with muted colors
- **Smart Collection Filtering**: "Show only non-downloaded hacks" checkbox for faster browsing
- **Enhanced Theme System**: Improved color management and visual consistency
- **Performance Optimizations**: Faster theme updates and UI responsiveness

### 🔧 Improvements
- **Search Experience**: Browse results immediately as data loads
- **Collection Management**: Better visual distinction and filtering for owned content
- **Theme Performance**: Optimized color updates across light and dark modes
- **UI Polish**: Consistent visual elements during theme transitions

### 🐛 Bug Fixes
- Fixed dark gray selection colors appearing in light mode
- Resolved delays in theme color updates for downloaded indicators
- Fixed visual inconsistencies during theme switching

</details>

<details>
<summary><strong>Previous Versions</strong></summary>

### v4.4.0
- **Cross-Platform Support**: Full compatibility with Windows, macOS, and Linux
- **Download State Management**: Collection tab is now locked during active downloads to prevent data corruption
- **Enhanced Dashboard Analytics**: Improved accuracy and data tracking for collection metrics

### v4.3.0
- Dashboard implementation with analytics and charts
- Collection page with comprehensive filtering and editing
- Theme support (light/dark modes)
- Improved bulk download workflow

### v4.2.0
- Multi-type download support
- Enhanced search and filtering capabilities
- Progress tracking improvements
- Bug fixes and stability improvements

### v4.1.0
- Initial release with core downloading functionality
- Basic patching system
- Simple collection tracking
- Windows-only support

</details>

---

**Made for the Super Mario World ROM hacking community** ❤️

<!-- planner-guide:start -->
## 🗂️ Planner

The Planner organizes collection entries with independent lifecycle statuses,
**Someday / Soon / Next** planning horizons, an ordered Next queue, and
multi-membership custom lists. Search and filters can be combined to focus the
backlog without storing a fixed Low/Normal/High priority.

Planner can be hidden from **Settings → Optional Features** without
deleting its saved state. Edits are staged until **Save Changes** is pressed,
and Planner state is stored
separately from `processed.json`. Existing completed collection entries remain
visible as Completed without requiring an automatic migration.

See [PLANNER.md](PLANNER.md) for the complete workflow, persistence contract,
filter behavior, compatibility rules, and the intended filter-driven Wheel
design.
<!-- planner-guide:end -->

<!-- save-data-sync-guide:start -->
## 💾 Save Data Sync

Save Data Sync can review `.srm` and `.sav` battery saves from multiple
configured folders, inspect checksum-valid SMW slots and conservative fallback
evidence, match saves to collection entries, and prepare completion updates.

Manual SMWCentral selection, remembered filename associations, review-only
startup or periodic scans, privacy-safe diagnostics, and local entries for
non-SMWCentral hacks are supported. Save files are never modified, and no
collection change is made until **Apply Selected** is pressed.

See [SAVE_DATA_SYNC.md](SAVE_DATA_SYNC.md) for the complete workflow, safety
rules, confidence model, privacy contract, and known limitations.
<!-- save-data-sync-guide:end -->
