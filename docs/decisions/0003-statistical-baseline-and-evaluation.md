# ADR 0003: Statistical baseline and event evaluation

> **Implementation update:** The original C++ runtime/build/test stack has been
> retired. This ADR records the historical design; the binary schema, Python
> conversion, and applicable data policies remain in use. See
> [development](../development.md) for the current Python workflow.


- **Status:** Accepted for M2
- **Scope:** Causal C++ baseline, validation selection, reproducible event reports
- **Related:** [Data policy](0001-data-split-and-preprocessing.md), [wire format](0002-binary-telemetry-format.md)

## Detector and fitting policy

Normalization uses per-channel Welford sample mean and variance fitted only on
**observed training cells** that intersect no anomaly, rare event, or communication
gap in any selected channel. It fits individual observations, so no training
feature windows are involved. Standard deviation has a floor of `1e-12`.

Two independent scores share this fixed normalization:

1. **Rolling z-score:** maximum absolute per-channel deviation from the previous
   120 usable cells, divided by their sample standard deviation. A floor of 0.05
   in normalized units prevents nearly constant windows producing unbounded scores.
   Welford insertion/removal maintains rolling moments.
2. **EWMA:** maximum absolute per-channel exponentially weighted normalized value,
   divided by `sqrt(alpha / (2 - alpha))`, with `alpha = 0.05`. This is a sustained
   departure score against the fixed training reference; the scale is conventional,
   not a calibrated probability under correlated telemetry.

A frame is scored before it enters rolling history. Observed and forward-filled
usable cells both update history; unavailable cells reset all history. Each reset,
including each partition boundary, requires 120 prior usable cells before scores
resume. State is initialized from the first usable value. These rules prevent
feature history crossing train/validation/test boundaries. The baseline consumes
measurements and quality masks only; labels never enter C++ scoring.

## Event matching and eligibility

Annotations retain individual channels and intervals. Matching uses the union of
anomaly-labelled channel intervals belonging to one original event ID. Positive
intervals are half-open; point events belong to their containing grid cell.
No extra tolerance is used in the primary report. Additional 30-second and
60-second tolerances are reported for sensitivity, without threshold reselection.

Rare-event and communication-gap cells in any selected channel are excluded from
primary evaluation. Missing scores, outages, and warm-up are also excluded.
An event with no eligible scored cell is reported as **unscorable**, rather than
silently counted as detected or omitted without accounting. Reports provide both
eligible-event counts and excluded/warm-up cell fractions.

An alarm episode is a maximal contiguous run of eligible scores at or above a
threshold. An excluded cell or missing score breaks the episode. Episodes are
processed chronologically. Each episode matches at most one unmatched event;
when multiple events intersect it, the earliest-ending event wins, with event ID
as a deterministic tie-break. Each event contributes at most one true positive.
Unmatched episodes, including repeat episodes on a previously detected event,
count as false alarms. This strict rule makes fragmentation and long alarms
visible limitations; it is not the official ESA hierarchical metric.

Detection delay is the first matching cell's **availability time** minus the
original event start, clamped to zero for early matches in tolerance sensitivity.
The false-alarm denominator is eligible scored time outside anomaly intervals,
expressed in 86,400-second days. Event precision, recall, F1, Wilson 95% recall
intervals, cell-level average precision (grouping score ties), and p50/p95/p99
detection delays are reported. Wilson intervals are descriptive; event independence
is an approximation. No event bootstrap or official ESA metric is claimed.

## Threshold selection and held-out evaluation

For each score, validation-only candidates are normal-score quantiles
`0.95, 0.99, 0.995, 0.999, 0.9995, 0.9999, 1.0`, plus an explicit no-alarm candidate
just above the maximum eligible validation score. Choose the largest event F1,
then fewest false alarms, then largest threshold. This finite candidate policy is
fixed before evaluation; window and alpha defaults are not selected on test data.

`selection.json` freezes thresholds with dataset-manifest, training-mask,
executable, and evaluation-script hashes plus detector configuration. Reusing an
output directory with changed provenance fails. Test reporting requires an
existing selection and explicit `--test`; it never reselects thresholds. Scores
are generated for the whole timeline, but test labels/scores do not participate
in validation selection. Every completed report appends an audit record; repeated
test evaluation must be described as exploratory.

## Timing and artifact boundaries

Dataset hashes and CSV/schema validation run in Python before invoking the C++
engine. C++ independently validates header, size, every frame, and frame-state
transitions. Direct low-level `tae score` callers must supply a verified dataset
and a correct eligibility mask; the supported benchmark entry point is
`python/evaluate.py`.

Scores are pairs of little-endian binary64 values `(zscore, ewma)`, one record per
input frame, with NaNs for unscorable frames. No labels appear in the score file.
Runtime metadata records fitted means/variances and frame counts. Latency samples
measure one detector update in every 1,024 frames, including normalization and
warm-up/outage paths, excluding file I/O, fitting, parsing, and integrity checks.
These are local observations, not hard real-time guarantees or end-to-end latency.

## Known limits

Mode changes, non-Gaussian channels, autocorrelation, contaminated unlabelled
training data, and small event counts remain substantive limitations. Rolling
history can absorb sustained anomalies; EWMA's frozen reference can mistake
legitimate drift for faults. Six synchronized channels do not establish performance
on a whole spacecraft. The M2 report is a baseline, not a state-of-the-art claim.
