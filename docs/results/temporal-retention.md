# Temporal evidence and adjacent-pair background

A ridge AR(1) receiver provides a temporal comparison to the pointwise PCA
receivers. It is fit on eligible consecutive training observations only,
using fixed regularization 0.001, a 150-second gap reset, and a training
score quantile of 0.999. Both original endpoints must survive retention.
No forward filling or stitching across missing observations earns credit.

## 1024-byte cap per active hour

| Capture / recorder | Actual MiB | PCA-3 events | AR(1) events | Scorable retained pairs |
| --- | ---: | ---: | ---: | ---: |
| Uniform | 25.04 | 5/11 | 2/11 | 2957 |
| Diff. / threshold | 0.81 | 10/11 | 1/11 | 11 |
| Diff. / adaptive | 6.30 | 11/11 | 10/11 | 1057 |
| Diff. / coverage | 6.30 | 11/11 | 10/11 | 4886 |
| Level / adaptive | 6.67 | 11/11 | 10/11 | 7281 |
| Pca / adaptive | 8.86 | 11/11 | 10/11 | 69167 |
| Disabled / adaptive | 6.22 | 4/11 | 0/11 | 0 |
| Diff. / burst | 6.30 | 11/11 | 10/11 | 79668 |
| Disabled / burst | 6.22 | 4/11 | 2/11 | 78877 |

The full archive contains AR(1) evidence for all 11 source-eligible events.
The native temporal study reports seven prespecified policies at four caps
(28 evaluations), rather than claiming exhaustive coverage of every receiver.

## What the experiment shows

- At 1,024 bytes, adaptive context capture preserves 10/11 temporal events versus 2/11 for uniform and 1/11 for threshold-only capture.
- Disabling the trigger leaves singleton adaptive background capture with 4/11 PCA-3 events but **0/11 AR(1) events**. Pointwise evidence is not interchangeable with temporal evidence.
- The adjacent-pair background control preserves **2/11 AR(1) events** under the disabled trigger, while retaining 4/11 PCA-3 events at the same rounded encoded cost. It does not solve the blind-spot problem.
- With first-difference triggers enabled, both ordinary adaptive and paired capture retain 10/11 AR(1) events. A pair control does not automatically improve the primary triggered result.

The pair control was designed **after observing this validation failure**. Its
eight-arm study is exploratory, not a fresh confirmation. The same hourly cap
does not imply equal exact expenditure; pair grouping may leave odd quota slots
unused. Isolated events, gap resets, background phase, and downstream model choice
still matter. Cross-mission evidence and stronger temporal detectors are pending.

Full reports: [temporal receiver](temporal-retention.json),
[adjacent-pair control](burst-retention.json), and
[capture/receiver benchmark](receiver-mismatch.json).

## Reproduce

```bash
python python/run_retention_sequence.py --output data/results/sequence-reproduction
python python/run_retention_bursts.py \
  --sequence data/results/sequence-reproduction \
  --output data/results/burst-reproduction
```

These commands require a completed native mismatch benchmark. See the
[benchmark guide](../benchmark.md) for full inputs and the independent-mission workflow.
