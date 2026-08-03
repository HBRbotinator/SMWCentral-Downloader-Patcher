# Collection Wheel

The native Collection Wheel is available from **Collection → Open Wheel**. It
selects one hack from a detached, read-only candidate pool.

## Collection ownership

The Wheel starts from the complete Collection rather than inheriting the
Collection page's active filters. It then applies its own filters inside the
Wheel dialog.

Obsolete versions are excluded from the active pool. Local and save-backed
Collection entries remain eligible when they satisfy the selected filters.

## Collection filters

The Wheel provides independent filters for:

- Search
- Completion
- Type
- Difficulty
- Download status
- SMWC rating
- Released from
- Released through

The filters compose with each other, and the candidate count updates
immediately.

Completion is independent from Planner lifecycle.

SMWC Rating is the synchronized SMW Central community rating. It is separate
from the user's editable Personal Rating stars. Rating thresholds are inclusive,
so 4.0+ includes hacks rated exactly 4.0. Missing, invalid, local-only, and zero
ratings are shown as Unrated.

Released from and Released through are inclusive. Unknown release years remain
eligible while both choices are Any, but are excluded while a year bound is
active.

## Optional Planner refinements

When explicit Planner entries or custom lists exist, the Wheel also displays:

- Lifecycle
- Planning horizon
- Custom list

These refinements are hidden as a group when Planner data is unavailable. The
Wheel remains usable with Collection filters alone.

Custom lists are Planner-owned and are stored with Planner state.

## Spinning

**Spin Wheel** selects from the complete filtered candidate pool.

Every candidate has an equal segment and an equal chance of selection. Large
pools limit visible text labels for readability, but unlabeled candidates remain
represented and equally eligible.

The native graphical Wheel uses a non-blocking decelerating animation and lands
with the selected segment beneath the pointer. The result is revealed only after
the animation finishes.

## Spin Again

**Spin Again** performs a one-call reroll that excludes only the current result.
It does not permanently remove that hack from later spins. When only one
candidate is eligible, Spin Again is unavailable.

## Collection result focus

After the spin completes, the selected hack is focused in Collection.

Wheel filters are independent from Collection page filters. When the selected
hack is hidden by the Collection table, the page clears its own filters, moves
to the correct pagination page, and focuses the result.

## Rating metadata

Collection distinguishes:

- **Personal Rating**: editable user-assigned stars.
- **SMWC Rating**: read-only community metadata synchronized from SMW Central.

**Settings → Fetch Missing Metadata** can backfill SMWC ratings for existing
SMWC-backed Collection entries. Local and save-backed entries remain Unrated
unless they have canonical SMWC metadata.

## Safety and persistence

Wheel operations are read-only:

- No per-hack Wheel eligibility flag is stored.
- Filters are not written into Collection records.
- Spin results are not persisted.
- Planner entries and lists are not modified.
- Personal Rating and SMWC Rating are never mixed.
- Candidate snapshots are detached from mutable Collection records.

## Current implementation boundary

The shipped Collection Wheel is the native desktop implementation rendered with
Tk Canvas.

The following are planned as a separate browser-runtime stage and are not part
of the native Wheel feature:

- OBS browser-source overlay
- HTML5/CSS3/JavaScript renderer
- Local HTTP or WebSocket API
- Streamer.bot triggers
- Standalone or tray-hosted Wheel service
- Browser Wheel operation while the main Downloader is closed

The planned browser runtime should reuse the same Collection, Planner, filter,
and winner-selection rules. Python remains the source of truth for the selected
candidate; the browser renderer should animate the predetermined result rather
than choose independently.
