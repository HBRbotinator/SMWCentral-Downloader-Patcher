# Browser / OBS Wheel Runtime

The Browser / OBS Wheel is a managed, local companion to the native Collection
Wheel. It renders the same eligible pool in HTML, CSS, and JavaScript so it can
be used as an OBS Browser Source.

Python remains authoritative for filtering and winner selection. The browser
does not choose, reroll, or influence a result.

## Start the managed runtime

1. Open **Collection → Open Wheel**.
2. Apply the desired Collection and optional Planner filters.
3. Select **Start Browser Wheel**.
4. Use the displayed URL for an OBS Browser Source.

The application attempts to copy the URL when the runtime starts. **Copy OBS
URL** repeats the clipboard operation without restarting the runtime.

The displayed URL is authoritative. The default runtime normally uses
`127.0.0.1` on port `8765`, but integrations should use the URL shown by the
dialog rather than constructing one.

The dialog displays the transparent overlay form:

`/wheel/?mode=overlay`

The base `/wheel/` URL remains a full preview and diagnostics page.

The runtime starts from the exact active pool. It does not expose the complete
Collection when filters have removed candidates.

## Configure OBS

In OBS:

1. Add a **Browser** source.
2. Paste the URL shown by the Collection Wheel dialog.
3. Choose a source width and height large enough for the wheel, heading, status,
   and result panel.
4. Keep the application and Collection Wheel dialog open while the source is in
   use.

The overlay has a transparent outer background and removes the preview title,
status badge, footer, card background, border, and diagnostic text. It loads no
external framework, CDN, font, script, image, or stylesheet.

The overlay is fully hidden while idle. A newly observed spin reveals it before
animation, keeps the result visible for eight seconds, and then returns to a
transparent hidden state.

Reloading the OBS source displays the current snapshot. A previously published
spin is treated as current state, but each newly observed sequence is animated
at most once per loaded page.

## Filters, spins, and rerolls

When the managed runtime is running, filter changes refresh its snapshot with
the exact current eligible pool.

For a normal spin:

1. The native Collection Wheel model selects the winner.
2. The dialog refreshes the browser snapshot from the exact selection pool.
3. Python publishes a versioned spin instruction containing the predetermined
   winner.
4. The native and browser renderers animate independently toward the same
   result.

For **Spin Again**, the browser snapshot uses the exact reroll pool after the
current result has been excluded. The previous result is not shown as eligible
for that reroll.

Browser publication occurs after selection. A browser-runtime error therefore
does not reroll, replace, or invalidate the native result.

## Browser animation and result presentation

The Browser / OBS Wheel uses a separate show-oriented schedule:

- 10.5 seconds total duration;
- nine full turns;
- one continuous `requestAnimationFrame`-driven motion curve;
- smooth acceleration through the first 10%;
- a high-speed middle through 27%;
- continuous deceleration over the final 73%;
- velocity and acceleration tapering smoothly to zero.

The animation does not switch between staged CSS transitions, so the final
slowdown has no braking handoff. The exact final rotation still comes from the
published Python-authored instruction.

Python chooses a safe visual landing offset inside the predetermined winner's
segment from nine weighted bands:

| Landing region | Segment position | Weight |
| --- | --- | --- |
| Hairline early | `0.025–0.055` | 8% |
| Extreme early | `0.07–0.13` | 14% |
| Early | `0.18–0.32` | 15% |
| Inner early | `0.36–0.46` | 10% |
| Center | `0.47–0.53` | 6% |
| Inner late | `0.54–0.64` | 10% |
| Late | `0.68–0.82` | 15% |
| Extreme late | `0.87–0.93` | 14% |
| Hairline late | `0.945–0.975` | 8% |

The early and late sides each receive 47% total probability. Hairline finishes
can creep just inside the selected segment or stop just before the following
segment while retaining a small visible margin.

Segment labels are radial. The browser tracks each label's combined wheel angle
and flips it by 180 degrees whenever it would otherwise appear upside down.

The final result displays the complete title. Long and exceptionally long names
wrap and use responsive size tiers rather than being ellipsized. The overlay
announces `WINNER!`, holds the result for eight seconds, expands celebration
rings, emits spark rays, animates the result card and title, and pulses the
winning segment.

Spark count, angle, distance, delay, hue, and scale vary, as do card tilt and
ring expansion. This presentation variation is derived from the immutable
Python-authored spin ID, sequence, and winner ID. It is repeatable for the same
instruction, uses no browser entropy source, and cannot influence the selected
winner.

## Predetermined spin validation

Every browser spin instruction is tied to:

- a monotonic sequence;
- an opaque spin ID;
- the snapshot generation time;
- the source revision;
- the candidate count;
- the winner ID;
- the winner title;
- the winner index;
- animation duration;
- full turns;
- the landing offset within the winning segment.

Before animating, the browser verifies that the instruction matches the exact
snapshot and candidate at the published index. A mismatched instruction waits
for synchronization instead of animating against the wrong pool.

The browser contains no entropy source or winner-selection function. Presentation variation is deterministically derived from the immutable spin identity.

## Runtime lifecycle

**Start Browser Wheel** is idempotent while the runtime is already active.
**Stop** shuts down the local service. Closing the Collection Wheel dialog also
stops it.

After the runtime is stopped, its URL is no longer available until it is started
again. OBS may continue showing its last rendered frame, but it cannot receive
new snapshots or spins.

The current managed mode is intentionally dialog-owned. It does not continue
running after the main application or Collection Wheel dialog closes.

## Read-only routes

The loopback service exposes these current routes:

| Method | Route | Purpose |
| --- | --- | --- |
| GET / HEAD | `/api/v1/health` | Snapshot and spin readiness |
| GET / HEAD | `/api/v1/snapshot` | Latest validated eligible-pool snapshot |
| GET / HEAD | `/api/v1/spin` | Latest Python-authored spin instruction |
| GET / HEAD | `/wheel/` | Full browser preview and diagnostics |
| GET / HEAD | `/wheel/?mode=overlay` | Transparent idle-hidden OBS presentation |
| GET / HEAD | `/wheel/style.css` | Embedded renderer styling |
| GET / HEAD | `/wheel/app.js` | Embedded read-only renderer client |

Mutating methods are rejected. There is no browser or HTTP command that starts a
spin or chooses a candidate.

## Security and privacy boundaries

The managed service:

- binds only to `127.0.0.1` or `localhost`;
- is not exposed to the LAN;
- accepts only read-oriented GET and HEAD requests;
- sends no-cache and content-sniffing protection headers;
- applies a same-origin Content Security Policy to browser assets;
- uses embedded local assets rather than third-party resources;
- returns versioned, validated JSON;
- excludes local ROM paths, save paths, download URLs, notes, raw SMWC payloads,
  Personal Rating, and arbitrary application internals;
- keeps Collection and Planner records detached from browser-visible snapshots.

Loopback-only and read-only behavior is part of the current contract. It should
not be weakened merely to support an external trigger.

## Troubleshooting

### The runtime does not start

The dialog shows the startup error. A common local cause is another process
already using the configured port. Stop the conflicting process or restart the
application after the port becomes available.

### OBS shows a connection error

Confirm that:

- **Start Browser Wheel** still shows the runtime as running;
- the Collection Wheel dialog remains open;
- OBS uses the exact currently displayed URL;
- the URL still opens from the same computer.

Restarting the runtime may produce a new usable session. Copy the displayed URL
again rather than relying on an old value.

### The page says it is waiting for a snapshot

Start the runtime from the Collection Wheel dialog. Initial startup publishes a
snapshot before the HTTP service begins serving the page.

If a later filter refresh fails, the runtime keeps its previous valid pool and
the dialog reports that the previous pool was retained.

### A spin does not animate in OBS

Confirm that OBS uses the displayed URL ending in `?mode=overlay`, that the
native spin completed selection, and that the dialog did not report a browser
publication error.

The browser deliberately refuses to animate a spin whose snapshot timestamp,
revision, candidate count, winner index, or winner ID does not match its current
snapshot. It waits for synchronization rather than showing a misleading result.

Reloading an OBS Browser Source resets page-local observation state. It does not
cause Python to choose another winner.

### The overlay appears empty between spins

That is the intended OBS behavior. Overlay mode hides the complete wheel and
result presentation while idle. Use the base `/wheel/` URL when a continuously
visible preview and diagnostics page is needed.

## Current limitations and future boundary

The current runtime is the managed in-application mode. It does not yet provide:

- a standalone or tray-hosted process;
- operation while the main application is closed;
- Streamer.bot control;
- an authenticated command API;
- a mutating HTTP or WebSocket endpoint;
- LAN or remote access;
- persistent spin history.

Future advanced-control work should reuse the same snapshot, spin, filtering,
and Python-authoritative selection contracts rather than moving winner selection
into JavaScript.
