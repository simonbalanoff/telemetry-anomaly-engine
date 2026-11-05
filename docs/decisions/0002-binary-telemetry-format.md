# ADR 0002: Binary telemetry interchange format

- **Status:** Accepted for v1 design; implementation and test verification pending
- **Date:** 2026-11-04
- **Related:** [ADR 0001](0001-data-split-and-preprocessing.md)
- **Scope:** Six synchronized ESA-ADB Mission1 telemetry channels (41–46), Python converter, C++20 reader, and evaluation metadata

## Decision

The converter produces one dataset directory with three files:

```text
data/processed/
  telemetry.bin
  events.csv
  manifest.json
```

`telemetry.bin` contains time-aligned measurements and quality state, but **no anomaly labels**. `events.csv` preserves per-channel event annotations and precise timestamps. `manifest.json` records preprocessing parameters and SHA-256 hashes of both content files. Do not supply labels or the manifest to the timed inference stage.

This is a deliberately fixed **version 1**, not a general-purpose telemetry serialization framework. All multibyte fields are packed without padding, encoded little-endian. Integers have the stated widths; floating-point values are IEEE-754 binary32. Code must read/write individual fields explicitly, not dump C++ structs or rely on host alignment.

## telemetry.bin: 64-byte header

| Byte offset | Bytes | Type | Name | v1 requirement |
| ---: | ---: | --- | --- | --- |
| 0 | 4 | ASCII | magic | `TAE1` |
| 4 | 2 | uint16 | version | 1 |
| 6 | 2 | uint16 | header_size | 64 |
| 8 | 4 | uint32 | channel_count | 6 |
| 12 | 4 | uint32 | period_ms | 30000 |
| 16 | 8 | int64 | start_us | Unix microseconds UTC, first **cell start** |
| 24 | 8 | uint64 | frame_count | Positive; fully fits available file |
| 32 | 8 | int64 | validation_start_us | 2008-01-01 00:00:00 UTC |
| 40 | 8 | int64 | test_start_us | 2011-01-01 00:00:00 UTC |
| 48 | 4 | uint32 | frame_size | 28 |
| 52 | 4 | uint32 | reserved32 | 0 |
| 56 | 8 | uint64 | reserved64 | 0 |

The v1 reader must reject wrong magic, version, sizes, channel count, sample period, reserved fields, or invalid split order. Require `start_us` to be aligned to a 30-second UTC cell. Require `start_us < validation_start_us < test_start_us` and both split boundaries to fall **within or at the end of** the represented frame interval, on exact cell boundaries. A production export must include all three partitions; synthetic test fixtures may use a separately designated test-only header validation policy rather than quietly accepting fake production boundaries.

For frame index `i` (zero-based):

```text
cell_start_us(i) = start_us + i * 30_000_000
available_us(i)  = cell_start_us(i) + 30_000_000
```

The file contains **every grid cell** from `start_us` through index `frame_count-1`, including missing cells. It does not encode an individual timestamp in each frame. Replay and detection delay use `available_us`; labels retain their exact UTC times.

Before allocating, reading, or computing timestamps, check integer overflow for `64 + frame_count * 28` and `start_us + frame_count * 30_000_000`. Require the physical file size to equal `64 + frame_count * 28` exactly: neither truncated nor trailing data is accepted.

## telemetry.bin: 28-byte frame

| Byte offset within frame | Bytes | Type | Name |
| ---: | ---: | --- | --- |
| 0 | 24 | float32[6] | `values`, ordered channels 41, 42, 43, 44, 45, 46 |
| 24 | 1 | uint8 | `observed_mask` |
| 25 | 1 | uint8 | `usable_mask` |
| 26 | 2 | uint16 | `staleness` (number of consecutive missing cells, saturated) |

Bit 0 is channel 41; bit 5 is channel 46. For this v1 **synchronized** dataset, masks can be only `0x00` or `0x3F`. No upper bits are permitted. v1 does not support per-channel missingness; a future revision may.

Allowed states:

| State | observed_mask | usable_mask | staleness | values |
| --- | --- | --- | --- | --- |
| Observed | `0x3F` | `0x3F` | 0 | Six finite raw measurements after keep-last aggregation |
| Filled | `0x00` | `0x3F` | 1–5 | Exact previous **observed** values |
| Unavailable | `0x00` | `0x00` | 6–65535 | Six canonical positive `+0.0f` |

The first frame must be observed. Every subsequent observed frame resets staleness to zero; every non-observed frame increments it by one, with saturation at 65535. Filled frames copy the last **observed** values bit-for-bit; they do not compound or transform an earlier fill. After five missing cells, a frame is unavailable until the next real observation. Unavailable frame values must be the all-zero binary32 bit pattern. Valid observed and filled values must be finite (zero is a legitimate measurement). Reconstructed readers validate the mask/state transitions and fill identity, not just individual bytes.

The shared staleness counter is sufficient only because the converter verifies all six channels have aligned timestamps. If this assumption fails, conversion stops rather than silently inventing synchronization.

## events.csv

Use UTF-8 CSV with a header and exactly these columns, in this order:

```text
event_id,channel,category,start_utc,end_utc
```

- One row per **source event-channel interval**, preserving event ID and each channel's own start/end.
- `channel` is an integer in `[41,46]`.
- `category` is one of `Anomaly`, `Rare Event`, `Communication Gap`.
- `start_utc` and `end_utc` use ISO 8601 UTC with a trailing `Z`, with microsecond precision (e.g. `2013-11-19T14:57:17.751000Z`).
- Require start <= end, timestamps within the covered telemetry period, valid event IDs, and no duplicate identical event-channel rows. Preserve more than one row per event when source labels contain distinct intervals; do not deduplicate by event ID alone.
- Apply an interval intersection rule to **half-open** `[start, end)` for positive-duration events. A zero-duration point event labels its containing cell (`floor(start, 30s)`), including a point exactly on a cell boundary.
- Keep the event ID and category available to the evaluation harness; derive channel-wise and global grid flags without discarding the original rows.

`events.csv` is evaluation metadata, never a feature input. Event matching/tolerance, alarm deduplication, and eligibility rules remain governed by ADR 0001 and later evaluation decisions.

## manifest.json

Use UTF-8 JSON with these required v1 fields:

```json
{
  "format": "TAE-DATASET",
  "version": 1,
  "dataset": "ESA-ADB/Mission1",
  "channels": [41, 42, 43, 44, 45, 46],
  "grid_period_ms": 30000,
  "collision_policy": "last",
  "max_forward_fill_cells": 5,
  "time_unit": "unix_microseconds_utc",
  "files": {
    "telemetry": {
      "path": "telemetry.bin",
      "sha256": "<64 lowercase hex characters>"
    },
    "events": {
      "path": "events.csv",
      "sha256": "<64 lowercase hex characters>"
    }
  }
}
```

Hashes above are placeholders; the converter computes actual SHA-256 digests of the **complete output file bytes** and writes the manifest **last**. Do not embed a hash of the manifest in itself.

The v1 reader verifies the required fields against header facts and the configured preprocessing policy; reject mismatches and unknown schema versions. File paths must be the exact v1 relative basenames `telemetry.bin` and `events.csv`, not arbitrary absolute or parent-relative paths. Validate filenames and hashes before accessing referenced paths.

SHA-256 detects accidental mutation or a mismatched pair of files. It does **not** authenticate adversarially modified content if the attacker can rewrite the manifest. Integrity verification runs during dataset opening, outside latency/throughput benchmark timing.

## Expected size

The observed grid occupancy investigation reported **14,728,320** grid cells. If conversion emits exactly that full span, the v1 byte count is:

```text
64 + 14,728,320 * 28 = 412,393,024 bytes
```

This is a **conditional expectation** to verify against the actual converter's first/last grid cell, not an instruction to hard-code the frame count. Labels and manifest add separate, small files.

## Validation checklist

### Header and file size

- [ ] Accept independently constructed valid v1 header and exact-size payload.
- [ ] Reject wrong magic, version, header length, frame size, sample period, and channel count.
- [ ] Reject nonzero reserved fields, misaligned start, invalid split ordering or boundary alignment.
- [ ] Reject truncated header, truncated payload, and trailing bytes.
- [ ] Reject multiplication/addition overflow when calculating expected size or final timestamp; do not allocate from unchecked counts.

### Frame state machine

- [ ] Accept observed values (including legitimate zero) and exact 5-cell fill sequences.
- [ ] Reject invalid mask bits, mixed masks unsupported in v1, nonfinite usable values, and invalid observed staleness.
- [ ] Reject fill beyond cell 5, wrong fill values, staleness jumps, and nonzero/unusual bit patterns in unavailable frames.
- [ ] Accept the missing-staleness saturation rule at 65535.
- [ ] Require first frame to be observed and check state reset after an extended gap.

### Labels and manifest

- [ ] Retain separate event/channel intervals, including point events, channel-specific spans, and UTC fractions.
- [ ] Verify correct labels at exact cell boundaries (point and positive-duration cases).
- [ ] Reject invalid categories/channels, backward/out-of-range intervals, duplicate records, malformed CSV, or inconsistent event metadata.
- [ ] Reject missing files, incorrect SHA-256 digests, manifest/header conflicts, and unsafe or unexpected file paths.
- [ ] Ensure label parsing never affects inference outputs or measured inference latency.

### Cross-language round-trip

- [ ] Python creates a known little-endian byte fixture; independently written C++ parser recovers exact field values.
- [ ] C++ parses independently authored golden bytes; do not use only Python-written data as the oracle.
- [ ] Test exact binary32 bit patterns for serialization; use numerical tolerances later for ML math, not file-format bytes.
- [ ] Mutate one byte of a valid header/frame/payload and verify deterministic rejection when the byte breaks a specified invariant or the manifest hash.

## Synthetic fixture definition

Design a 12-frame series beginning at an aligned UTC midnight, with the following states:

```text
index:       0  1  2  3  4  5  6  7  8  9 10 11
state:       O  O  F  F  F  F  F  M  M  O  O  O
staleness:   0  0  1  2  3  4  5  6  7  0  0  0
```

`O` means observed, `F` means filled, and `M` means unavailable. Include six distinct measurement values on observed rows, a legitimate measured zero, and different values after observation resumes. Frames 2–6 must exactly copy frame 1; frames 7–8 must contain `+0.0f` in every measurement slot.

Because the fixed production split boundaries cannot both fall within a 12-frame midnight fixture, test **header split validation separately** using a synthetic full-span header whose timestamp range includes both 2008 and 2011. Do not relax the production header rules merely to fit a short example; for short frame-state tests, directly invoke the frame decoder/state validator on fixture bytes rather than presenting the 12-frame series as a complete valid production file.

Include independent tests for a 30-second cell with three raw observations and a labelled point at the final observation, plus events exactly on cell boundaries. Validate precise UTC ordering and correct 30-second *availability* timestamps.

## Scope boundaries

- No compression, generic tensors, memory-mapped reader, arbitrary-channel schema, or per-frame timestamps in v1.
- No inference-time access to labels.
- No direct C++ struct reinterpretation of on-disk bytes.
- Parser design must clearly distinguish malformed input from EOF and avoid unbounded allocation.
- A later ADR can change the format; old files remain versioned rather than silently reinterpreted.

**Next milestone:** Implement the Python v1 writer and the C++20 validating reader against the fixtures, then test round-trip compatibility. Review their API designs before coding.
