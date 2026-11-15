# Preserving Fault Evidence under Telemetry Budgets

**Simon Balanoff · Causal telemetry retention · Research draft**

[Read the paper](paper/draft.pdf) · [Results](#results) ·
[Reproduce](#reproduce) · [LaTeX source](paper/main.tex)

When a spacecraft cannot transmit every measurement, **which observations should
it keep so that a future fault can still be investigated?**

This project studies a causal recorder that retains original measurements,
pre-trigger context, and background observations under a fixed serialized-byte
budget. Capture decisions use only observations available so far; event labels
are reserved for evaluation.

**Initial finding:** on 11 Mission1 validation events, the adaptive recorder
preserves downstream PCA evidence for **11/11 events using 6.30 MiB**, compared
with **5/11 using 25.04 MiB** for uniform sampling, under the same hourly byte cap.
These are development results on one mission; independent-mission performance
and diagnostic usefulness remain untested.

<a href="paper/draft.pdf"><img src="paper/preview.jpg" alt="First page of the research paper by Simon Balanoff; click to read the PDF" width="320"></a>

## Research approach

The recorder combines a bounded pre-trigger buffer, post-trigger capture, and
capacity reserved for background sampling independently of anomaly scores.
Headers, timestamps, record tags, and measurement values all count toward the cap.

The evaluation separates **capture → encoded packets → downstream assessment**.
Detectors are calibrated on eligible training observations and frozen across
policies. Evaluation decodes the packets and checks retained timestamps and values
against the original observations. Forward-filled values never count as raw evidence.

Comparisons include uniform sampling, fixed extrema summaries, threshold-only
capture, reservoir sampling, and randomized-phase sampling. Component ablations
remove pre-trigger capture, post-trigger capture, or background reservation.

## Results

The native replay covers **3,248,700 observations from 2008–2010**, with receivers
calibrated on **8,713,221 eligible training observations** from before 2008.
Experiments include four hourly caps, 80 seeded sampling arms, and 16 ablation arms.

At a **1,024-byte cap per active hour**:

| Capture policy | Total encoded MiB | Events with frozen PCA evidence |
| --- | ---: | ---: |
| Uniform sampling | 25.04 | 5 / 11 |
| Reservoir, ten seeds | 25.15 mean | 5.1 / 11 mean; range 4–7 |
| Randomized phase, ten seeds | 24.96 mean | 5.4 / 11 mean; range 4–8 |
| Threshold-only | 0.81 | 10 / 11 |
| Adaptive recorder | 6.30 | 11 / 11 |

All policies share a **cap**, not equal actual expenditure. Fixed summaries are
assessed separately because bucket extrema are not raw observations suitable for
the same PCA receiver. Seed ranges describe sampling variation on the same events,
not confidence intervals for performance on new faults.

![Fault evidence and pre-event context versus actual encoded bytes across recording budgets](docs/results/randomized-retention.svg)

**Event counts miss context loss.** At the same 1,024-byte cap, removing pre-trigger
capture preserves 11/11 PCA evidence but reduces pre-event context coverage from
**64.3% to 1.8%**. Removing background sampling reduces PCA evidence to 10/11 while
using fewer bytes. Removing post-trigger capture barely changes these headline metrics;
its diagnostic benefit has not been demonstrated.

These measurements concern **11 validation events** and do not establish novelty,
physical diagnosis, or cross-mission generalization. The previously examined
Mission1 test split is excluded. Reports include per-event outcomes, positive
normal observations, configurations, and artifact hashes:

[Native study](docs/results/native-retention.md) ·
[Seeded comparisons](docs/results/randomized-retention.md) ·
[Component ablations](docs/results/ablation-retention.md)

## Reproduce

The research pipeline runs entirely in Python with NumPy and pandas. Run the
software checks without mission data using Python 3.12 or compatible:

```bash
python -m pip install -r python/requirements-core.txt
PYTHONPATH=python python -m unittest discover -s python/tests -v
```

<details>
<summary>Replay the mission studies</summary>

Prepare trusted official ESA Mission1 archives and the verified dataset bundle
following the [data guide](docs/data-pipeline.md), then run:

```bash
python python/run_retention_pilot.py --output data/results/native-reproduction
python python/run_retention_randomized.py \
  --baseline data/results/native-reproduction \
  --output data/results/randomized-reproduction
python python/run_retention_ablations.py \
  --baseline data/results/native-reproduction \
  --output data/results/ablation-reproduction
```

Use new output directories. Studies preserve source and implementation hashes,
serialize packet streams, then evaluate decoded evidence. Raw datasets and large
artifacts remain gitignored; small reports and generated manuscript tables are tracked.

</details>

<details>
<summary>Build the paper and README preview</summary>

With Tectonic and a thumbnail renderer installed, run:

```bash
make -C paper preview
```

See the [paper guide](paper/README.md) for manuscript details.

</details>

## Next research question

Do the same retention settings preserve useful evidence on an independent mission?
The [cross-mission protocol](docs/cross-mission-evaluation.md) locks settings, code,
and input hashes before evaluation, with receiver calibration restricted to the
new mission's training data. The runner is tested; independent-mission results
are pending. The current input requires six synchronized native channels.

Stronger adaptive competitors, realistic contact/loss modeling, and engineering
assessment of diagnostic usefulness remain open research work.

[Method and byte contract](docs/retention-research.md) ·
[Research plan](paper/research-plan.md) · [Development](docs/development.md) ·
[Claim/evidence ledger](paper/claims.md)
