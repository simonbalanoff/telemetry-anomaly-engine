# Telemetry Anomaly Engine

A C++20 project for replaying spacecraft telemetry, detecting anomalous behavior, and measuring detection performance. The goal is to build and validate the underlying numerical and systems components rather than wrap a prebuilt inference engine.

**Status:** M0 (data exploration and design) completed; M1 implementation is next. The repository currently contains the C++ build/test skeleton, Python dataset exploration tools, and engineering decision records. The telemetry loader, detectors, and threaded pipeline are **not implemented yet**.

## Project goals

- **Telemetry replay:** Convert six ESA-ADB Mission1 channels into synchronized, fixed-rate frames and replay them at accelerated rates.
- **Three detectors:** A rolling statistical baseline (Welford, z-score, EWMA), PCA reconstruction error (custom covariance and symmetric eigensolver), and a dense autoencoder trained with PyTorch but executed using handwritten C++ inference kernels.
- **Systems engineering:** Bounded queues, a preallocated frame pool, `std::jthread` pipeline stages, deterministic output, clean shutdown, and a mutex-queue versus SPSC ring-buffer comparison.
- **Verification:** Cross-check numerical results against NumPy, Eigen, and PyTorch; test malformed binary inputs; use sanitizers, reproducible experiments, and latency/throughput benchmarks.

The real telemetry is relatively slow. “Real-time” in this project means **accelerated replay and measured pipeline performance**, not an assertion of flight-ready deployment.

## Dataset and design

The project uses the [ESA Anomaly Detection Benchmark (ESA-ADB)](https://doi.org/10.5281/zenodo.12528696), focused on Mission1 channels **41–46**. The raw dataset is not stored in Git.

Exploration of the locally downloaded subset identified a nominal 30-second sampling cadence, occasional additional observations within a cell, and missing telemetry intervals. Those observations informed the initial data contract:

- Align samples to a 30-second UTC grid and use the last observation in each cell as the primary aggregation policy.
- Forward-fill at most five consecutive empty cells, while preserving observed, filled, and unavailable states.
- Use chronological train (2000–2007), validation (2008–2010), and test (2011–2013) partitions, with controls against feature-history leakage.
- Preserve exact per-channel event labels separately from the data consumed by the detectors.
- Exchange processed telemetry in a documented binary format: 64-byte header, 28-byte frames, implicit timestamps, and a SHA-256 manifest.

These are initial benchmark policies, not claims that every parameter has been optimized. See the decision records for evidence, limitations, and validation requirements:

- [ADR 0001 — Data split and preprocessing](docs/decisions/0001-data-split-and-preprocessing.md)
- [ADR 0002 — Binary telemetry format](docs/decisions/0002-binary-telemetry-format.md)

## Roadmap

| Milestone | Focus | Status |
| --- | --- | --- |
| M0 | Dataset exploration, split/preprocessing decisions, binary format design | Complete |
| M1 | Binary converter/reader, frame pool, fixed-capacity queue | Next |
| M2 | Statistical detector and evaluation harness | Planned |
| M3–M4 | Tensor operations and PCA detector | Planned |
| M5 | Autoencoder inference and PyTorch parity | Planned |
| M6–M7 | Threaded pipeline and SPSC queue comparison | Planned |
| M8–M9 | Profiling, optimization, benchmarks, final evaluation | Planned |
| M10–M11 | Optional dashboard and project polish | Optional / planned |

The next implementation task is a **validated C++ binary header decoder**, followed by frame decoding and a Python writer tested against independent synthetic fixtures.

## Build and test

Requirements: CMake 3.24+, a C++20 compiler, and network access for the first GoogleTest FetchContent download. Development is currently on macOS with Apple Silicon.

```bash
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
./build/debug/apps/cli/tae
```

Additional configure/build/test presets: `release`, `asan` (AddressSanitizer and UndefinedBehaviorSanitizer), and `tsan` (ThreadSanitizer). Sanitizer support depends on the compiler/platform. The current CLI prints a version string, and the current test is a smoke test; these commands do **not** yet run anomaly detection.

## Repository layout

| Path | Purpose |
| --- | --- |
| `include/tae/`, `src/` | C++ library and upcoming engine components |
| `apps/cli/` | Command-line entry point |
| `tests/` | GoogleTest tests |
| `python/` | ESA-ADB inspection and preprocessing experiments |
| `docs/decisions/` | Design decisions and validation contracts |
| `data/`, `models/` | Local datasets and generated model artifacts (not committed) |

## Evaluation principles

The eventual comparison will report event-wise detection quality, false alarms per eligible day, detection delay, and latency distributions (p50/p95/p99). Thresholds and fitted transforms will use training/validation data only; the held-out test set will be evaluated after the experiment is fixed. Limitations and uncertainty will be documented, including the small number of test anomalies and potential loss of short events during resampling.

The emphasis is on **correctness, reproducibility, and measured tradeoffs**—not promising unrealistically high detection accuracy or flight qualification.
