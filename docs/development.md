# Development

The research pipeline runs entirely in Python. It needs no CMake, compiler,
native executable, or sanitizer setup. The former C++ detector runtime and its
CLI parity tests were retired because the retention experiments did not use them.
Historical detector artifacts remain documented in [results](results/README.md).

## Install and test

Use Python 3.12 or compatible from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r python/requirements-core.txt
PYTHONPATH=python python -m unittest discover -s python/tests -v
```

NumPy and pandas cover conversion, verification, capture, and evaluation. Plotting
uses optional Matplotlib from `python/requirements.txt`. Formatting uses Black from
`python/requirements-dev.txt`. Install those extras only when needed.

## Test responsibilities

| Tests | Responsibility |
| --- | --- |
| `test_write_binary.py`, `test_preprocess.py` | Binary encoding, sequence validation, atomic writes, keep-last gridding, bounded filling |
| `test_convert_esa.py`, `test_dataset_evaluation.py` | Channel synchronization, manifest integrity, annotations, event matching, validation-only threshold selection |
| `test_verify_export.py` | Independent full-source frame comparison; reject changed values, masks, and staleness |
| `test_pca_features_comparison.py` | Preserved extrema, raw-evidence scores, alarm grouping, validation selection |
| `test_retention.py` | Exact packet bytes, causal capture, context, quotas, decoding, epoch boundaries |
| `test_native_retention.py` | Native source fidelity, training-only receivers, source-fixed event denominators |
| `test_randomized_retention.py` | Seed reproducibility, reservoir inclusion, phase sampling, frozen-study integration |
| `test_retention_transfer.py` | Component removals, reference packet equality, mission bundles, protocol locks, label-independent capture |

The suite runs without real datasets or a native binary. CI runs Python tests and
separately rebuilds the manuscript. Actual mission replays require trusted local
archives and are separate from CI. Local verification currently passes 101 tests;
remote CI status must be checked after pushing.

## Trusted Mission1 data

The official archives use pickle internally; use only trusted dataset files.
Expected inputs and policy are in [the data guide](data-pipeline.md).

```bash
python python/convert_esa.py data/ESA-Mission1 --output data/processed/telemetry.bin
python python/dataset.py data/processed
python python/verify_export.py data/ESA-Mission1 data/processed \
  --report data/results/source-verification.json
```

Dataset opening checks manifest policy, full-file hashes, header, physical size,
and annotation schema. The independent vectorized source verifier reconstructs
every frame from native observations and compares binary32 value bits, masks,
and staleness, covering filled and unavailable cells. The [Python-only full-source
verification](results/m1-source-validation.json) records the complete local export.
The older report's native scan remains historical evidence, not a current dependency.

## Research experiments

```bash
python python/run_retention_demo.py --latex paper/generated/smoke_results.tex
python python/run_retention_pilot.py --output data/results/native-reproduction
python python/run_retention_randomized.py \
  --baseline data/results/native-reproduction \
  --output data/results/randomized-reproduction
python python/run_retention_ablations.py \
  --baseline data/results/native-reproduction \
  --output data/results/ablation-reproduction
```

Each study writes packets before evaluating decoded evidence. Existing outputs are
not overwritten. Dataset and large result files remain gitignored. See the
[cross-mission guide](cross-mission-evaluation.md) to prepare an independent dataset,
freeze the protocol, and run all declared arms. It currently requires six
synchronized native channels; synthetic integration tests do not establish
cross-mission performance.

## Manuscript and formatting

```bash
make -C paper preview
python python/snapshot_paper.py --check
```

The preview command requires Tectonic and a thumbnail renderer (macOS `sips` or
Poppler). CI uses latexmk to build the same source. The snapshot check binds the
tracked PDF and README thumbnail to manuscript sources and generated figures.
Generated tables should be rebuilt from completed reports, never edited by hand.
Use Black for changed Python files; scientific plots use Matplotlib. The
[claim ledger](../paper/claims.md) separates measurements from untested benefits.

## Receiver mismatch, temporal evidence, and delivery

The [benchmark guide](benchmark.md) documents native and independent-mission
commands, coverage/adjacent-pair controls, temporal receiver input requirements,
finite-buffer transport accounting, and resource-measurement scope. Tests in
`test_retention_benchmark.py` cover complete native and external small-data runs,
training isolation, pair availability, loss/eviction/partial transmission, byte
conservation, and canonical settings tampering. The [roadmap](roadmap.md) separates
implemented software from external scientific evidence still needed.
