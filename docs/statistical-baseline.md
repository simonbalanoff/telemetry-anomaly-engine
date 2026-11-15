# Statistical baseline: run and inspect

The supported benchmark entry point verifies the dataset bundle before fitting
or scoring. C++ computes the detector scores; Python performs eligibility masking,
validation-only threshold selection, and event-level reporting.

## Build and validate

```bash
python -m pip install -r python/requirements-core.txt
cmake --preset release
cmake --build --preset release --parallel
python python/evaluate.py data/processed
```

Defaults are a 120-cell window (one hour) and EWMA alpha 0.05. See
[ADR 0003](decisions/0003-statistical-baseline-and-evaluation.md) for the complete
policy, formulas, warm-up, interval matching, and selection rules.

Outputs under `data/results/statistical/`:

| File | Purpose |
| --- | --- |
| `train_mask.bin` | One byte per frame; 1 marks a label-eligible training cell |
| `scores.bin` | Two little-endian float64 scores per frame; NaNs mean no score |
| `runtime.json` | Training moments, detector settings, frame counts, sampled latency |
| `selection.json` | Frozen validation thresholds, candidate results, provenance hashes |
| `validation_report.json` | Validation event metrics, coverage, delay, and sensitivity |
| `runs.jsonl` | Append-only record of completed reports |

Use a new output directory for a changed detector or evaluation script:

```bash
python python/evaluate.py data/processed --window 240 --output data/results/window-240
```

Do model selection on validation. Once configuration is frozen, explicitly request
the held-out report:

```bash
python python/evaluate.py data/processed --test
```

This requires an existing matching selection and writes `test_report.json`. It
never tunes thresholds against test labels. Repeated test use is recorded and
must be described as exploratory. Test evaluation does not imply deployment safety.

## Inspect low-level components

```bash
python python/dataset.py data/processed
./build/release/apps/cli/tae verify data/processed/telemetry.bin
```

The Python command verifies manifest policy, paths, hashes, header, and event
schema. The C++ command scans the entire binary, validating every frame and quality
transition. The low-level `tae score` command accepts a prepared training mask;
callers must first verify the bundle. The evaluation driver handles this contract.

Short synthetic integration tests explicitly select `HeaderPolicy::SyntheticFixture`
(or the CLI's `--synthetic-fixture` test flag). Production readers reject synthetic
split boundaries by default.

## Runtime components

`FramePool` preallocates frame storage and returns movable leases. Destroying a
lease returns the slot; the pool must outlive all leases. `acquire()` is nonblocking
and returns an empty optional on exhaustion. `BoundedQueue<T>` preallocates a
fixed-capacity mutex-protected ring. Producers and consumers block until progress
or closure; `close()` wakes all waiters, rejects further pushes, and lets consumers
drain remaining items. Owners must close and join workers before destroying a queue.

These components are tested together under concurrency. The M2 scorer is deliberately
single-threaded; threaded replay and the SPSC comparison remain later milestones.
