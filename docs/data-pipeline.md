# Data pipeline: ESA-ADB Mission1

This guide documents the implemented converter, its data contract, and what remains before a complete benchmark dataset is available. [ADR 0001](decisions/0001-data-split-and-preprocessing.md) defines the preprocessing and evaluation rules; [ADR 0002](decisions/0002-binary-telemetry-format.md) specifies the binary and metadata formats.

## Source layout

The local source directory is expected to contain at least:

```text
data/ESA-Mission1/
  channels/
    channel_41.zip
    channel_42.zip
    channel_43.zip
    channel_44.zip
    channel_45.zip
    channel_46.zip
  labels.csv
  anomaly_types.csv
```

The current binary converter needs the six channel archives. The label/type CSVs will be needed for the planned `events.csv` export. Source archives are local and gitignored.

The loader in `python/exploration/esa.py` reads each official ZIP entry as a pickled pandas Series. **Unpickling executes code; use only trusted official archives.**

## Current conversion command

From the repository root:

```bash
python -m pip install -r python/requirements.txt
python python/convert_esa.py data/ESA-Mission1 --output data/processed/telemetry.bin
```

The converter:

1. Loads `channel_41` through `channel_46` in that order.
2. Checks nonempty, strictly increasing reference timestamps, microsecond representability, and exact alignment of all six timestamp arrays.
3. Rejects nonfinite or binary32-unrepresentable measurements.
4. Maps observations to UTC 30-second cells and keeps the **last** observation in each occupied cell.
5. Emits a six-value frame for every grid cell, filling up to five consecutive missing cells and marking later missing cells unavailable.
6. Writes `telemetry.bin` through the validated Python writer, using a same-directory temporary file and atomic replacement on successful completion.
7. Checks the final byte length against the count computed from the grid.

The converter is implemented; a successful full-dataset run has **not** yet been independently confirmed. It currently loads a six-column NumPy measurement matrix in memory, while the subsequent frame iterator writes incrementally.

## Frame quality states

| State | Observed mask | Usable mask | Staleness | Measurement values |
| --- | --- | --- | --- | --- |
| Observed | `0x3F` | `0x3F` | 0 | Last observation in that 30-second cell |
| Forward-filled | `0x00` | `0x3F` | 1–5 | Bit-exact copy of most recent observed values |
| Unavailable | `0x00` | `0x00` | 6–65535 | Six canonical positive-zero binary32 values |

The first frame must be observed. The staleness counter saturates at 65535 and resets on a new observation. Cell availability occurs at **the end of the cell**; individual frame timestamps are reconstructed from the header:

```text
cell_start_us(i) = start_us + i * 30_000_000
available_us(i) = cell_start_us(i) + 30_000_000
```

The complete `telemetry.bin` consists of a 64-byte header followed by 28 bytes per frame. The header records the UTC start, frame count, 30-second period, six channels, and the validation/test split boundaries. See [ADR 0002](decisions/0002-binary-telemetry-format.md) for the exact byte offsets.

## Reference checks from exploration

The following numbers were measured during initial Mission1 exploration and are **checks**, not hardcoded constants:

| Measure | Reference |
| --- | ---: |
| Raw observations per channel | 15,381,169 |
| Full 30-second grid cells | 14,728,320 |
| Occupied cells | 14,642,408 |
| Empty cells | 85,912 |
| Cells with multiple observations | 733,166 |
| Expected binary size, if the observed span is reproduced | 412,393,024 bytes |

Investigate any discrepancies before relying on the binary artifact. Note that “cells with multiple observations” is a cell count; it is not the count of discarded raw samples.

## Dataset splits

| Partition | UTC interval | Intended usage |
| --- | --- | --- |
| Train | [2000-01-01, 2008-01-01) | Fit eligible normalization and model parameters |
| Validation | [2008-01-01, 2011-01-01) | Select thresholds and model parameters |
| Test | [2011-01-01, 2014-01-01) | Locked final evaluation |

Avoid feature-history leakage across boundaries. This is a downstream modeling requirement; the conversion step itself does not train a detector.

## Planned complete dataset bundle

The agreed v1 output is:

```text
data/processed/
  telemetry.bin
  events.csv
  manifest.json
```

**Only `telemetry.bin` is implemented by the current conversion command.** The other two files have specification but not working exporters.

`events.csv` must contain one record per original event-channel interval:

```text
event_id,channel,category,start_utc,end_utc
```

Keep original event IDs, channels, categories, and precise UTC boundaries. For positive-duration events use half-open intervals; zero-duration events label their containing grid cell. Rare events and communication gaps must not become ordinary negative labels merely because measurements are present.

`manifest.json` will declare format `TAE-DATASET` version 1, dataset and channel configuration, aggregation/fill parameters, and SHA-256 of the complete `telemetry.bin` and `events.csv`. Hash verification belongs to dataset opening and must occur outside measured inference timing. Hashes protect against accidental mismatch/corruption but do not authenticate a manifest that an attacker can rewrite.

## Verification still required

- Run the real conversion and compare all six reference statistics.
- Feed the complete binary to C++ `TelemetryReader` and scan **all** frames, not just the header.
- Preserve source event-channel labels and verify point events and boundary intersections.
- Validate the manifest schema and both hashes before the evaluation harness opens the dataset.
- Add explicit end-to-end tests for grid-boundary timestamp decisions, long outages, and consistency of the actual converted output.

The 12-frame Python-to-C++ fixture is a valuable interoperability test but does **not** substitute for a complete data-integrity check.
