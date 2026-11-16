# Evidence retention under detector mismatch

The benchmark asks whether recorded telemetry stays useful to a downstream detector
that differs from the capture trigger. The current measurements are development
results on the previously used Mission1 validation archive. They are not a new
held-out test, a novelty claim, or evidence of physical diagnosis.

## What is implemented

- A frozen receiver bank: standardized level plus PCA residuals at ranks 1–5.
  The level and rank-3 model preserve the original pilot's exact parameters.
  Additional ranks are trained/calibrated using eligible training observations
  only. These receivers are correlated sensitivity checks.
- Four capture conditions: causal first differences, six-standard-deviation level,
  rank-3 PCA relative to its training-calibrated threshold, and a disabled trigger.
  The last is a controlled failure scenario, not a claim about a real onboard model.
- Threshold-only, adaptive context capture, and coverage-based background control
  under each trigger, plus uniform and ten-seed reservoir/random-phase controls.
  The native benchmark has 132 arms across four caps and reuses verified original
  streams rather than regenerating the pilot.
- A separate ridge AR(1) receiver, fitted only on eligible consecutive training
  observations. Its inputs must both survive retention. Native gaps over 150 seconds
  and partition boundaries reset availability. No interpolation or forward filling
  creates forecast evidence. Twenty-eight selected policy/cap arms are reported.
- An adjacent-pair background control, evaluated in eight exploratory native arms
  after observing the temporal receiver's failure under singleton sampling.
  It spends the same reserved background quota on pairs inside time strata, leaving
  an odd unused slot unfilled. Pairs cannot cross epochs, strata, or 150-second gaps.
- A finite-buffer transport simulator and a separate synthetic host resource profile.

## Evidence and denominators

All source-eligible events remain in the overall denominator. Every receiver also
reports how many events it can recognize in the full archive; retention loss is
measured against this upper reference, not against an assumption that the detector
can detect every fault. Normal-observation positives are reported alongside scored
exposure and are not deduplicated alarm episodes.

Within-event trigger blindness means no capture score crosses its threshold inside
the annotated event. A nearby trigger may still preserve it as context. Blind-event
counts are conditional on full-archive recoverability by the particular receiver.
A zero conditional denominator is not perfect protection against unknown faults.

Pre/post-context coverage measures retained original samples in five-minute windows.
Post-context windows truncated by the evaluation boundary are flagged. Raw evidence,
encoded bytes, per-event outcomes, and stream hashes remain inspectable in JSON.

## Transport assumptions

Packets arrive at epoch end. Contacts are discrete service opportunities every six
hours; an arrival exactly at contact time enters before service. Buffer capacity is
charged to complete encoded packet payloads, including a partially transmitted
packet, until it is delivered, evicted, or lost. Drop-oldest is the default eviction
rule; drop-newest is also implemented. Oversized packets are rejected. Packets can
accumulate wire-byte progress over contacts; the model does not simulate physical
frame timing or CCSDS retransmission.

Each 128-byte frame payload charges 16 overhead bytes. The ample and lossy scenarios
allow 32,768 wire bytes/contact and 16,384 queued payload bytes; congestion allows
2,048 and 4,096. Loss is applied to completed packets, with probability 0.1 and one
declared seed in the lossy scenario. The simulator writes only fully delivered
packets. Evidence is reevaluated on that stream using actual contact delivery times.
Pending packets at the evaluation end supply no evidence.

Packet and payload accounting must conserve arrived = delivered + rejected +
evicted + lost + pending. Wire bytes include unsuccessful and partial transmissions.
Python object overhead is not counted as onboard buffer capacity. The schedules are
illustrative; congestion differences also reflect unequal actual capture expenditure.
They need engineering requirements and additional loss seeds before
operational or uncertainty claims.

## Reproduce the native experiments

Start from the verified native pilot and seeded-control runs described in the
[development guide](development.md). Use fresh output directories:

```bash
python python/run_retention_benchmark.py --output data/results/benchmark-reproduction
python python/run_retention_sequence.py \
  --benchmark data/results/benchmark-reproduction \
  --output data/results/sequence-reproduction
python python/run_retention_bursts.py \
  --benchmark data/results/benchmark-reproduction \
  --sequence data/results/sequence-reproduction \
  --output data/results/burst-reproduction
python python/profile_retention.py \
  --observations 20000 --output data/results/profile-reproduction.json
```

The benchmark supports `--budgets`, `--seeds`, and `--workers`; record any change
before viewing outcomes. It captures every arm before evaluating annotations.
Receiver fitting receives training annotations only. Inputs and original packet
streams are hash-checked, and the original pilot is not modified.

Generate the mismatch/delivery figure and manuscript tables from a completed run:

```bash
python python/summarize_retention_benchmark.py data/results/benchmark-reproduction/report.json
```

## Independent mission workflow

Supply synchronized original observations as NumPy arrays with the
[six-channel bundle contract](cross-mission-evaluation.md). Prepare the bundle with:

```bash
python python/prepare_retention_bundle.py \
  --timestamps source/timestamps.npy --values source/values.npy \
  --training-events source/training_events.json \
  --evaluation-events source/evaluation_events.json \
  --mission independent-mission --channels sensor-a sensor-b sensor-c sensor-d sensor-e sensor-f \
  --training-end-us 1704067200000000 \
  --evaluation-start-us 1704067200000000 --evaluation-end-us 1735689600000000 \
  --rationale 'Document original source, channel choice, prior label exposure, and split rationale here' \
  --output data/independent-mission
```

Dates and names above are placeholders, not recommended split choices. The adapter
copies arrays without resampling; it checks shape, precision, chronology, finite
values, split annotations, and file hashes. The source-provenance record does not
authenticate that measurements came from a spacecraft.

Freeze and commit a protocol before inspecting evaluation outcomes:

```bash
python python/run_retention_bundle_benchmark.py freeze \
  --bundle data/independent-mission --lock protocols/independent-mission.lock.json
python python/run_retention_bundle_benchmark.py run \
  --bundle data/independent-mission --lock protocols/independent-mission.lock.json \
  --output data/results/independent-benchmark
python python/run_retention_sequence.py --bundle data/independent-mission \
  --benchmark data/results/independent-benchmark --output data/results/independent-temporal
```

The extended runner includes burst capture for all four trigger conditions: 148
policy/cap/seed arms with default settings, followed by 36 selected temporal arms.
It verifies the input, canonical settings digest, code/requirements hashes, Python,
and NumPy versions against the lock. It calibrates all receivers from training
only and parses evaluation annotations after every capture completes. Changing
settings, code, or inputs requires an explicit new lock. Preserve and report all
attempts; a lock cannot prove that someone has never inspected labels. This
workflow has also completed the [frozen Mission2 follow-up](results/mission2-study.md).
Its fixed subset has no eligible anomaly labels, so the primary fault comparison is
uninformative. Temporal input availability is measured separately.

## Resource profile

[The host profile](results/retention-resource-profile.json) reports throughput,
1,000-observation block-mean latency percentiles, and a separate tracemalloc pass.
Both passes must produce identical packet hashes. Measurements include synthetic
sample creation, encoding, and hashing but exclude disk I/O and receiver training.
Traced allocations are not process RSS, total native allocations, or embedded RAM.
One local run does not establish deployment capacity or reliable tail latency.

## Completed Mission2 attempt

The [protocol](../protocols/mission2-study-v1.md), [input lock](../protocols/mission2-study-v1.lock.json),
and [results](results/mission2-study.md) preserve the complete 148/36-arm follow-up.
The empty eligible anomaly denominator is not a reason to relabel rare events or
substitute another group. The annotation-support check is explicitly post-evaluation.
`report_mission2_study.py` generates descriptive paper artifacts; it does not alter
scoring or replace the locked primary analysis. See the source-selection record for
exact reproduction commands and the two local pre-evaluation commits.
