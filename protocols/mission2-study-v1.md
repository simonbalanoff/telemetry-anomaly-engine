# Mission2 independent evaluation protocol — version 1

## Decisions recorded before annotation conversion or evaluation

Source: ESA Anomaly Dataset v2, Zenodo record 15237121. The acquired
`ESA-Mission2.zip` has official MD5 `bfc72012691427d9327eb41f726ce45e`.
The metadata-first audit and lossless export are recorded in
`docs/datasets/mission2-selection.md` and its JSON artifacts.

Channels are fixed to `channel_86`–`channel_91`, in ascending order, mapped to
logical codec slots 41–46. This is the lowest numbered complete metadata group
with exactly six numeric target channels. Channels, splits, settings, and
comparisons will not change based on annotation counts or evaluation outcomes.

## Chronological split

- Training: all available native observations before **2001-10-01T00:00:00Z**.
- Evaluation: **[2001-10-01T00:00:00Z, 2003-07-01T00:00:00Z)**.
- The training boundary follows the authors' 21-month Mission2 benchmark boundary.
  The evaluation endpoint is the first complete hourly boundary after the last
  native observation; the full remaining source is included. No validation subset
  of Mission2 is used for tuning. This is training-calibrated transfer of retention
  settings, not zero-shot transfer of the Mission1 receiver.

## Annotation and boundary rules

Use only source annotations on the six fixed channels. Preserve original IDs,
categories, start/end times, and source channel names. Positive-duration intervals
are half-open; point intervals belong to the split containing their timestamp.
Do not move boundaries, truncate annotations to hide crossings, relabel faults as
quality exclusions, or choose a different group after inspecting labels.

Partition annotation rows by temporal intersection with the split. Determine
boundary censorship at **event-ID level across all selected-channel rows**: if
any part of an event lies outside a split, mark every intersecting row of that
event as boundary-censored for that split. This includes an event spanning the
boundary through separate, nonoverlapping channel annotations and a point exactly
at the exclusive endpoint. Preserve the original intervals and retain these events
in detailed output; exclude them from the common source-eligible event denominator.
Training masks still exclude the original intersecting anomaly/rare-event/gap
intervals, including the training portion of crossing events. Evaluation negative
exposure excludes all annotated intervals. Do not interpret censored events as
normal input. Categories and timestamp validity must be checked; malformed or
unknown annotations cause an error rather than silent omission.

## Frozen settings and comparisons

Use `protocols/cross-mission-v1.json` unchanged: one-hour epochs; caps 256, 512,
1,024, 2,048 bytes; trigger threshold 6; pre/post context 8/4 samples; background
fraction 0.2; receiver training quantile 0.999; PCA rank 3 as the original receiver;
seeds 0–9. The extended benchmark declares 148 capture arms and the subsequent
AR(1) analysis declares 36 selected policy/cap evaluations. All declared arms must
be reported. The disabled trigger is a controlled stress condition.

Primary contrast: **disabled-trigger adjacent-pair background versus disabled-trigger
singleton adaptive background, at the 1,024-byte cap**, using AR(1) event evidence.
Use the same source-eligible events and report full-archive AR(1) recoverability
separately. Report paired counts (both, pair only, singleton only, neither), raw
numerators/denominators, and actual byte expenditure. If there are no eligible or
recoverable events, report the experiment as uninformative for this contrast; do
not replace the dataset or claim success.

Secondary analyses are the remaining caps, enabled-trigger policies, pointwise
receiver bank, context preservation, normal-observation exposure, and declared
illustrative contact/loss scenarios. No hyperparameter selection or winner-driven
seed/cap selection is allowed. These comparisons are descriptive; correlated
observations, detector ranks, and seeds are not additional independent faults.
The AR(1) receiver uses the existing training-only ridge/gap/quantile settings.
No physical diagnosis or onboard deployment claim follows from this experiment.

## Exposure and execution record

Before this document: channel metadata, native timestamp identity, training numeric
quality, and full-source lossless numeric integrity checks only. No Mission2 event
labels, model scores, anomaly outcomes, or evaluation-value distributions were
inspected. After these rules were written, the CSV headers and their first row
were checked for schema; the displayed label was on unselected channel 9.
This did not change any selection or split. Annotation conversion after this document is an input preparation step;
it must not inform any choices above. Record converter/input hashes and preserve
all resulting artifacts.

Prepare a versioned bundle, test boundary handling, and freeze the implementation,
settings, environment, input hashes, and this protocol's digest. Commit that
concrete protocol/lock and its necessary implementation before running evaluation.
Record the protocol commit and retain every attempted evaluation. Hash locks make
changes visible; they do not prove that labels were never viewed. A post-evaluation
change produces a development result requiring a fresh confirmation dataset.
