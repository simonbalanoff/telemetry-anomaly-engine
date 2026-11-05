# ADR 0001: Data split and telemetry preprocessing

- **Status:** Accepted for the initial baseline; evaluation parameters noted below remain open
- **Date:** 2026-11-04
- **Scope:** ESA-ADB Mission1 channels 41–46, Python conversion and C++20 replay/evaluation
- **Related:** [ESA-ADB dataset](https://doi.org/10.5281/zenodo.12528696), [ESA-ADB implementation](https://github.com/kplabs-pl/ESA-ADB)

## Context

The engine will replay a fixed-rate, six-channel representation of spacecraft telemetry and compare statistical, PCA-reconstruction, and autoencoder-reconstruction anomaly detectors. Python performs trusted-source decoding, exploratory checks, conversion, and reference training; the runtime and scoring engine are C++20.

The following observations were checked against the locally downloaded Mission1 files and exploration outputs; the raw data is not committed to this repository:

- Channels 41–46 have 15,381,169 raw samples each, with matching, monotonic, unique timestamps, no NaNs, and coverage from 2000-01-01 through 2013-12-31.
- The nominal cadence is 30 seconds, with timestamp jitter and additional intra-cell samples. Of 14,728,320 aligned 30-second cells, 14,642,408 are occupied and 85,912 are empty (about 0.58%). Of occupied cells, 733,166 (about 5.01%) contain multiple samples.
- Within-cell value spread has a median of 0.0086 on channel 41 and 0.0102 on channel 44. For labelled point anomaly `id_187` at 2013-11-19 14:57:17.751 UTC, the third and last observation of its cell is anomalous: channel 41 rises to approximately 0.963274 and channel 44 falls to zero. Keep-first loses these large changes; keep-last and the examined maximum-deviation policy preserve them.
- There are 118 distinct labelled events touching these channels: 51 anomalies, 63 rare events, and 4 communication gaps. Labels are per event/channel, and labelled channel intervals need not be identical. Eleven events have zero duration; many other anomaly intervals are shorter than one grid interval.
- Some anomalous intervals are subtle and sustained (inspected examples: `id_153` and `id_157`), whereas `id_187` is an obvious synchronized point spike. Inspected rare event `id_147` also shows coordinated changes, so it must not silently count as ordinary negative training data.
- The four communication-gap events exhibit different availability patterns, as measured on channel 41:

| Event | Missing 30-second cells | Missing runs | Longest run | Runs longer than 5 cells |
| --- | ---: | ---: | ---: | ---: |
| `id_52` | 612 | 181 | 29 | 2 |
| `id_53` | 48 | 7 | 29 | 1 |
| `id_54` | 708 | 1 | 708 | 1 |
| `id_57` | 390 | 120 | 4 | 0 |

These analyses describe the selected Mission1 subset, not all ESA-ADB missions or channels.

## Decisions

### 1. Temporal grid and collisions

- Align timestamps in UTC using `floor("30s")`; retain the chronological order of raw observations.
- Emit one six-channel frame for each 30-second cell in the covered interval. All six source channels share timestamps in the checked files; the converter must validate this rather than assume it.
- **Primary aggregation: keep the last raw observation in each cell**, independently for each channel. This is a simple, deterministic baseline and preserves the inspected point anomaly `id_187`. It does **not** guarantee preservation of other short anomalies.
- Store or report collision statistics during conversion. Compare keep-first and maximum-absolute-deviation alternatives in a later sensitivity experiment; do not tune aggregation using test-set detection results.
- A grid frame becomes available at **the end** of its 30-second cell, not at the floored timestamp. Use this availability convention for replay timing and detection-delay calculations. The original label timestamps remain at their actual UTC instants.

### 2. Missing observations and imputation

- Distinguish **observed**, **forward-filled**, and **unavailable** states. An imputed value must never be treated as a measured observation.
- Forward-fill only from the most recent observed cell, for at most **five consecutive empty cells** (150 seconds). Track staleness in grid steps. On the sixth consecutive empty cell and beyond, mark the value unavailable rather than continuing to fabricate a usable measurement.
- After an extended unavailable run, reset rolling/history-dependent detector state. Do not score any model window that requires an unavailable cell; resume only when sufficient valid history has been accumulated. The exact warm-up policy is detector-specific and must be tested.
- Keep imputation/availability information separate from labels. A labelled communication-gap interval may contain real observations. Do not overwrite observed measurements merely because they fall within a communication-gap label.
- The five-cell limit is an engineering baseline motivated by observed short missing runs; it is **not** a validated optimum. Report how often frames/windows are excluded and consider a sensitivity analysis.

### 3. Chronological partition and leakage control

Use UTC boundaries and half-open partitions:

| Partition | Interval | Anomaly events | Rare events | Communication gaps |
| --- | --- | ---: | ---: | ---: |
| Train | [2000-01-01, 2008-01-01) | 27 | 35 | 4 |
| Validation | [2008-01-01, 2011-01-01) | 11 | 14 | 0 |
| Test | [2011-01-01, 2014-01-01) | 13 | 14 | 0 |

The `check_split.py` output reported **zero** labelled events whose start and end lie in different partitions. This does not by itself prevent feature-history leakage.

- Do not let feature windows cross a partition boundary. Apply an embargo of at least the maximum required feature-history/window length (and include any additional stateful warm-up where necessary).
- Fit normalization, PCA, and neural-network parameters **only on eligible training data**. No validation/test values, including unlabeled values, may influence fitted transforms or thresholds.
- Choose thresholds and other model-selection parameters on validation only; reserve test for a final locked evaluation. If the test is revisited after changes, document that as exploratory rather than a pristine held-out estimate.
- Training windows must not overlap labelled anomalies, rare events, or communication gaps, or contain unavailable samples. An explicit, reproducible eligibility mask will implement this policy.

### 4. Labels and evaluation eligibility

- Preserve source event IDs, categories, channel IDs, and precise start/end timestamps in the preprocessing artifacts or accompanying metadata. Do not collapse the source labels irreversibly into one global binary bit.
- Create channel-wise grid labels for convenience, plus a derived global anomaly flag (`any` labelled channel). For a positive-duration interval, mark cells intersecting the interval; **zero-duration point events explicitly label the cell containing the instant**. Define endpoint conventions unambiguously in the converter and test them at cell boundaries.
- Keep **label category** distinct from **measurement availability** and from **evaluation eligibility**. For the primary benchmark, rare-event and communication-gap intervals are excluded from false-alarm counting, but their observed measurements stay in the replay and remain auditable. Report the excluded time/cell fraction.
- Evaluate anomalies primarily by **event**, not just by positive grid-cell counts. Avoid counting multiple alarms on one event as multiple true positives; define matching, alarm deduplication, and treatment of alarms outside eligible periods before reporting scores.
- Report event-wise precision/recall/F1, false alarms per eligible day, detection delay, and AUC-PR where meaningful, alongside ESA-ADB's official time-aware evaluation for comparability. With only 13 test anomaly events, report uncertainty intervals and avoid overstating ranking differences. Event-level bootstrap methodology must be specified before use.

### 5. Point events and time resolution

- Preserve precise point-event timestamps independently of gridded labels. Detection is only available after the 30-second aggregation cell closes, so scores cannot claim sub-cell reaction time.
- **Open parameter:** an allowed point-event alarm tolerance and event-matching window. Set this using benchmark conventions and/or validation data, publish it before final test evaluation, and include a tolerance sensitivity analysis. Do not select it based on test outcomes.

## Alternatives and tradeoffs

| Choice | Why not the primary baseline |
| --- | --- |
| Keep-first per cell | Erases the inspected `id_187` spike. |
| Maximum deviation per cell | Selects extreme values by construction, potentially inflating apparent anomaly evidence; compare as an ablation instead. |
| Unlimited forward-fill | Makes hours-long outages appear like trustworthy repeated telemetry. |
| Drop all communication-gap intervals from replay | Discards genuine observations and conflates benchmark labels with sensor availability. |
| Random train/test split | Leaks temporal structure and risks overly optimistic generalization. |
| Global anomaly bit only | Loses channel attribution, event identity, and accurate event-wise evaluation. |
| Preserve every raw observation in the primary engine | More faithful timing, but defeats the intended fixed-rate frame representation; a future sensitivity study may compare it. |

## Known limitations and open follow-ups

1. Verify the exact fraction of eligible scored frames/windows over the **full** timeline, not merely within four labelled communication gaps.
2. Compare collision policies beyond `id_187` on representative normal periods and labelled events; the selected keep-last policy can still lose an earlier anomalous observation within a cell.
3. Choose model window lengths, state reset/warm-up behavior, event-matching tolerance, and alarm deduplication **before** locked test evaluation.
4. Define normalization when channels are imputed, and whether staleness/observation states are supplied as detector features; avoid silently fitting on synthetic fills.
5. Specify the binary interchange format separately: magic/version, endianness, timestamps and cell-availability convention, six float32 values, quality masks/staleness, label/event metadata, partition identifiers, checksums/length validation, and malformed-input behavior. Do this before implementing `preprocess.py` or the C++ reader.
6. Keep reproducible summaries and small synthetic test fixtures in version control; raw ESA pickle/ZIP data remains local and must only be unpickled from trusted sources.

## Verification required before M1

- Synthetic tests for grid-boundary timestamps, single and multiple collisions, empty cells, five-versus-six-cell missing runs, and channel alignment failures.
- Label tests for point events, channel-specific intervals, intervals touching grid-cell boundaries, and category/eligibility distinctions.
- Split tests asserting no model window spans a boundary and that fit/threshold sources are restricted to train/validation respectively.
- A documented binary-format agreement and round-trip test plan before creating the converter/loader.

**Decision outcome:** The initial dataset representation and leakage policies are sufficiently specified for the next design step. The binary layout and the explicitly open evaluation parameters are not yet finalized.
