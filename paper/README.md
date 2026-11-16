# Research report

**Preserving Fault Evidence under Telemetry Budgets: Causal Retention and Receiver Requirements**

**Simon Balanoff · Technical Report, Version 1.1 · November 15, 2026**

[Read the current PDF](draft.pdf) · [LaTeX source](main.tex) ·
[Research plan](research-plan.md) · [Claim/evidence ledger](claims.md)

This version integrates the Mission1 development studies and the completed,
protocol-fixed Mission2 attempt. It is a technical report, not a peer-reviewed
publication or a demonstrated cross-mission fault-recovery improvement. The
`draft.pdf` filename remains compatible with existing repository links.

## Scope and central findings

Event counts, context, temporal input availability, and delivered evidence are
different outcomes. Mission1 shows substantial context loss without an event-count
change and a pointwise/temporal mismatch under a disabled trigger. An adjacent-pair
control partially addresses the temporal failure on that same development archive.

The frozen Mission2 subset contains no anomaly labels: its 148 capture arms and
36 temporal assessments yield an **uninformative primary fault-retention comparison**.
The measured 45,935 paired inputs concern availability, not anomaly recovery. The
report preserves this attempt, the fixed selection rule, and the source-category
verification. It does not replace the group after viewing results.

The main text emphasizes definitions, methods, the two evidence phases, and their
limits. Complete Mission1 cap/control grids and synthetic checks appear in appendices.
Related work now includes operational burst prioritization, anomaly-guided science
downlink, the published ESA benchmark, OPS-SAT, compression, and streaming controls.
These comparisons do not establish algorithmic novelty. The report also discloses
AI-assisted implementation/drafting and its unreviewed technical-report status.

## Build and refresh

From the repository root, with Tectonic and a thumbnail renderer installed:

```bash
make -C paper preview
python python/snapshot_paper.py --check
```

The build writes `paper/build/main.pdf`, then refreshes `paper/draft.pdf`,
`paper/preview.jpg`, and `paper/snapshot.json`. Commit the three snapshot files
with manuscript changes. The snapshot manifest binds the PDF and preview to the
LaTeX, bibliography, generated tables, and figures. It does not require identical
PDF bytes across compilers. The report date is fixed for this version; update it
and the version deliberately for a future release.

GitHub opens the tracked PDF from the repository. The root README links it through
a first-page image. CI verifies snapshot hashes, regenerates the synthetic table,
and builds the manuscript with latexmk; it does not publish or commit a release.
A conventional pdflatex/BibTeX toolchain also supports the standard article source.

## Reproduce the evidence

The [benchmark guide](../docs/benchmark.md) documents experiment inputs, commands,
receiver calibration, delivery assumptions, and independent-mission protocol locks.
Small reports are tracked; trusted official mission archives and large packet
streams are obtained or generated separately.

Generated tables must come from completed reports, not manual numeric edits:

- `python/run_retention_demo.py`: synthetic validation table.
- Native, randomized, and ablation runners: their respective `--latex` outputs.
- `python/summarize_retention_benchmark.py`: mismatch/delivery tables and figure.
- `python/summarize_retention_sequence.py`: temporal and adjacent-pair comparison.

For future revisions, preserve source-fixed denominators, exact native observations,
actual byte expenditure, and the distinction between exploratory and independent
results. The [implementation roadmap](../docs/roadmap.md) separates implemented
software from external evidence still needed. Venue-specific formatting, affiliation,
and any required disclosures should be resolved before preparing a submission.

## Version record

Version 1.0, preserved in Git before the Mission2 run, reported Mission1 development
only. Version 1.1 adds the frozen follow-up and explicitly records its empty anomaly
denominator. The source/preparation protocol commit is `3c1ed90`; the pre-evaluation
lock commit is `d5366f3`. This local record is not third-party preregistration.
The [Mission2 result](../docs/results/mission2-study.md) links all completed reports.
`python/report_mission2_study.py` regenerates its qualification table and the
cross-phase input-requirement figure from completed reports and the verified source.
