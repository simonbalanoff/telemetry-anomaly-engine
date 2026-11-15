# Telemetry Anomaly Engine

**Research focus: preserve diagnostically useful telemetry under storage and
downlink budgets.** The engine is evolving from detector benchmarking into a
causal recorder that decides which native observations and surrounding context to
retain before the nature of a fault is known.

The initial recorder prototype includes explicit packet-byte accounting, bounded
pre-trigger context, reserved detector-independent background sampling, and four
reference capture policies. Its current results are **synthetic protocol checks**;
real-mission retention benefit and novelty remain unproven.

The existing C++20 reader, statistical/PCA detectors, verified ESA data pipeline,
and reproducible evaluation provide supporting infrastructure. The recorder itself
is currently a Python research prototype; native mission replay, C++ integration,
and operational validation are the next research milestones. This is not
flight-qualified software.

Start with the [research protocol](docs/retention-research.md) and
[LaTeX paper draft](paper/README.md).

## Research paper

[Read the current PDF draft](paper/draft.pdf) · [LaTeX source](paper/main.tex) ·
[Research plan and missing evidence](paper/research-plan.md)

<a href="paper/draft.pdf"><img src="paper/preview.jpg" alt="First page of Simon Balanoff's research draft; click to open the PDF" width="420"></a>

This is a checked-in draft snapshot, with synthetic protocol results only. The
[CI workflow](.github/workflows/ci.yml) also builds a downloadable PDF artifact.
After editing the manuscript, run `make -C paper preview` and include the refreshed
PDF, thumbnail, and snapshot manifest in the same commit. CI checks snapshot freshness.

## Reproduce the recorder prototype

```bash
python -m pip install -r python/requirements-core.txt
python python/run_retention_demo.py --latex paper/generated/smoke_results.tex
PYTHONPATH=python python -m unittest discover -s python/tests -p 'test_retention.py' -v

# Optional: build the manuscript with Tectonic installed.
cd paper
make pdf
```

The demo writes real encoded packets and evaluates decoded data. It reports
actual bytes, raw event/context coverage, onset error, and a separate coarse
summary-evidence result. All policies share a byte cap; they need not spend the
same number of bytes. The paper table is generated from the experiment output.

## What works

- **Verified data bundles:** `telemetry.bin`, channel-preserving `events.csv`, and
  a versioned `manifest.json` with SHA-256 integrity checks.
- **Strict C++ I/O:** explicit little-endian decoding, checked sizes/timestamps,
  finite measurements, and validation of every missing-data state transition.
- **Bounded runtime storage:** a preallocated frame pool with movable leases and
  a fixed-capacity blocking queue with explicit close-and-drain shutdown.
- **Multivariate detection:** training-only covariance, a symmetric eigensolver,
  and C++ PCA reconstruction scores verified against NumPy.
- **Preserved raw evidence:** an optional hash-bound sidecar stores within-cell
  sample counts and extrema without changing the v1 telemetry format.
- **Causal statistical detection:** Welford moments, rolling z-scores, and EWMA;
  history resets at partition boundaries and after unavailable data.
- **Reproducible evaluation:** event precision/recall/F1, false alarms per eligible
  day, detection delay, alarm duration, coverage, cell average precision, and
  uncertainty/sensitivity reports. Thresholds and provenance are frozen before test.
- **Verification:** Python/C++ numerical parity, malformed-input tests, concurrent
  queue/pool tests, sanitizer presets, and a GitHub Actions test matrix.

## Quick start

Requires CMake 3.24+, a C++20 compiler, and Python 3.12 or compatible. The initial
CMake configuration downloads GoogleTest; unit tests do not need the ESA dataset.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r python/requirements-core.txt

cmake --preset debug
cmake --build --preset debug --parallel
ctest --preset debug --output-on-failure
PYTHONPATH=python python -m unittest discover -s python/tests -v
```

The Python integration suite uses `build/debug/apps/cli/tae` by default. Set
`TAE_EXECUTABLE` to test another build. `release`, `asan` (address + undefined
behaviour), and `tsan` presets are also available. See the
[development guide](docs/development.md).

## Convert and verify real telemetry

Place the trusted official [ESA-ADB Mission1 data](https://doi.org/10.5281/zenodo.12528696)
under `data/ESA-Mission1/`, including channel archives 41–46, `labels.csv`, and
`anomaly_types.csv`. Raw data and large generated artifacts stay out of Git.

```bash
cmake --preset release
cmake --build --preset release --parallel

python python/convert_esa.py data/ESA-Mission1 --output data/processed/telemetry.bin
python python/dataset.py data/processed
./build/release/apps/cli/tae verify data/processed/telemetry.bin

# Independent vectorized comparison of every exported frame with source data.
python python/verify_export.py data/ESA-Mission1 data/processed
```

The converter uses UTC 30-second cells, retains the last observation in each cell,
and forward-fills at most five empty cells. Longer gaps remain unavailable. Frames
become available at the **end** of their cell. Labels preserve original timestamps
and channel-specific intervals. The source loader uses pickle: only load trusted
official archives. See the [data pipeline guide](docs/data-pipeline.md).

The checked local export contains **14,728,320 frames**, **1,255 event-channel
intervals**, and **118 distinct events**. All reference statistics and all binary32
measurement bits match the independent source comparison. The binary is
412,393,024 bytes. [Verification artifact](docs/results/m1-validation.json).

## Run the statistical baseline

```bash
# Fit normalization on eligible training observations; select validation thresholds.
python python/evaluate.py data/processed

# After freezing configuration, explicitly evaluate the held-out partition.
python python/evaluate.py data/processed --test
```

Training covers 2000–2007, validation 2008–2010, and test 2011–2013. Normalization
excludes labelled anomalies, rare events, communication gaps, and imputed values.
Rolling history never crosses partition boundaries. Labels are evaluation metadata,
not detector inputs.

Results are written under `data/results/statistical/`. `selection.json` freezes
validation thresholds with dataset, executable, and evaluation-script hashes.
Changing the configuration requires a new `--output` directory. Repeated test use
is recorded in `runs.jsonl` and must be described as exploratory.

See the [baseline guide](docs/statistical-baseline.md) and
[evaluation policy](docs/decisions/0003-statistical-baseline-and-evaluation.md).
These custom event metrics are not the official ESA hierarchical benchmark score.

On the frozen local test run, rolling z-score detected **10 of 13 events**
(F1 0.8696), and EWMA detected **6 of 13** (F1 0.6316), each with zero unmatched
alarm episodes. About 1.90% of test cells were excluded or unscorable. The small
event count and alarm durations limit interpretation; see the complete
[results and caveats](docs/results/README.md).

## Compare detectors and inspect alarms

```bash
python python/export_features.py data/ESA-Mission1 data/processed
python python/run_comparison.py data/processed
```

The comparison selects PCA rank and thresholds on validation under a default
budget of one false alarm episode per 100 eligible days. All models share the same
observed-cell exposure. A five-cell hold keeps short usable missing gaps from
fragmenting one incident; held cells receive no detection credit. A strict no-hold
control, alarm catalogs with channel evidence, and always-on/off controls expose
the effects on workload. Historical M2 results remain unchanged.

See the [comparison guide](docs/evidence-comparison.md) for reproduction, artifact
formats, and limitations. New reporting on the previously examined test split
requires an explicit `--exploratory-test` flag.

In the validation-only comparison at the default budget, z-score detects 10/11
events with 9 false-alarm episodes; PCA detects 8/11 with 2. PCA has much longer
alarm duration, and raw-extrema scores do not beat their matched retained-value
control. See the [full comparison and plot](docs/results/README.md#pca-and-preserved-evidence-comparison-validation-only).

## Architecture

```text
ESA Mission1 channels + annotations
                |
      Python conversion + manifest
                |
     Verified dataset bundle
                |
      C++ validating reader
                |
  Train-only normalization -> statistical + PCA scores
                                      |
                         Python event evaluation
                                      |
                   Frozen selection + auditable reports
```

`FramePool` and `BoundedQueue` are independently tested building blocks for the
later threaded replay pipeline; they are not required by the single-threaded scorer.

## Repository map

| Path | Responsibility |
| --- | --- |
| `include/tae/io/`, `src/io/` | Binary format, state validation, streaming reader |
| `include/tae/runtime/` | Frame pool and bounded queue |
| `include/tae/detectors/`, `src/detectors/` | Welford moments, normalization, statistical and PCA scores |
| `include/tae/math/`, `src/math/` | Online covariance and symmetric eigendecomposition |
| `apps/cli/` | Version, full-file validation, scoring commands |
| `python/convert_esa.py`, `python/dataset.py` | Conversion, annotations, schema and integrity checks |
| `python/retention/`, `python/run_retention_demo.py` | Budgeted native-observation capture and protocol checks |
| `paper/` | LaTeX manuscript, generated results table, and claim/evidence ledger |
| `python/evaluate.py` | Historical statistical baseline evaluation |
| `python/export_features.py`, `python/run_comparison.py` | Raw extrema and workload-constrained comparisons |
| `python/verify_export.py` | Independent full-source parity check |
| `tests/`, `python/tests/` | C++ and Python correctness/integration tests |
| `docs/decisions/`, `docs/results/` | Design contracts and small reproducible result artifacts |

## Research roadmap

| Milestone | Focus | Status |
| --- | --- | --- |
| R0–R1 | Recorder contract, reference policies, synthetic protocol checks, LaTeX draft | Implemented |
| R2 | Native mission replay, independent receivers, multi-budget retention comparison | Next |
| R3 | Contact/loss simulation, C++ recorder integration, CPU/memory measurements | Planned |
| R4 | Frozen independent-mission evaluation and operational review | Planned |

[Detailed protocol and evidence limits](docs/retention-research.md).

## Supporting detector-engine roadmap

| Milestone | Focus | Status |
| --- | --- | --- |
| M0 | Exploration and data/format decisions | Complete |
| M1 | Verified real-data export, binary I/O, frame pool, bounded queue | Complete |
| M2 | Statistical detectors and reproducible evaluation harness | Complete |
| M3–M4 | Fixed six-channel covariance/eigensolver and PCA with NumPy parity | Implemented |
| M5 | Autoencoder or forecasting receiver, when justified by retention experiments | Deferred |
| M6–M7 | Threaded replay and SPSC queue comparison | Planned |
| M8–M9 | Profiling, optimization, broader benchmarks and evaluation | Planned |
| M10–M11 | Optional dashboard and presentation | Optional |

## Limits and research questions

Keep-last aggregation can erase short anomalies. Forward-fill can make telemetry
look artificially stable. A rolling model can absorb sustained faults, while a
fixed reference can mistake operating-mode changes for faults. Six synchronized
channels and 13 test anomaly events provide limited evidence for generalization.
Latency samples measure detector updates on one local machine, not end-to-end
flight-system guarantees.

Current extensions and further experiments are outlined in
[research directions](docs/research-directions.md): preserve within-cell variation,
compare frozen and adaptive references, separate data quality from fault evidence,
and evaluate operator workload alongside detection accuracy.
