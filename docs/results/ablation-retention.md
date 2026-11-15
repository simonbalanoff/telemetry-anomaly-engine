# Native component ablations

Four adaptive variants at four byte caps produce 16 paired development arms on the
same 3,248,700 Mission1 validation observations and 11 source-eligible events.
Training, receivers, trigger scores, epoch boundaries, and evaluation are unchanged.
Every full-arm stream reproduces the original adaptive stream hash exactly.

| Cap (bytes/hour) | Variant | Actual MiB | PCA events | Pre-event context |
| ---: | --- | ---: | ---: | ---: |
| 256 | full | 2.63 | 10/11 | 24.2% |
| 256 | no pre | 2.63 | 10/11 | 0.0% |
| 256 | no post | 2.63 | 10/11 | 24.2% |
| 256 | no background | 0.84 | 10/11 | 41.5% |
| 512 | full | 3.57 | 10/11 | 64.3% |
| 512 | no pre | 3.55 | 10/11 | 1.8% |
| 512 | no post | 3.56 | 10/11 | 64.3% |
| 512 | no background | 0.88 | 10/11 | 64.3% |
| 1024 | full | 6.30 | 11/11 | 64.3% |
| 1024 | no pre | 6.26 | 11/11 | 1.8% |
| 1024 | no post | 6.28 | 11/11 | 64.3% |
| 1024 | no background | 0.90 | 10/11 | 64.3% |
| 2048 | full | 11.69 | 11/11 | 67.1% |
| 2048 | no pre | 11.66 | 11/11 | 9.1% |
| 2048 | no post | 11.68 | 11/11 | 67.1% |
| 2048 | no background | 0.90 | 10/11 | 64.3% |

## What changes

- At 1,024 bytes, removing pre-trigger capture preserves PCA evidence for all 11 events but reduces pre-event context from 64.3% to 1.8%. Event counts alone miss this loss.
- Removing background sampling loses PCA evidence for `id_138` at the 1,024- and 2,048-byte caps. At 1,024 bytes, actual expenditure falls from 6.30 to 0.90 MiB. This is a coverage/cost tradeoff on this archive.
- At 256 bytes, removing background reservation increases pre-event context from 24.2% to 41.5%. Releasing the reserved quota allows more trigger context; background reservation is not free.
- Removing post-trigger capture leaves the reported PCA event counts and pre-context coverage unchanged at every cap. The present study does not establish its diagnostic benefit; post-event reconstruction is not an endpoint.

## Interpretation limits

These are single-component configuration removals, not factorial estimates of
interactions. No-background releases its reserved capacity to triggers. Caps are
shared, actual expenditure is not matched. Deterministic ablation arms have no
seed-based uncertainty; all outcomes concern the same small validation archive.
Positive normal observations remain exposure-dependent and are not alarm episodes.

The [machine-readable report](ablation-retention.json) includes source hashes,
packet-stream hashes, all per-event outcomes, durations, and descriptive duration/gap
strata. Gap strata use adjacent eligible observations from the event plus pre-event
context, so annotated exclusions can also create gaps in usable evidence. These
are descriptive failure breakdowns, not estimates from independent faults.

## Reproduce

```bash
python python/run_retention_ablations.py \
  --baseline data/results/retention-native \
  --output data/results/ablation-reproduction \
  --latex paper/generated/ablation_results.tex
```

The original native pilot, verified bundle, and trusted native archives must be
available. Outputs must be empty; original artifacts are not overwritten. Only
small reports and the generated manuscript table are tracked. Large streams remain
under ignored `data/results/`.

The next generalization experiment uses the [frozen cross-mission protocol](../cross-mission-evaluation.md).
No independent-mission performance result has been measured yet.
