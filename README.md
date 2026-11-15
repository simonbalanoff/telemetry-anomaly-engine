# Telemetry Anomaly Engine

A C++20 engine for validating spacecraft telemetry and evaluating causal anomaly
detectors. Python prepares the ESA dataset and runs reproducible experiments;
C++ implements binary decoding, statistical kernels, and bounded runtime storage.

**M1 and M2 are implemented and locally validated.** The complete Mission1 export
has been checked against the original six channels, frame by frame. Rolling
z-score and EWMA baselines run end to end with training-only normalization,
validation-selected thresholds, and explicit held-out evaluation.

This is an engineering and benchmarking project, not flight-qualified software.
The current scorer is single-threaded. Threaded replay, PCA, and autoencoder
inference remain future milestones.

## What works

- **Verified data bundles:** `telemetry.bin`, channel-preserving `events.csv`, and
  a versioned `manifest.json` with SHA-256 integrity checks.
- **Strict C++ I/O:** explicit little-endian decoding, checked sizes/timestamps,
  finite measurements, and validation of every missing-data state transition.
- **Bounded runtime storage:** a preallocated frame pool with movable leases and
  a fixed-capacity blocking queue with explicit close-and-drain shutdown.
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
  Train-only normalization -> causal statistical scores
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
| `include/tae/detectors/`, `src/detectors/` | Welford moments, normalization, statistical scores |
| `apps/cli/` | Version, full-file validation, scoring commands |
| `python/convert_esa.py`, `python/dataset.py` | Conversion, annotations, schema and integrity checks |
| `python/evaluate.py` | Eligibility, threshold selection, event reports |
| `python/verify_export.py` | Independent full-source parity check |
| `tests/`, `python/tests/` | C++ and Python correctness/integration tests |
| `docs/decisions/`, `docs/results/` | Design contracts and small reproducible result artifacts |

## Roadmap

| Milestone | Focus | Status |
| --- | --- | --- |
| M0 | Exploration and data/format decisions | Complete |
| M1 | Verified real-data export, binary I/O, frame pool, bounded queue | Complete |
| M2 | Statistical detectors and reproducible evaluation harness | Complete |
| M3–M4 | Numerical kernels and PCA | Planned |
| M5 | PyTorch autoencoder and C++ inference parity | Planned |
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

The next research experiments are outlined in
[research directions](docs/research-directions.md): preserve within-cell variation,
compare frozen and adaptive references, separate data quality from fault evidence,
and evaluate operator workload alongside detection accuracy.
