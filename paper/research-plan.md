# From protocol draft to research paper

The manuscript now includes synthetic checks and an initial native Mission1
validation pilot. Independent mission generalization and diagnostically useful
evidence under realistic operational constraints remain unestablished.

## 1. Native Mission1 validation pilot — initial sweep completed

**Implementation:** stream original native-timestamp observations into the four
recorder policies; never turn forward-filled grid cells into raw evidence. Fit
capture/receiver transforms on eligible training observations only. Reuse the
verified dataset hashes and channel-specific annotations.

**Initial proposed grid, not yet frozen:** one-hour epochs; 256, 512, 1,024, and
2,048 application bytes per active epoch; pre-trigger context 0/4/8 samples;
background reservation 0/0.2; fixed declared post-trigger context. Report actual
expenditure as well as allocation. Smaller caps change raw and summary capacities
differently; that difference must remain visible.

**Paper additions:** exact native-data inclusion/exclusion rules, training and
validation periods, source-observation and event counts, configuration table, and
a diagram showing capture, serialization, delivery, and independent assessment.

**Completed:** a three-year native replay, four byte caps, four policies, fixed
training-only receivers, bit-checked decoded streams, and a generated paper table.
See [native results](../docs/results/native-retention.md). Stronger baselines and
ablations below remain necessary.

## 2. Establish the scientific comparison

The full-archive reference, ten-seed reservoir baseline, and ten-seed randomized-phase
baseline are now implemented and measured at all four caps. Add a stronger established
adaptive-sampling or triggered-buffer competitor next.
A comparison against only uniform sampling would be insufficient evidence of novelty.

Freeze a common receiver model and its threshold before comparing retention
policies. The receiver should differ from the capture trigger, for example a
forecasting or relationship model. Include a second receiver/model swap to expose
capture/receiver coupling. Define how the receiver consumes sparse observations
and summaries without silently treating absent data as normal measurements.

Report all source-eligible events in the denominator: an event lost by a retention
policy is a miss, not an unscorable event that disappears from the report. Events
with genuinely unavailable original source observations are separately identified.
Summary overlap is coarse temporal evidence and cannot claim exact onset recovery.

**Required figures:** evidence-versus-actual-bytes curves; context/onset error
versus budget; workload/delivery-delay distributions; paired per-event outcomes.

## 3. Explain which mechanism helps

Completed: 16 single-component ablation arms remove pre-trigger context, background
reservation, and post-trigger capture. Full arms reproduce the original packet hashes.
See [ablation results](../docs/results/ablation-retention.md). Interaction effects remain open.
Measure boundary effects, triggers that miss events, noisy normal periods, outages,
and budget exhaustion. Distinguish improved evidence preservation from changes in
receiver thresholds or alarm grouping. Include unsuccessful cases, not just examples
chosen because the adaptive policy succeeds.

Use paired event-level uncertainty and describe its assumptions. Time-correlated
frames do not provide millions of independent fault examples. With sparse events,
avoid declaring a winner from a small numerical difference.

## 4. Add mission realism and a fresh evaluation

Document a concrete user's memory, communication, and investigation requirements.
Simulate contact gaps, queueing, losses, eviction, and transport overhead before
calling the byte cap a realistic downlink budget. Measure recorder memory and CPU;
Keep experimentation Python-first. A native implementation is justified only by
profiling or the deployment/resource claims being made.

Freeze choices after validation, then evaluate an untouched mission or independent
dataset. The historical Mission1 test period has already been inspected. Further
results on it are exploratory, not a fresh held-out estimate.

## Missing manuscript content before submission

- A literature comparison table locating the actual contribution among triggered
  recorders, adaptive sampling, compression, and anomaly-based prioritization.
- Explicit primary/secondary outcome definitions and policy-independent denominators.
- A justified resource configuration and an experimental-design table.
- Native mission results, uncertainty, ablations, stronger competitors, and failure cases.
- Resource/contact-model evidence for any practical deployment claims.
- A reproducibility statement, data/license details, affiliation, venue format,
  and required AI-assistance/funding/conflict disclosures.

The single-component ablations and [frozen cross-mission runner](../docs/cross-mission-evaluation.md)
are implemented. Supply a documented independent-mission bundle, freeze its lock before
evaluation, and run all declared arms. A stronger adaptive-acquisition competitor and
component interactions remain coding tasks; the seeded sampling controls are complete. The native pilot is validation development evidence; the synthetic
table remains a software check. Neither replaces a frozen independent evaluation.

## Completed implementation and next evidence

The [implementation roadmap](../docs/roadmap.md) now has an executable
[benchmark](../docs/benchmark.md): 132 native mismatch arms, 28 temporal assessments,
eight exploratory adjacent-pair arms, finite-buffer delivery, and a scoped host
profile. The independent benchmark freezes 148 capture arms and 36 temporal
assessments. Software/integration checks do not complete the independent-mission
or operator-validation research milestones. The paired-background policy was
motivated by the observed validation failure and must be frozen before confirmation.
