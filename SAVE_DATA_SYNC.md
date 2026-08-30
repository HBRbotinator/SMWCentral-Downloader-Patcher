# Save Data Sync

Save Data Sync reviews SNES battery-save files and proposes collection changes.
It never modifies `.srm` or `.sav` files, and no collection change is committed
until the user presses **Apply Selected**.

## Supported save sources

Configure one or more emulator or console save folders in Settings.

- Supported extensions are `.srm` and `.sav`, case-insensitively.
- Each configured folder is scanned non-recursively.
- Repeated folder entries and repeated paths to the same physical file are
  deduplicated.
- When several saves match the same collection entry, the strongest candidate
  wins: higher detected progress first, then newer modification time.
- Removing a configured source removes only the setting. It never deletes the
  folder or any save files.
- Unavailable folders remain configured. Manual scans require confirmation
  before they are skipped; automatic scans skip them without blocking startup.

The former single `save_sync_dir` setting is migrated into the ordered
`save_sync_dirs` list and retained as a compatibility mirror of the first
configured source.

## Save analysis and confidence

The scanner records structured evidence rather than treating one byte as
universally authoritative.

### Checksum-valid standard SMW slots

All three ordinary SMW slots and their primary and backup copies are inspected.
A usable standard record must satisfy the expected checksum contract. When
copies disagree, the evidence records which copy and counter were selected.

Checksum-valid standard slot evidence is classified as medium confidence
because the overworld-event counter used by many hacks does not necessarily
equal the advertised exit count.

### Legacy raw counters

A legacy counter may remain available as low-confidence evidence when no
stronger profile is proven. Repeated `0x60` empty-slot patterns and
uninitialized values are rejected instead of being treated as progress.

### Expanded or custom SRAM

A larger save container is not proof that the inherited counter has the same
meaning. An expanded save without a validated compatible layout fails closed:
the raw counter is retained only as evidence and the candidate remains
uncertain.

Some expanded SA-1/BW-RAM images contain a standard SMW save block in a later
8 KiB-aligned bank. Such a relocated block is accepted only when matching
checksum-valid primary and backup copies prove one unambiguous slot value. It
remains medium-confidence evidence and is reported with profile
`relocated_standard_smw_slots`.

The scanner does not guess custom layouts from filenames or hack titles.

### Confidence in the review window

Both review tabs show a **Confidence** column and a selected-row evidence
summary. The values mean:

- **Medium** — checksum-validated standard structure, including a safely proven
  relocated block;
- **Low** — a plausible but unvalidated legacy raw counter;
- **None** — no trusted progress value was established.

Medium is currently the highest automatic grade because a checksum-valid
overworld-event counter still may not equal the hack's advertised exit total.

Low-confidence completion candidates remain reviewable but are not checked by
default. The user must select them explicitly before **Apply Selected**.

## Candidate states

A scanned save can be shown as:

- **Completed** when detected progress meets the known exit total, or when the
  user enabled the explicit mark-all option.
- **In progress** when usable progress is below a known total.
- **Uncertain** when the save is readable but its progress or exit relationship
  is not proven.
- **Unmatched** when no collection entry or explicit resolution is available.
- **Already completed** when the collection entry was completed before the
  scan; existing completion data is preserved.

The save modification date may supply a completion date when a newly applied
completion has a usable timestamp. Existing completion dates are not
overwritten, and SNES saves do not provide a reliable play-time value.

## Matching existing collection entries

Normal collection matching uses conservative normalized title and known local
ROM-path forms. Automatic orphan resolution uses the same calibrated
`CatalogueMatcher` as Collection ROM ingestion: Exact/Strong matches may resolve
automatically, while abbreviations, partial titles, ambiguous candidates, and
other guarded fuzzy matches remain explicit review suggestions. Matcher
thresholds are not relaxed for Save Sync.

Save Data Sync uses the KaizOFF public catalogue as its primary SMWC data
provider. **Look up checked on SMWC** loads one cached KaizOFF Index snapshot
for the review, runs the calibrated matcher locally, and fetches rich KaizOFF
metadata only for safe automatic resolutions. Review-only suggestions use Index
metadata and do not trigger rich per-ID requests until the user explicitly
selects a result. The checked-row batch never fans out into direct SMWCentral
API searches if KaizOFF is unavailable; this avoids exhausting SMWC's
comparatively small rate limit.

An explicit manual search also uses the shared KaizOFF Index first. Direct
SMWCentral API search is retained only as a logged fallback when KaizOFF cannot
provide the catalogue or the selected submission detail. This fallback is tied
to the user's single manual request rather than repeated automatically for all
unmatched saves. User-facing SMWC terminology refers to the canonical SMWC
submission identity even when KaizOFF supplies the catalogue data.

The wider application follows the same provider policy: KaizOFF Index is preferred for
sparse discovery, KaizOFF per-ID detail for resolved hacks, and KaizOFF's paginated full-record catalogue for rich bulk workloads. Direct SMWC catalogue reads
remain fallback/exception paths rather than the normal source.

Local save-backed entries are intentionally excluded from ordinary automatic
title and ROM-path matching. Their explicit saved filename association remains
authoritative, which allows the association to be forgotten later.

## Manual SMWCentral search

For one unresolved or review-suggested save:

1. Select the save on the unresolved/import tab. Review-suggested rows show the
   top candidate and matcher confidence but are never checked automatically.
2. Choose **Search Selected...**.
3. Enter a free-text query if the filename-derived query needs adjustment.
4. Review ranked catalogue results and whether each SMWC ID is already in the
   collection. When a checked lookup produced a review suggestion, that SMWC ID
   is preselected if it is present in the manual result set. KaizOFF Index rows
   may show a neutral **Catalogue** release state until the selected ID is hydrated.
5. Explicitly choose **Use Selected**.
6. Keep the row checked and press **Apply Selected**.

Opening or confirming the search result does not write collection data.
SMWCentral-backed imports use the canonical SMWCentral ID so later downloads
merge with the same collection entry.

## Saved filename associations

An explicit manual selection can be remembered as:

```text
normalized save filename -> canonical collection ID
```

Only the normalized filename stem and collection ID are stored. Absolute paths,
parent directories, and save contents are not part of the association.

A later scan displays the match as **Saved** and diagnostic source
`saved_alias`.

**Forget Saved Match** removes only the association. It does not delete:

- the save file;
- a ROM file;
- the collection entry;
- completion status, date, notes, or rating.

After forgetting and rescanning, a shorthand filename such as `QW2.srm`
normally returns to the unresolved tab unless another independent matching rule
applies.

Associations whose target no longer exists are pruned safely.

## Local save-backed entries

A save for a hack outside SMWCentral can create an explicit local collection
entry.

1. Select one unresolved save.
2. Choose **Create Local Entry...**.
3. Enter a collection title and total exit count.
4. Confirm the prepared resolution.
5. Press **Apply Selected**.

The entry is marked internally with `local_save_entry: true` and receives the
same opaque local Collection identity used by other ingestion sources:
`usr_<16 lowercase hex characters>`. The ID is randomly allocated and is not
derived from the save filename, entered title, ROM hash, or absolute path.

A total of `0` means unknown and keeps the progress uncertain.

On later scans the explicit saved association is used. The Completion tab can:

- edit the local title or exit total while preserving the stable ID and other
  collection metadata;
- forget only the saved association;
- remove the local collection record and every association targeting it.

Removing a local entry never deletes save or ROM files. These lifecycle actions
are not available for normal SMWCentral-backed entries.

## Startup and periodic review scans

Background review is disabled by default.

### Startup scan

The optional startup scan runs once after the application and collection
manager initialize.

### Periodic scan

The optional periodic scan supports fixed intervals of 5, 15, 30, or 60
minutes while the application remains open. The default selected interval is
15 minutes, but periodic scanning remains disabled until enabled explicitly.

Both modes:

- use the configured available save sources;
- run without startup prompts;
- never write collection data;
- never open the review dialog automatically;
- retain only completion candidates and unmatched saves for attention;
- defer when another automatic scan is running or an earlier automatic review
  is still pending.

The user must open **Review Auto-Scan...** and press **Apply Selected** before
anything is committed. In-progress, uncertain, and already-completed matched
saves remain available through a normal manual scan but do not create an
automatic review notification.

## Apply Selected safety boundary

All collection writes remain behind one explicit boundary.

- Only checked candidates are applied.
- Preparing a manual SMWCentral or local resolution does not apply it.
- Existing completed entries are not downgraded.
- Unresolved candidates cannot be imported.
- Save files are opened read-only and never rewritten.
- Removing a source, association, or local entry never deletes save files.

## Privacy-safe diagnostics

The review dialog can export a JSON diagnostic report. Diagnostic schema
version 4 includes:

- file name, extension, size, and modification date;
- selected parser profile, slot/copy, confidence, warnings, and validation
  evidence;
- effective match and resolution source;
- counts for direct matches, SMWCentral resolutions, saved associations, local
  custom resolutions, and unresolved candidates.

By default the report excludes:

- absolute paths;
- parent-directory names;
- raw save bytes.

A first-time local resolution is reported as `local_custom`. A later scan using
its remembered association is reported as `saved_alias`.

## Known limitations

- The standard SMW overworld-event counter is not guaranteed to equal exits for
  every hack.
- Unknown expanded/custom layouts remain uncertain until a structural profile
  proves their meaning.
- Folder discovery is non-recursive.
- Automatic scans are interval-based polling, not filesystem watchers.
- Save Data Sync does not derive reliable play time from SNES battery saves.

These limitations are deliberate fail-closed behavior rather than reasons to
guess or silently alter collection state.
