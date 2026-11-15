# From protocol draft to research paper

The current manuscript is a methods/protocol draft with synthetic engineering
checks. Its central empirical claim—better preservation of useful fault evidence
under realistic constraints—has not yet been established.

## 1. Run a native Mission1 validation pilot

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

**Exit criterion:** reproducible multi-budget validation reports, budget/causality
checks over the complete pilot, and no annotations entering capture decisions.

## 2. Establish the scientific comparison

Add a full-archive reference, a detector-independent random/reservoir baseline,
and a stronger established adaptive-sampling or triggered-buffer competitor.
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

Ablate pre-trigger context, background reservation, and post-trigger capture.
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
C++ integration is necessary only for the deployment/resource claims being made.

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

The first useful next coding task is item 1. The first useful next writing task
is to formalize item 2's receiver protocol and outcomes before collecting the
main results. The current synthetic table remains a software check, not the main
results table for a submission.
