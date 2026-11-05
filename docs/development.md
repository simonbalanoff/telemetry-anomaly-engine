# Development and testing

This guide describes the commands supported by the current repository. Work from the repository root unless stated otherwise.

## Toolchain

- CMake 3.24+ and a C++20 compiler.
- Python with the dependencies in `python/requirements.txt`.
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

The CLI currently prints a version string:

```bash
./build/debug/apps/cli/tae
```

It does not yet accept a dataset path or execute anomaly detection.

## Python tests

Python test files live in **`python/tests/`** and use the standard-library `unittest` runner. They import modules from the parent `python/` directory, so set `PYTHONPATH` explicitly when running from the repository root:

```bash
python -m pip install -r python/requirements.txt
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

The 12-frame fixture uses **synthetic split timestamps** to make a short complete binary file testable by the current reader. It is not a real Mission1 production export; see the production-boundary requirement in [ADR 0002](decisions/0002-binary-telemetry-format.md). Resolving the intended distinction between test-only and production header validation remains a contract-hardening task.

## Test layout

| Test path | Responsibility |
| --- | --- |
| `tests/test_telemetry_header.cpp` | Decode and reject invalid 64-byte headers |
| `tests/test_telemetry_frame.cpp` | Decode and validate six-channel 28-byte frames |
| `tests/test_telemetry_reader.cpp` | Stream real test files; file-size and sequence corruption |
| `tests/test_python_integration.cpp` | Read and compare the Python-generated golden fixture |
| `tests/test_smoke.cpp` | Basic library/CLI build sanity |
| `python/tests/test_write_binary.py` | Serializer validation and atomic-write failure handling |
| `python/tests/test_preprocess.py` | Keep-last gridding and five-cell filling |
| `python/tests/test_convert_esa.py` | Six-channel loading, synchronization, grid statistics |

User-reported local results included 60/60 C++ tests and 26 Python serializer tests at earlier stages. Those results are not a current CI guarantee; rerun the suites after changes.

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

Steps 4–6 have not yet been demonstrated on a fully converted dataset.
