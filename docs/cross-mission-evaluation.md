# Frozen cross-mission evaluation

The next generalization test transfers fixed **retention settings**, while fitting
normalization and receiver thresholds on the new mission's designated training
observations. It is not zero-shot transfer of the Mission1 receiver. No independent
mission result has been measured yet; only Mission1 archives are available locally.

## Fixed decisions

[Protocol settings](../protocols/cross-mission-v1.json) declare the four byte caps,
one-hour epochs, trigger threshold, context lengths, background fraction, receiver
quantile/PCA dimension, and all ten random seeds. These settings retain the current
Mission1 defaults; the ablation results have not been used to retune them.

The original retention-only runner reports every arm: four original policies, three adaptive component
removals, and twenty seeded sampling controls at each cap (108 arms in total).
A calculated full-archive reference shows what evidence the frozen receivers can
recover before retention. Compare actual bytes as well as caps. Primary outcome:
source-eligible events with frozen PCA evidence per cap. Secondary outcomes include
raw coverage, pre-event context, level evidence, epoch-end delivery delay, and
positive/scored normal observations. The latter are not alarm episodes.

Descriptive breakdowns use event duration (up to 60 seconds, over 60 through 600,
over 600) and maximum adjacent eligible-observation gap (up to/over 150 seconds) within the
event plus pre-event context. Fewer than two observations yields an insufficient-data
group. Gaps concern usable native evidence, not simulated downlink outages; annotated
exclusions can create gaps between eligible observations.
Small strata and seed ranges are not generalization confidence intervals.

## Mission input contract

Provide a directory containing `manifest.json` and these four files:

| File | Meaning |
| --- | --- |
| `timestamps.npy` | Strictly increasing nonnegative little-endian int64 UTC microseconds, shape `(N,)` |
| `values.npy` | Finite little-endian float32 original measurements, shape `(N, 6)` |
| `training_events.json` | Training annotations only; may be `[]` |
| `evaluation_events.json` | Evaluation annotations, kept separate from training |

The current codec requires **six synchronized channels**. Choose and document
channels using engineering metadata or training data before looking at evaluation
outcomes. Do not interpolate, forward-fill, or silently discard asynchronous samples
to manufacture synchronization. An asynchronous adapter and a variable-width codec
remain separate future work. Preserve the raw-data source, license, adapter version,
channel-selection rationale, and split rationale alongside the bundle.

Example manifest (replace the hashes and mission identity with real values):

```json
{
  "format": "TAE-MISSION",
  "version": 1,
  "mission": "Independent mission identifier",
  "channels": ["sensor-a", "sensor-b", "sensor-c", "sensor-d", "sensor-e", "sensor-f"],
  "observation_semantics": "synchronized-native-no-fill",
  "training_end_us": 1704067200000000,
  "evaluation_start_us": 1704067200000000,
  "evaluation_end_us": 1735689600000000,
  "files": {
    "timestamps.npy": "SHA256",
    "values.npy": "SHA256",
    "training_events.json": "SHA256",
    "evaluation_events.json": "SHA256"
  }
}
```

Annotations are lists of objects with `event_id` (string), `category`, `channel`,
`start_us`, and `end_us`. Categories are `Anomaly`, `Rare Event`, or
`Communication Gap`; the latter two exclude source observations from event scoring.
Channel IDs 41–46 are **logical wire-format slots** corresponding to the six declared
channel names, not an assumption about the new mission's sensor names. Group
multi-channel annotations under the same event ID. Intervals are half-open;
`start_us == end_us` identifies a point event. Training intervals must lie within
`[0, training_end_us)` and evaluation annotations within the declared evaluation
split (non-point intervals may end at its exclusive end). This first interface
rejects crossing annotations; choose documented boundaries outside events rather
than clipping faults. Evaluation boundaries must align to whole reporting epochs.

## Freeze, then run

```bash
python python/run_retention_transfer.py freeze \
  --bundle data/independent-mission \
  --settings protocols/cross-mission-v1.json \
  --lock protocols/independent-mission.lock.json

python python/run_retention_transfer.py run \
  --bundle data/independent-mission \
  --lock protocols/independent-mission.lock.json \
  --output data/results/independent-mission-v1
```

Commit the lock before running the evaluation. It binds the target manifest,
settings, and implementation hashes. File hashes, shapes, finite values, temporal
order, and split separation are checked. A changed input or implementation requires
an explicit new lock; existing locks and completed outputs are not overwritten.
The runner fits receivers using training observations/annotations, writes the
frozen model, and captures every packet stream before parsing evaluation labels.
Decoded packets must preserve source timestamps and binary32 measurements and obey
their declared cap. All arms, source denominators, event details, and stream hashes
are written to `report.json`; large streams remain local.

Hash locks make changes reviewable; they cannot establish that a person has never
seen labels, authenticate a mission identity, or prevent deliberate lock editing.
Record prior exposure and publish all attempts. If settings change after evaluation,
treat the result as development and use another untouched evaluation for confirmation.
A successful run on synthetic fixtures checks software, not cross-mission performance.

## Extended receiver-mismatch benchmark

For the current research experiment, prefer the [extended benchmark workflow](benchmark.md).
It adds the frozen receiver bank, coverage and adjacent-pair controls, finite-buffer
delivery, a canonical settings digest and environment/code checks, and a separate
AR(1) evaluation requiring retained native pairs. Its default independent study has
148 capture arms and 36 selected temporal evaluations. The original runner above
remains available for reproducing its narrower protocol.
