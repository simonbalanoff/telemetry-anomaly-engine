# Development and testing

This guide describes the commands supported by the current repository. Work from the repository root unless stated otherwise.

## Toolchain

- CMake 3.24+ and a C++20 compiler.
- Python with the dependencies in `python/requirements-core.txt`.
- Network access for CMake's initial GoogleTest download.
- The sanitizer presets depend on compiler/platform support; development so far has been on macOS.

## Configure, build, and test C++

```bash
cmake --preset debug
cmake --build --preset debug
ctest --preset debug --output-on-failure
```

```bash
cmake --preset asan
cmake --build --preset asan
ctest --preset asan --output-on-failure
```

The presets `release` and `tsan` are defined in `CMakePresets.json` as well. ThreadSanitizer availability and compatibility are compiler/platform dependent.

The CLI supports version reporting and a complete binary scan:

```bash
./build/debug/apps/cli/tae
./build/debug/apps/cli/tae verify data/processed/telemetry.bin
```

For fitting, scoring, and event evaluation, use the [baseline workflow](statistical-baseline.md).

## Python tests

Python test files live in **`python/tests/`** and use the standard-library `unittest` runner. They import modules from the parent `python/` directory, so set `PYTHONPATH` explicitly when running from the repository root:

```bash
python -m pip install -r python/requirements-core.txt
PYTHONPATH=python python -m unittest discover -s python/tests -p "test_*.py" -v
```

To run one group of tests:

```bash
PYTHONPATH=python python -m unittest discover -s python/tests -p "test_preprocess.py" -v
PYTHONPATH=python python -m unittest discover -s python/tests -p "test_convert_esa.py" -v
PYTHONPATH=python python -m unittest discover -s python/tests -p "test_write_binary.py" -v
```

These scripts exercise Python serialization, grid/collision/missing-data behavior, timestamp alignment, and source-value validation with synthetic input or mocks. They do not download the full ESA dataset.

## Python-to-C++ fixture test

`tests/CMakeLists.txt` runs `python/generate_fixture.py` as a CMake custom command to produce a deterministic 12-frame binary file in the build directory. `tests/test_python_integration.cpp` reads that file through the actual `TelemetryReader`.

```bash
cmake --build --preset debug
ctest --preset debug -R PythonIntegration --output-on-failure
```

CMake finds a Python interpreter at configuration time. The fixture is regenerated when `python/generate_fixture.py` or `python/write_binary.py` changes. The suite checks exact decoded values, masks, staleness, timestamps, and selected malformed-input cases.

The 12-frame fixture uses **synthetic split timestamps** to make a short complete binary file testable by the current reader. It is not a real Mission1 production export; see the production-boundary requirement in [ADR 0002](decisions/0002-binary-telemetry-format.md). Tests explicitly select `HeaderPolicy::SyntheticFixture`; default production readers require the real split boundaries.

## Test layout

| Test path | Responsibility |
| --- | --- |
| `tests/test_telemetry_header.cpp` | Decode and reject invalid 64-byte headers |
| `tests/test_telemetry_frame.cpp` | Decode and validate six-channel 28-byte frames |
| `tests/test_telemetry_reader.cpp` | Stream real test files; file-size and sequence corruption |
| `tests/test_python_integration.cpp` | Read and compare the Python-generated golden fixture |
| `tests/test_runtime_statistical.cpp` | Rolling moment parity, resets, concurrent queue/pool behaviour |
| `python/tests/test_dataset_evaluation.py` | Metadata, event matching, threshold isolation, end-to-end C++ numerical parity |
| `tests/test_smoke.cpp` | Basic library/CLI build sanity |
| `python/tests/test_write_binary.py` | Serializer validation and atomic-write failure handling |
| `python/tests/test_preprocess.py` | Keep-last gridding and five-cell filling |
| `python/tests/test_convert_esa.py` | Six-channel loading, synchronization, grid statistics |

Current local verification: 75 C++ tests pass in debug, release, ASan/UBSan, and TSan builds; 89 Python tests pass locally, including available CLI parity checks. Earlier parity verification also covered an ASan build. The GitHub Actions workflow is configured but has not been run remotely in this session.

## Working with actual ESA-ADB data

The files under `python/exploration/` and the main converter expect a local official Mission1 download. The shared loader `python/exploration/esa.py` unpickles channel archives; **only use trusted dataset files**.

```bash
python python/convert_esa.py data/ESA-Mission1 --output data/processed/telemetry.bin
```

Refer to [Data pipeline](data-pipeline.md) for the exact expected input layout and output verification. Neither `data/` nor `models/` artifacts should be committed.

## Troubleshooting

- **Python `ModuleNotFoundError` for `write_binary`, `preprocess`, or `convert_esa`:** Run discovery with `PYTHONPATH=python` from the repository root.
- **`TAE_FIXTURE_PATH` missing in clangd:** Reconfigure CMake, then refresh the clangd compile database. The macro is set through `target_compile_definitions` in `tests/CMakeLists.txt`.
- **GoogleTest warning inside its own headers:** Distinguish dependency warnings from compiler errors in project source.
- **Missing Mission1 files:** Verify `data/ESA-Mission1/channels/channel_41.zip` through `channel_46.zip` exist before conversion.
- **Sanitizer failure:** Determine whether the sanitizer is supported on the current compiler and OS before diagnosing a project memory or threading bug.

## Definition of done for the data-pipeline portion of M1

1. Python unit tests and C++ unit/integration tests pass.
2. Official Mission1 timestamps match across all six channels.
3. Real binary output has the expected frame count and physical length.
4. The C++ reader can consume the complete output and validate every frame.
5. Source event-channel annotations are exported without flattening into global labels.
6. The manifest records the expected schema and SHA-256 hashes; opening code verifies them before benchmark timing.

All six checks pass on the complete local export. The source-parity and C++ scan results are preserved in [M1 verification](results/m1-validation.json).

## M1/M2 verification and formatting

The Python suite includes label boundaries, metadata corruption, event matching,
NumPy/C++ score parity, train-only normalization, split resets, and outage recovery.
The C++ suite includes concurrent queue/pool transfer and MPMC queue tests.

```bash
TAE_EXECUTABLE=build/release/apps/cli/tae PYTHONPATH=python python -m unittest discover -s python/tests -v
cmake --preset tsan
cmake --build --preset tsan --parallel
ctest --preset tsan --output-on-failure
```

CI configures debug, release, and ASan/UBSan on Ubuntu. Local checks also cover
ThreadSanitizer when supported. Dataset conversion and held-out evaluation require
local official data and are intentionally separate from CI.

New C++ components follow `.clang-format`. Python additions use Black; optional
development tools are listed in `python/requirements-dev.txt`. The original
`python/requirements.txt` includes heavier exploratory and future ML dependencies;
these are unnecessary for M1/M2.

## PCA and raw-evidence regression tests

`tests/test_pca.cpp` checks covariance, eigenvector orthogonality, matrix
reconstruction, invalid inputs, and relationship-breaking faults. The Python suite
compares every PCA rank with independent NumPy decomposition through the real CLI,
checks unchanged legacy score columns, validates the raw-extrema sidecar, and tests
alarm holding without granting missing-cell detection credit. All new comparison
paths use only `requirements-core.txt`; plotting is an optional Matplotlib tool.

The [comparison workflow](evidence-comparison.md) exercises complete local telemetry.
Its current default is validation only, with explicit exploratory test reporting.

## Retention research prototype and manuscript

The initial `python/retention/` package is a Python research prototype separate
from the C++ detector engine. Run its complete synthetic replay and generated
paper table with:

```bash
python python/run_retention_demo.py --latex paper/generated/smoke_results.tex
PYTHONPATH=python python -m unittest discover -s python/tests -p 'test_retention.py' -v
make -C paper pdf
```

The last command requires Tectonic. CI additionally has a paper job that regenerates
the table and builds the standard LaTeX source with latexmk. Remote CI execution
has not been observed in this session. See `docs/retention-research.md` for the
byte contract and `paper/claims.md` for the distinction between software checks
and unmeasured mission benefit.

## CI portability fixes

The reported Ubuntu/GCC job failed because an unbraced conditional enclosed a
GoogleTest macro with its own conditional expansion. `test_pca.cpp` now uses explicit
braces. The paper job failed on `enumitem.sty`; the manuscript did not use a list
requiring that package, so the unused `enumitem`/`setlist` preamble was removed.
The matrix uses `fail-fast: false` to retain independent job diagnostics. Fixes
are locally checked; a new remote CI run is needed after the changes are pushed.

## Randomized retention comparison

The Python suite checks reservoir inclusion across positions, seed reproducibility,
epoch isolation, score independence, missed targets, caps, decoding, and an end-to-end
seeded comparison on a small source. The study reuses the completed native pilot's
receiver model and validates reference hashes before replay. See
`docs/results/randomized-retention.md` for commands and the meaning of seed ranges.

Cross-mission bundle validation, code/input locks, training/evaluation split isolation,
label-independent capture, decoded budget checks, and paired ablation replay are covered
by `python/tests/test_retention_transfer.py`. See [the protocol](cross-mission-evaluation.md).
