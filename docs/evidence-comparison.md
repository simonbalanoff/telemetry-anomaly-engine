# Compare relationships and preserved raw evidence

This experiment compares the existing statistical detectors with C++ PCA and
three simple scores derived from retained values and within-cell extremes. It
uses the same observed-cell exposure and a fixed validation false-alarm budget.
See [ADR 0004](decisions/0004-pca-and-evidence-comparison.md) for exact formulas,
selection rules, feature schema, and limitations.

## Run

Start with the verified v1 dataset from the [data pipeline](data-pipeline.md).
The feature exporter additionally needs the original trusted source archives.
The commands use only the existing NumPy/pandas core dependencies.

```bash
cmake --preset release
cmake --build --preset release --parallel
python python/export_features.py data/ESA-Mission1 data/processed
python python/run_comparison.py data/processed
```

The optional feature bundle is stored under `data/features/`; v1 telemetry stays
unchanged. The source-verified count/min/max array occupies roughly 730 MiB.
Comparison outputs under `data/results/comparison/` include:

| Artifact | Purpose |
| --- | --- |
| `selection.json` | Validation thresholds, feasible candidates, selected PCA rank, provenance |
| `runtime.json` | Fitted normalization, PCA eigenvalues/basis, score schema, combined timing |
| `engine_scores.bin` | Seven float64 C++ score columns, declared by runtime metadata |
| `evidence_scores.npy` | Retained excursion, raw excursion, and within-cell range |
| `validation_report.json` | Shared exposure, event metrics, scored/held alarm time, and trivial controls |
| `validation_*_alarms.json` | Alarm episodes with timing and per-channel evidence |
| `runs.jsonl` | Audit trail of completed reports |

Large outputs are gitignored. Completed selection hashes protect against accidental
reuse after code, data, engine, or configuration changes. Use a fresh output
directory for another configuration:

```bash
python python/run_comparison.py data/processed --false-alarms-per-day 0.05 --output data/results/budget-005
```

Default budget is one unmatched alarm episode per 100 eligible normal days.
By default, alarms hold across at most five usable unobserved cells. Missing cells
receive no event-detection credit; exclusions and outages remain hard boundaries.
Compare with strict episode splitting:

```bash
python python/run_comparison.py data/processed --bridge-missing-cells 0 --output data/results/comparison-no-hold
```

Selection is constrained on validation; no future false-alarm guarantee is implied.
The finite threshold grid can miss a better operating point between candidates.
PCA rank and threshold selection on the same validation period are model selection,
not an independent estimate of generalization.

## Plot and inspect

With the optional Matplotlib dependency from `python/requirements.txt`:

```bash
python python/plot_comparison.py data/results/comparison/validation_report.json data/results/comparison/summary.svg
```

An alarm catalog's evidence describes a model departure and its raw context. It
does not identify the true physical fault. PCA contributions sum to reconstruction
error; rolling-score alarms show contextual retained-value deviations rather than
claiming those are exact rolling-score contributions.

Historical M2 test results remain in `docs/results/`. This comparison defaults to
validation only. Further evaluation on the already examined test split is explicitly
exploratory and requires a frozen matching selection:

```bash
python python/run_comparison.py data/processed --exploratory-test
```
