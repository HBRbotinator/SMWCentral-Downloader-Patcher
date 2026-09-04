# Dashboard clear-time trends

The chart follows the Dashboard period and its own Type filter. Last Week and
Last Month use daily buckets; longer periods use monthly buckets. Only completed
hacks with a valid completion date and positive recorded Time to Beat appear on
the timeline. All Time summary cards can also include undated completions.

## Metric

**Time per exit** is the default. For each difficulty and date bucket, it divides
the total recorded time of eligible hacks by their total known exits. The graph
uses minutes per exit. This is an exit-weighted average, not the average of each
hack's individual rate. For example, 2 hours over 2 exits plus 3 hours over 18
exits produces 5 hours / 20 exits = 15 minutes per exit.

Missing, zero, negative, fractional or invalid exit counts are excluded from this
metric, with an exclusion count above the graph. They are never replaced by an
assumed 50 exits. The summary card uses the same known-exit rule.

**Time per hack** retains the ordinary completion-duration view, in hours per
hack. Positive recorded time still qualifies when the exit count is unknown.

Each hack contributes once to All Types and once to each of its distinct types.
The chart uses the Collection's reviewed top-level Time to Beat, including a
verified imported first-clear duration; it does not sum repeat playthroughs.
Neither metric edits that recorded value.

Time per exit is a useful normalization, not a measurement of individual level
times or a pure skill rating. It uses the hack's recorded total exit count;
different hack designs and completion goals can still affect comparisons.

## Legend

Click a difficulty's checkbox, name or colored dot to hide/show its series.
Hidden difficulties do not affect the vertical scale. **Show all difficulties**
restores every series, including after all have been hidden. The legend wraps
onto additional rows in smaller windows and supports native keyboard checkbox
interaction.

## Smoothing

Smoothing starts **Off**. Choose a **3-day / 5-day average** for daily periods,
or a **3-month / 5-month average** for monthly periods.

The line uses a trailing window ending at each observed date bucket. It combines
the underlying time and exit totals (or time and hack counts), rather than
averaging bucket averages. Early windows use the available in-period data;
future dates and records outside the selected Dashboard period never contribute.

Faint dots preserve the actual unsmoothed bucket averages. A period without a
valid observation stays a gap; neither the raw nor smoothed line connects across
it. Smoothing is a display calculation only, not interpolation, an estimate of
missing completions, or a change to your saved history.

## View choices

Metric, smoothing, type and hidden difficulties remain selected through
Dashboard refreshes, period changes, navigation and theme refreshes during the
current application session. On restart, the chart returns to Time per exit,
All Types, smoothing Off, with all difficulties visible. No new configuration,
Collection or playthrough files are written by these controls.
