# Telemetry Anomaly Engine

A C++20 project for replaying spacecraft telemetry and evaluating anomaly detectors. The emphasis is on building the numerical and systems components directly, validating them against reference implementations, and measuring correctness and performance.

**Status:** M0 design and exploration complete. **M1 data pipeline in progress:** the binary decoder, streaming reader, Python writer, preprocessing logic, real-data conversion command, and Python-to-C++ fixture tests are implemented. The full ESA-ADB export has **not been verified in this repository**; event/manifest export, dataset-level hash verification, frame pools, queues, and anomaly detectors remain to be implemented.

This is an engineering and benchmarking project, not flight-qualified software. “Real-time” refers to planned accelerated replay and measured pipeline throughput, not the original approximately 30-second telemetry cadence.

## Project goals

- **Deterministic replay:** Convert ESA-ADB Mission1 channels 41–46 into fixed-rate six-channel telemetry frames and replay them at accelerated speeds.
- **Three anomaly detectors:** Rolling statistics (Welford, z-score, EWMA), PCA reconstruction error (custom covariance and symmetric eigensolver), and a dense autoencoder trained in PyTorch with handwritten C++ inference kernels.
- **Systems engineering:** Preallocated frame storage, bounded queues, `std::jthread` pipeline stages, deterministic shutdown, and mutex-queue versus SPSC ring-buffer benchmarks.
- **Verification:** Independent Python/C++ binary-format tests, sanitizers, numerical parity checks, and eventually event-level accuracy and latency distributions.

The detectors, threaded pipeline, evaluation harness, and performance benchmarks are future work.

## Current implementation

| Area | Implemented | Next |
| --- | --- | --- |
| Dataset exploration and format decisions | Mission1 exploration; [ADR 0001](docs/decisions/0001-data-split-and-preprocessing.md) and [ADR 0002](docs/decisions/0002-binary-telemetry-format.md) | Validate results on the complete converted artifact |
| C++ binary I/O | Explicit little-endian header/frame decoding, frame-sequence validation, streaming `TelemetryReader`, malformed-input tests | Dataset manifest verification |
| Python binary I/O | Binary writer, sequence validation, temporary-file write and atomic replacement | Complete dataset metadata export |
| Cross-language checks | Python-generated 12-frame fixture read by C++, exact binary32/mask/staleness checks and targeted corruption tests | Full-file parity against real Mission1 |
| ESA conversion | Channel loading, timestamp-alignment validation, 30-second grid, keep-last collision policy, five-cell forward-fill, binary export command | Run and verify real export; add events.csv and manifest.json |
| Runtime and ML | CMake library and version-only CLI | Frame pool, bounded queue, statistical detector, PCA, autoencoder |

The most recently reported local result was **60/60 C++ tests passing**, before the additional Python converter tests. The repository contains test source files, but no claim is made here that the current commit has been tested on CI or that full-data conversion has completed.

## Quick start

### C++ requirements

CMake 3.24+, a C++20 compiler, and network access on the first configuration so CMake can download GoogleTest.

```bash
cmake --preset debug
cmake --build --preset debug
ctest --preset debug --output-on-failure
./build/debug/apps/cli/tae
```

Other available configure/build/test presets are `release`, `asan` (address and undefined-behavior sanitizers), and `tsan` (thread sanitizer). Sanitizer availability is platform dependent. The CLI currently prints the project version; it does **not** yet run replay or anomaly detection.

### Python requirements and tests

Use a Python environment with dependencies from `python/requirements.txt`. From the repository root:

```bash
python -m pip install -r python/requirements.txt
PYTHONPATH=python python -m unittest discover -s python/tests -p "test_*.py" -v
```

The `PYTHONPATH=python` setting is intentional: test modules under `python/tests/` import `write_binary`, `preprocess`, and `convert_esa` as top-level modules. The C++ CMake test target generates the Python-written fixture automatically via `python/generate_fixture.py`.

Detailed commands, testing notes, and troubleshooting: [Development guide](docs/development.md).

## ESA-ADB data conversion

The project uses the [ESA Anomaly Detection Benchmark (ESA-ADB)](https://doi.org/10.5281/zenodo.12528696), Mission1 channels **41–46**. The raw dataset is **not** committed to Git. Place the trusted official Mission1 files under `data/ESA-Mission1/` with `channels/channel_41.zip` through `channel_46.zip`.

From the repository root, using the Python environment:

```bash
python python/convert_esa.py data/ESA-Mission1 --output data/processed/telemetry.bin
```

The converter verifies that the six input channels have exactly matching timestamps and that values can be encoded as finite binary32 measurements. It retains the **last** observation in each UTC 30-second cell, fills at most five consecutive missing cells, then emits unavailable frames until a real observation arrives.

The converter currently writes **only `telemetry.bin`**. The planned `events.csv`, `manifest.json`, their schema checks, and SHA-256 verification remain outstanding. Do not treat a lone `telemetry.bin` as a complete, verified v1 dataset bundle.

See the [Data pipeline guide](docs/data-pipeline.md) for source layout, format details, reference statistics, and verification steps.

## Architecture

```text
Official ESA-ADB Mission1 channels
                |
        Python channel loader
                |
    Timestamp alignment and grid
                |
      Python binary frame writer
                |
         telemetry.bin
                |
     C++ validating TelemetryReader
                |
        Future replay pipeline
                |
       Future anomaly detectors
                |
         Future evaluation
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `include/tae/io/`, `src/io/` | C++ binary-format decoders, validator, and reader |
| `apps/cli/` | Current version-only CLI; replay CLI planned |
| `tests/` | GoogleTest unit and Python-to-C++ integration tests |
| `python/convert_esa.py` | Real ESA-ADB channel loading and binary export |
| `python/preprocess.py`, `python/write_binary.py` | Gridding/quality-state logic and binary serialization |
| `python/tests/` | Python `unittest` test suite |
| `python/exploration/` | Dataset investigation scripts; trusted-source pickle loader |
| `docs/development.md` | Build and testing workflow |
| `docs/data-pipeline.md` | Conversion, format, and integrity checklist |
| `docs/decisions/` | Design decisions and data/evaluation constraints |
| `data/`, `models/` | Local, gitignored datasets and model artifacts |

## Roadmap

| Milestone | Focus | Status |
| --- | --- | --- |
| M0 | Dataset exploration, split/preprocessing policy, binary-format specification | Complete |
| M1 | Binary I/O, real-data export and verification, frame pool, fixed-capacity queue | In progress |
| M2 | Statistical anomaly detector and evaluation harness | Planned |
| M3–M4 | Numerical kernels and PCA detector | Planned |
| M5 | PyTorch-trained autoencoder and C++ inference parity | Planned |
| M6–M7 | Threaded replay and SPSC queue comparison | Planned |
| M8–M9 | Profiling, optimization, benchmarks, held-out evaluation | Planned |
| M10–M11 | Optional dashboard and presentation polish | Optional |

**Immediate next work:** Run and validate the real `telemetry.bin` export; preserve the original channel-specific annotations in `events.csv`; generate a checked `manifest.json`; then build the frame pool and bounded queue.

## Evaluation principles

Chronological partitions are train **2000–2007**, validation **2008–2010**, and test **2011–2013**. Model fitting uses eligible training data only; threshold tuning uses validation only. Rare-event and communication-gap labels remain separate from measurement availability and are excluded from primary false-alarm counts. Feature windows must not cross partition boundaries.

Planned reports include event-wise precision/recall/F1, false alarms per eligible day, detection delay, and p50/p95/p99 latency. With only 13 test anomaly events in the chosen subset, uncertainty and limitations will matter. These evaluation results have **not** been produced yet.

## Limitations

The synchronized six-channel format is specific to this Mission1 subset, not an arbitrary telemetry schema. Keep-last aggregation can discard a short anomaly if an ordinary observation arrives later in the same cell. Five-cell forward-fill is a documented baseline, not an optimized policy. The Python source loader uses pickle and should only open trusted official dataset archives.

For the complete wire format and data-design rationale, see [ADR 0002](docs/decisions/0002-binary-telemetry-format.md) and [ADR 0001](docs/decisions/0001-data-split-and-preprocessing.md).
