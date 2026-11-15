# Research directions beyond the baseline

The current system provides a reproducible starting point for studying a narrower
question: **how much anomaly evidence survives preprocessing, and how much operator
attention is needed to detect a real event?** The experiments below are proposals,
not claims of improved performance.

## Preserve evidence before adding model complexity

The 30-second keep-last grid can erase a transient that occurs before the retained
sample. Compare the current grid with additional per-cell minimum, maximum, range,
sample count, and timing features. A second experiment can run a small spike
monitor on raw samples alongside the fixed-grid trend detector. Measure real-event
recall at the same false-alarm budget, with preprocessing and inference costs
reported separately. Keep original labels and aggregation decisions fixed before
held-out evaluation.

## Compare a frozen baseline with a cautious adaptive baseline

Rolling statistics eventually absorb a sustained fault; a fixed reference can flag
legitimate drift. Compare their disagreement rather than relying on either alone.
Test whether slowing or suspending updates during suspicious periods improves
fault persistence without locking the model into a stale operating regime.
Every adaptation rule must be causal and validated on historical prefixes.

## Distinguish operating mode, data quality, and fault evidence

A manoeuvre or equipment transition may be unusual but healthy. If available,
condition normal behaviour on command and mode information. Otherwise test
training-only clustering of recurring regimes and maintain an explicit unfamiliar
mode signal. Report data-quality alerts separately from measurement anomalies;
missing observations can hide a fault or indicate one.

Mode-aware monitoring has precedent in
[An Approach To Mode and Anomaly Detection with Spacecraft Telemetry Data](https://papers.phmsociety.org/index.php/ijphm/article/view/2467).

## Evaluate incidents and workload

An operational report should expose missed events, false alarms per day, delay,
alarm duration, fragmented alarms, and unscorable time. Add comparisons with
always-off, always-on, and random-score controls to detect misleading metrics.
Only 13 anomaly events are in this project's test subset: frame count must not be
mistaken for independent evidence about generalization. Use uncertainty intervals,
event-type breakdowns, and additional missions or channels before broad claims.
Synthetic spike, drift, stuck-sensor, and dropout tests can diagnose weaknesses,
but should remain separate from real-fault performance.

See the primary studies
[Towards a Rigorous Evaluation of Time-series Anomaly Detection](https://arxiv.org/abs/2109.05257)
and [European Space Agency Benchmark for Anomaly Detection in Satellite Telemetry](https://arxiv.org/abs/2406.17826).

## Make alarms inspectable

For each incident, retain the contributing channels, departure from the reference,
recent measurements, availability state, and related alarms. Treat explanations
as evidence of what the model used, not as a verified root-cause diagnosis.
This provides a practical path toward operator feedback and targeted relabelling.
