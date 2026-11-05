# telemetry-anomaly-engine

A C++20 engine for detecting anomalies in spacecraft telemetry, evaluated on real
ESA telemetry (ESA-ADB). Work in progress.

## Build and test

```bash
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
./build/debug/apps/cli/tae
```

Other presets: `release`, `asan` (address + undefined behaviour sanitizers), `tsan`.
