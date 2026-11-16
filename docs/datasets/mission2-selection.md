# Mission2 source audit and channel-selection rule

Source: ESA Anomaly Dataset v2, Zenodo record 15237121, `ESA-Mission2.zip`.
The local archive matches the official MD5 `bfc72012691427d9327eb41f726ce45e`.
The archive contains 100 channels and approximately 4.10 GB of extracted files.

## Selection declared before inspecting channel values or event labels

Use the lowest numbered metadata group containing exactly six channels that all
have `Target=YES` and `Categorical=NO`. The supplied `channels.csv` selects group 13:
`channel_86` through `channel_91`, subsystem 6, physical unit 3. The next eligible
metadata groups are 14 and 31; they are not alternatives to try after viewing
anomaly detection outcomes.

The first compatibility check examines native timestamp identity and training-only
numeric quality. It does not load `labels.csv`, inspect evaluation-value statistics,
or compute anomaly outcomes. Training is provisionally before 2001-10-01, the
chronological boundary used by the authors' 21-month Mission2 benchmark setting:
https://github.com/kplabs-pl/ESA-ADB/blob/main/notebooks/data-prep/Mission2_semiunsupervised_prep_from_raw.py
The final split and annotation-boundary rules must be committed before evaluation.

This audit is not a frozen evaluation protocol. It establishes whether the current
six-synchronized-channel representation can preserve these source observations.
If the native channels are asynchronous, do not interpolate, fill, or intersect
away observations to make this group appear synchronized. Record incompatibility
and extend the representation before proceeding. Channel selection must not depend
on which group produces favorable anomaly results.

## Prior exposure

Before selection: archive size, path list, and `channels.csv` metadata only.
No Mission2 labels, evaluation-value statistics, fitted models, or fault outcomes
have been examined. Any additional timestamp or training-data exposure is to be
recorded in the audit report. Mission1 was already used for development.

## Completed audit and native export

[Audit report](mission2-audit.json) and [native export manifest](mission2-native-export.json)
record source/implementation hashes. All six selected channels share exactly
7,387,262 native timestamps across the full source. Each has 3,711,752 observations
before the provisional training cutoff. Training checks pass; the later export
checks every source timestamp and value for exact binary32 representation.

The extracted archives are in `data/ESA-Mission2/`. The lossless source arrays are
`data/native-mission2/timestamps.npy` and `data/native-mission2/values.npy`, with a
local manifest. These are not a complete labeled benchmark bundle. No interpolation,
forward filling, timestamp intersection, derivative transformation, or sample
reordering was performed. Raw data and arrays remain gitignored.

Exposure after these steps: metadata, timestamp identity/chronology, and numeric
integrity across the source; training numeric quality. The tools do not parse
`labels.csv`, summarize evaluation-value distributions, or fit/evaluate any model.
Reading all values to validate a lossless export is a source-integrity operation,
not an anomaly experiment.

### Reproduce without overwriting this audit

```bash
unzip -n data/ESA-Mission2.zip -d data
python python/audit_mission_channels.py data/ESA-Mission2 \
  --report data/results/mission2-audit-reproduction.json
python python/export_mission_native.py data/ESA-Mission2 \
  --audit data/results/mission2-audit-reproduction.json \
  --output data/native-mission2-reproduction
```

Run from the repository root with the core Python dependencies installed. System
`unzip` handles the outer archive's compression, which Python's standard ZIP
reader does not support. The source loader reads trusted official pickle objects.
The tools reject existing outputs and changed metadata/source hashes. Tests cover
metadata-only selection, training-limited quality checks, timestamp units and
misalignment, lossless export, and hidden integer precision loss.

### Remaining before evaluation

Commit the channel selection and final chronological split/boundary-event rules;
then convert annotations without using outcome counts to change those choices.
Prepare the complete mission bundle from the native arrays and separate training/
evaluation annotations. Freeze the extended benchmark lock and commit it before
running the declared comparisons. No Mission2 performance claim is supported yet.

## Declared evaluation decisions

[Mission2 study protocol v1](../../protocols/mission2-study-v1.md) now fixes training
before October 1, 2001 and evaluation through July 1, 2003. It specifies event-ID
boundary censorship without clipping, the full declared comparisons, and the
primary disabled-trigger temporal contrast. The annotation-policy extension keeps
the legacy strict reader and Mission1 core evaluator unchanged. Preparation and
lock artifacts are added after that protocol/implementation has been committed.

## Prepared and frozen inputs

The channel/split rules and necessary implementation were committed as `3c1ed90`
before annotation conversion. [The bundle manifest](mission2-bundle-manifest.json)
and [preparation record](mission2-preparation.json) bind the original arrays,
source annotation files, converter, unchanged retention settings, and study text.
Original intervals and IDs are preserved. No receiver was fitted and no detection
outcome was calculated during preparation.

The complete local bundle is `data/mission2-bundle-v1/`.
[The evaluation lock](../../protocols/mission2-study-v1.lock.json) freezes its inputs,
code, numerical environment, and the study protocol. It is committed before the
first evaluation; runtime checks enforce that ordering and record its commit.
The later temporal and primary analyses verify the same committed study.

```bash
python python/run_retention_bundle_benchmark.py run \
  --bundle data/mission2-bundle-v1 --lock protocols/mission2-study-v1.lock.json \
  --output data/results/mission2-benchmark-v1
python python/run_retention_sequence.py --bundle data/mission2-bundle-v1 \
  --benchmark data/results/mission2-benchmark-v1 \
  --output data/results/mission2-temporal-v1
python python/summarize_independent_retention.py \
  --benchmark data/results/mission2-benchmark-v1/report.json \
  --temporal data/results/mission2-temporal-v1/report.json \
  --output data/results/mission2-primary-v1.json
```

The complete 148 capture arms and 36 selected temporal evaluations are required.
Results do not authorize retrospective channel, split, policy, or seed selection.
The paper's Version 1.0 snapshot predates this evaluation and remains a Mission1
technical report until a separately identified revision incorporates new evidence.
