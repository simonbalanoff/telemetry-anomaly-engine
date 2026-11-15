# ADR 0004: PCA, preserved raw evidence, and workload-constrained comparison

> **Implementation update:** The original C++ runtime/build/test stack has been
> retired. This ADR records the historical design; the binary schema, Python
> conversion, and applicable data policies remain in use. See
> [development](../development.md) for the current Python workflow.


- **Status:** Accepted for the next research baseline
- **Scope:** Fixed six-channel C++ numerical kernels, optional feature bundle, validation-only comparison
- **Related:** [M2 policy](0003-statistical-baseline-and-evaluation.md)

## Decisions

### Learn relationships on eligible training observations

A multivariate Welford accumulator computes raw sample covariance on the same
observed, unlabelled training cells used by the existing normalizer. The covariance
is standardized by the training sample standard deviations, with the same `1e-12`
floor as the normalizer. No validation or test observation contributes to these
moments. A symmetric Jacobi eigensolver returns descending eigenvalues and an
orthonormal basis; eigenvector signs are canonicalized for inspectable artifacts.
It rejects nonfinite/asymmetric input and reports non-convergence.

PCA reconstruction error is the squared residual after projection onto the first
`k` eigenvectors, averaged over six normalized channels. Channel contributions
sum to the overall score. Candidate ranks are 1–5; validation selects the rank.
Indefinite covariance matrices are rejected. Singular covariance and repeated
eigenvalues are supported, although a basis splitting a degenerate eigenspace is
not uniquely identifiable. Tests compare reconstruction/covariance, not arbitrary
signs of NumPy eigenvectors.

The existing `score` command continues to produce exactly two score columns.
`score-pca` adds `pca_1` through `pca_5` and records eigenvalues/eigenvectors and
column names in runtime metadata. It computes PCA scores only on observed frames,
with the statistical detector's existing warm-up mask for a fair comparison.
The sampled update latency includes all five PCA scores together; it is not the
latency of one selected PCA model.

### Preserve optional evidence without changing the v1 wire format

`export_features.py` writes a separate `TAE-CELL-FEATURES` version-1 bundle:

```text
data/features/
  cell_features.npy
  manifest.json
```

The fixed NumPy structured dtype contains a little-endian uint32 raw sample count
and six little-endian float32 minima and maxima per grid cell. It uses 52 bytes
per cell, plus the NumPy header. Extrema are computed after the same binary32
conversion used by the v1 dataset. They preserve all within-cell extremes at that
precision, but not their exact ordering or timestamps.

A cell without raw samples has count zero and six NaN minima/maxima, including
cells whose v1 measurement was forward-filled. Extrema are never imputed. The
exporter checks source alignment/coverage, every occupied cell's keep-last bits,
and the occupancy mask against the verified v1 file. The manifest binds the feature
file to that exact telemetry SHA-256 and records its own full-file hash, channel
order, frame count, grid period, source statistics, and exporter hash. Opening
checks schema, hashes, occupancy, and extrema bounds. NumPy pickle loading is disabled.

This is an offline feature sidecar. No C++ inference support or claim of exact
transient reconstruction is implied. A complete bundle occupies roughly 730 MiB;
large artifacts stay gitignored.

### Use a matched control to measure discarded evidence

Three additional scores share the existing frozen training normalizer:

- **Retained excursion:** largest absolute standardized retained value.
- **Raw excursion:** largest absolute standardized minimum or maximum.
- **Within-cell range:** largest standardized max-minus-min range.

The retained/raw pair isolates evidence retention under identical normalization
and exposure. The raw score must be at least the retained score on observed cells;
independently selected thresholds can still give it worse event detection.
All evidence becomes available at cell end, never before its raw samples arrive.

### Enforce equal exposure and an explicit alarm budget

All compared detectors use the intersection of observed cells, completed statistical
warm-up, and finite score coverage. Rare-event and communication-gap exclusions
are shared. Every score must be finite on this common mask; differing coverage
causes failure. This differs from the historical M2 report, which allowed filled
cells, so the reports are not directly comparable.

Default budget: at most **0.01 unmatched alarm episodes per eligible normal day**
on validation. Threshold candidates use both validation normal-score and all eligible validation-score quantiles
`0.9, 0.95, 0.99, 0.995, 0.999, 0.9995, 0.9999, 0.99995, 0.99999, 0.999995,
0.999999, 1`, plus an explicit no-alarm threshold above the maximum eligible
validation score. Including the all-score tail permits thresholds above the maximum
normal score, which can reduce fragmentation of long anomalies without selecting
the no-alarm option. This finite grid is an approximation, not an exhaustive search
over thresholds; the extreme-tail resolution matters for low budgets.

Among feasible thresholds, maximize event recall, then minimize false alarm count,
then total alarm seconds, then maximize threshold. Choose the best PCA rank by
the first three criteria, with fewer components breaking ties. Raw threshold
magnitudes are not compared across different detectors. Configuration, dependency
script hashes, engine hash, dataset/feature hashes, and Python/NumPy versions are
frozen in the selection artifact. Selection rejects eligibility outside validation.
A validation budget is not a guarantee on future telemetry.

### Hold an incident through short gaps without inventing detections

The version-2 comparison uses a default alarm hold of five cells. Two above-threshold
observed episodes merge only if every intervening cell is unobserved, still usable
under the v1 fill policy, not label-excluded, and the gap is at most five cells.
Observed below-threshold cells, unavailable data, rare-event/communication-gap
labels, and partition boundaries remain hard breaks. A merged interval contains
both endpoints; gaps after the final scored alarm are not extrapolated.

Event matching still intersects **eligible scored cells only**. A point event in
a held missing cell remains unscorable and receives no detection credit. Reports
separate `alarm_scored_cells` from `alarm_held_unscored_cells`; total alarm seconds
include the held time. Alarm fraction uses scored alarm cells over eligible scored
cells, so missing cells cannot inflate it above one. Peak evidence is selected
only from scored cells, avoiding NaN extrema in held gaps. The same policy applies
to every detector and to trivial controls.

`--bridge-missing-cells 0` reproduces strict episode splitting. This control is
reported separately so a change in alarm management is not misrepresented as a
change in the detector's numerical accuracy. The historical M2 entry point retains
its original strict default. New comparison selection artifacts include the hold
configuration and identify policy `evidence-comparison-v2`.

### Report incidents and workload, including trivial controls

Reports retain the existing one-to-one event matching and false-alarm semantics,
with the explicit episode hold described above. They add alarm fraction and always-on/always-off controls to reveal
where event metrics can conceal excessive alarm duration. For each alarm episode,
a catalog records timing, peak score, quality state, raw sample count, per-channel
retained/extreme values, and overlapping event IDs. PCA contributions are squared
reconstruction residuals; raw/range contributions correspond to their score.
Statistical alarm context is explicitly labelled as a frozen-reference deviation,
not an attribution of the rolling z-score or EWMA. These are model explanations,
not root-cause diagnoses. Overlap IDs are not a substitute for the one-to-one matcher.

The historical test split has already been examined. Default reporting remains
validation-only. An existing matching selection plus `--exploratory-test` is
required for further test reporting; such runs are explicitly labelled exploratory.
No new test report is needed to validate this implementation.

## Verification

- Random symmetric reconstruction and orthogonality checks, zero/repeated
  eigenspaces, malformed matrices, and large-offset covariance tests.
- Independent NumPy covariance/eigendecomposition/PCA parity for every candidate
  rank through the real CLI, plus unchanged legacy score-column checks.
- A synthetic within-cell spike erased by keep-last but retained by extrema.
- Feature corruption, mismatched source values, dataset binding, and extrema checks.
- Budget feasibility, validation-only mask enforcement, test-score mutation checks,
  JSON artifact serialization, and missing-cell hold/no-detection-credit checks.
- Complete real-data feature export and validation-only detector comparison.

## Interpretation limits

Linear PCA can miss faults aligned with its retained subspace, and global training
covariance need not describe every operating mode. Extrema preserve a spike's
magnitude, not its physical significance; they can also preserve harmless noise.
A better cell-level ranking need not produce better event recall at a strict alarm
budget. Missingness and episode policy materially affect workload, so expose both
the strict and held-alarm comparisons before drawing model-ranking conclusions.
