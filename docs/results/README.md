# Local M1/M2 results

These small artifacts document a complete local run on ESA-ADB Mission1 channels
41–46. Raw data, binary frames, masks, and score arrays remain gitignored.

## M1: complete export verification

[m1-validation.json](m1-validation.json) records reference counts, file hashes,
quality-state counts, an independent vectorized full-source comparison, and an
independent full-file C++ scan. All 14,728,320 exported frames match the expected
keep-last/forward-fill values bit for bit.

| State | Frames |
| --- | ---: |
| Observed | 14,642,408 |
| Forward-filled | 83,800 |
| Unavailable | 2,112 |

The bundle contains 1,255 event-channel intervals across 118 original event IDs.

## M2: frozen statistical baseline

The configuration is a 120-cell rolling window, EWMA alpha 0.05, and a normalized
rolling standard-deviation floor of 0.05. Normalization used 8,296,650 eligible
observed training cells. Validation selected thresholds of approximately
6.785716 for z-score and 46.391470 for EWMA.

| Partition | Detector | Detected / eligible events | Precision | Recall | F1 | False alarm episodes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Validation | Rolling z-score | 10 / 11 | 0.5000 | 0.9091 | 0.6452 | 10 |
| Validation | EWMA | 7 / 11 | 0.1628 | 0.6364 | 0.2593 | 36 |
| Test | Rolling z-score | 10 / 13 | 1.0000 | 0.7692 | 0.8696 | 0 |
| Test | EWMA | 6 / 13 | 1.0000 | 0.4615 | 0.6316 | 0 |

Test reporting was requested once after freezing the validation selection. Both
validation and test records appear in [m2-runs.jsonl](m2-runs.jsonl). The report
uses custom strict one-to-one event/episode matching, not the official ESA
hierarchical metric. Details are frozen in
[ADR 0003](../decisions/0003-statistical-baseline-and-evaluation.md).

Interpret these figures with their limits:

- There are only 13 test anomaly events. Recall intervals, individual matched IDs,
  and delay distributions are in the JSON reports; zero false alarms here does
  not imply a zero underlying false-alarm rate.
- Roughly 1.90% of test cells are excluded by labels, unavailable data, or warm-up.
  All 13 test anomaly events have at least one eligible scored cell.
- Long EWMA alarm episodes can cover substantial time. Alarm durations are
  reported separately from episode counts; the precision alone conceals this.
- The test period happens to score better than validation for these thresholds.
  This does not establish improvement on another mission or channel group.
- The current train/validation/test split has now been evaluated. Further changes
  examined on this same test period are exploratory.

Artifacts:

- [m2-selection.json](m2-selection.json): thresholds, validation candidates, provenance.
- [m2-validation.json](m2-validation.json): full validation report.
- [m2-test.json](m2-test.json): full held-out report.

## Reproduce

```bash
cmake --preset release
cmake --build --preset release --parallel
python python/convert_esa.py data/ESA-Mission1 --output data/processed/telemetry.bin
python python/verify_export.py data/ESA-Mission1 data/processed
python python/evaluate.py data/processed --output data/results/reproduction
python python/evaluate.py data/processed --output data/results/reproduction --test
```

A separately compiled executable normally has a different hash. Regenerate the
selection on validation using a fresh results directory rather than copying the
frozen selection from this run. Detector latency samples are local to macOS arm64
with AppleClang 21 release optimization; they exclude I/O and are not end-to-end
latency or portable performance guarantees.
