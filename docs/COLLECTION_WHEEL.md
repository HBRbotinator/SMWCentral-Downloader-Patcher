# Collection Wheel

The Collection Wheel is available from **Collection → Open Wheel**. It selects
one hack from a detached, read-only candidate pool.

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

## Native spinning

**Spin Wheel** selects from the complete filtered candidate pool.

Every candidate has an equal segment and an equal chance of selection. Large
pools limit visible text labels for readability, but unlabeled candidates remain
represented and equally eligible.

The native graphical Wheel uses a non-blocking decelerating animation and lands
with the selected segment beneath the pointer. The result is revealed only after
the animation finishes.

When the Browser Wheel is stopped, the native Wheel keeps its quick desktop
animation: five turns, 61 frames, and approximately 1.68 seconds.

When the managed Browser Wheel is running, the native Wheel switches to the
shared presentation schedule: 5.5 seconds, nine turns, and the same continuous
acceleration and deceleration curve used by the browser. Python supplies one
weighted landing offset for the spin, and both renderers use that exact offset.
They therefore reveal the same winner at the same position within its segment.

The browser observes the published instruction through its local read-only
endpoint, so its visible start can differ by part of the polling interval. The
renderers are presentation-synchronized but are not guaranteed to match on
every rendered frame.

## Spin Again

**Spin Again** performs a one-call reroll that excludes only the current result.
It does not permanently remove that hack from later spins. When only one
candidate is eligible, Spin Again is unavailable.

## Browser / OBS Wheel

The dialog also provides a managed **Browser / OBS Wheel** section.

**Start Browser Wheel** starts a loopback-only runtime using the exact current
filtered pool. The displayed OBS Browser Source URL is copied to the clipboard
when possible. **Copy OBS URL** copies it again, and **Stop** shuts down the
dialog-owned runtime.

While the runtime is active:

- filter changes publish the exact new eligible pool;
- Spin Wheel publishes the same pool used by native selection;
- Spin Again publishes the exact reroll pool after excluding the current result;
- Python selects the winner once;
- Python supplies one weighted landing offset for both renderers;
- the browser receives and animates that predetermined winner;
- the native Wheel uses the same 5.5-second schedule while the runtime runs;
- both Wheels land on the same position inside the winner segment;
- browser publication failure does not replace or invalidate the native result.

Closing the Collection Wheel dialog stops its managed browser runtime.

### Preview and OBS overlay modes

The runtime exposes two visual modes from the same local page:

- `/wheel/` is the full preview and diagnostics view.
- `/wheel/?mode=overlay` is the transparent OBS presentation.

The dialog displays and copies the overlay URL. In overlay mode, the title,
status badge, footer, card background, border, and preview text are omitted.

The overlay stays fully hidden while idle. A newly published spin reveals the
wheel, the winner remains visible for eight seconds, and the complete overlay
then returns to a transparent hidden state.

### Browser spin presentation

The Browser / OBS Wheel uses the show-oriented schedule. While its managed
runtime is running, the native Wheel uses this same schedule:

- 5.5 seconds total;
- nine full turns;
- one continuous frame-driven motion curve;
- smooth acceleration through the first 10%;
- a high-speed middle through 27%;
- continuous deceleration over the final 73%;
- a smooth zero-speed finish without a staged transition or braking handoff.

Python chooses one safe visual landing offset inside the predetermined winner's
segment from nine weighted bands. The early and late sides each receive 47% of
the probability, while the center receives 6%. Hairline bands from 0.025 to
0.055 and from 0.945 to 0.975 allow the pointer to creep just inside the selected
segment or stop just before the following segment while preserving a visible
margin.

Segment labels are oriented radially and flip by 180 degrees when their current
screen angle would otherwise make them upside down.

The winner presentation displays the complete title. Long titles wrap and use
responsive size tiers instead of ellipsis. The result card, title, winning
segment, and winning label receive an extended celebration before the overlay
hides. Spark count, angle, distance, delay, hue, and scale, together with card
tilt and ring expansion, vary between spins. That variation is derived from the
immutable Python-authored spin identity, is repeatable for the same instruction,
and cannot influence filtering or winner selection.

See the [Browser / OBS Wheel guide](WHEEL_BROWSER_RUNTIME.md) for setup,
architecture, API routes, security boundaries, and troubleshooting.

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

Wheel operations remain read-only with respect to Collection and Planner data:

- No per-hack Wheel eligibility flag is stored.
- Filters are not written into Collection records.
- Spin results are not persisted.
- Planner entries and lists are not modified.
- Personal Rating and SMWC Rating are never mixed.
- Candidate snapshots are detached from mutable Collection records.
- Local ROM paths, save paths, download URLs, notes, and raw metadata are not
  exposed through the browser runtime.
- Browser clients cannot select a winner or send a spin command.

## Current implementation boundary

Two renderers are available while the Collection Wheel dialog is open:

1. The native Tk Canvas Wheel.
2. The managed HTML/CSS/JavaScript Browser / OBS Wheel.

The managed browser runtime is loopback-only and serves read-only health,
snapshot, spin-state, and browser resources. The application must remain open,
and the Collection Wheel dialog owns the runtime lifecycle.

The following remain outside the current feature:

- Browser Wheel operation while the main application is closed
- Standalone or tray-hosted Wheel service
- Streamer.bot command triggers
- Mutating HTTP or WebSocket commands
- LAN or remote-network exposure
- Browser-side winner selection

Python remains the source of truth for the selected candidate. The browser
validates that every spin instruction matches the exact snapshot, candidate
count, winner index, and winner ID before animating it.
