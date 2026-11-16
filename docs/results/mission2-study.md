# Mission2 frozen follow-up: input availability without anomaly support

**The predeclared primary contrast is uninformative:** the fixed six-channel
evaluation subset has no eligible anomaly events. N/A is not perfect recall,
zero detection performance, or evidence that the method generalizes.

## Protocol and execution

Channels 86–91 were selected using metadata before annotation conversion.
Training ends October 1, 2001; evaluation includes all remaining source through
July 1, 2003, on the anonymized dataset timeline. Retention settings transfer
unchanged from Mission1; receivers calibrate only on eligible Mission2 training
data. The channel/split/implementation commit is `3c1ed90`; the input-lock commit
is `d5366f30b9e6e61c2374e6a94734ef05a47fab10`. All 148 capture arms and 36 selected temporal
evaluations completed. No alternate group was selected after observing the result.

The [protocol](../../protocols/mission2-study-v1.md) and
[lock](../../protocols/mission2-study-v1.lock.json) bind inputs, code, environment,
and the primary comparison. This is a local Git record, not third-party preregistration.

## Annotation-support verification

The fixed channels have 252 source annotation rows, all classified as Rare Event.
The evaluation split has 150 Rare Event rows across 25 event IDs.
An independent raw-CSV category/interval check agrees with the prepared bundle.
Rare nominal events remain exclusions under the frozen protocol; they are not
relabeled as faults to create a favorable denominator. Metadata `Target=YES`
did not establish anomaly-only task support under our scoring rules. This is a
limitation of our source qualification, not an annotation error.

## Predeclared primary contrast

At the 1,024-byte cap, compare disabled-trigger paired versus singleton background
using AR(1) event evidence. The common eligible and full-archive-recoverable
anomaly counts are both zero. Paired outcome counts are therefore empty; no
effect estimate or significance claim is supported.

## Secondary input-availability measurement

| Capture / policy | Encoded MiB | Scorable retained native pairs | Anomaly recall |
| --- | ---: | ---: | --- |
| uniform | 14.66 | 0 | N/A |
| difference-adaptive | 3.62 | 0 | N/A |
| difference-coverage | 3.62 | 783 | N/A |
| difference-burst | 3.62 | 45,935 | N/A |
| disabled-adaptive | 3.62 | 0 | N/A |
| disabled-burst | 3.62 | 45,935 | N/A |

The pair policy preserves 45,935 of 3,675,508 full-source scorable transitions
(1.25%), compared with 0 for singleton background.
The two primary streams differ by 36 encoded bytes, despite rounding to the same
3.62 MiB. This is a structural input-availability result, not measured fault recovery.

The paper keeps Mission1 development findings separate from this frozen follow-up.
A subsequent study needs an annotation-only coverage qualification rule declared
before selection, or a representation covering the complete intended target set.
This completed attempt remains in the record; it is not replaced by another group.

Full artifacts: [capture benchmark](mission2-benchmark.json),
[temporal evaluations](mission2-temporal.json), [primary analysis](mission2-primary.json),
and [annotation-support check](../datasets/mission2-annotation-support.json).
