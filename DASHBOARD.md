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

Smoothing starts **Off**, which connects the actual day/month averages. Choose
**Light**, **Medium** or **Strong** for exponential smoothing. These replace the
old calendar-window averages, which often had too few observations to smooth
sparse histories effectively.

Each difficulty's first observed average seeds its trend. Each later observed
average updates it as `trend = alpha * current + (1 - alpha) * previous trend`.
Light uses alpha 0.50, Medium 0.30 and Strong 0.15. Stronger smoothing responds
more slowly to changes; it can help reveal the broader trend but can also lag a
real improvement or setback. It does not guarantee a monotonically rising or
falling line, nor is it a fitted skill rating.

Smoothing operates on the displayed day/month averages. Each observed bucket
updates the trend once, regardless of the number of hacks within it. The raw
bucket averages retain their original exit weighting (or per-hack averaging);
neither the summary cards nor saved completion records are changed.

Only observations within the selected Dashboard period and Type participate.
Changing the period starts the calculation from its first eligible observation;
no earlier history or future observation leaks into the trend. A day/month with
no eligible observation neither updates nor resets the smoother. The next
observation blends with the previous trend even after a long interval.

The x-axis keeps actual calendar spacing. Both raw and smoothed lines connect
successive observations; **dashed segments** distinguish intervals containing
one or more missing periods for that difficulty and metric. These connectors
are visual guides, not measurements of what happened in the gap. No artificial
data points or zero-valued completions are inserted, and the lines are not
extended before the first or after the last observation.

Faint dots preserve the unsmoothed averages when smoothing is enabled. A single
observation appears as a point, without a connecting line. Axis labels use
ordinary decimal numbers (for example, `180m` rather than `1.8e+02m`).

## View choices

Metric, smoothing, type and hidden difficulties remain selected through
Dashboard refreshes, period changes, navigation and theme refreshes during the
current application session. On restart, the chart returns to Time per exit,
All Types, smoothing Off, with all difficulties visible. No new configuration,
Collection or playthrough files are written by these controls.
