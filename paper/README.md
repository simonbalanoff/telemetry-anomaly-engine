# Research report

**Preserving Fault Evidence under Telemetry Budgets: A Causal Recorder and Evaluation Protocol**

**Simon Balanoff · Technical Report, Version 1.0 · November 15, 2026**

[Read the current PDF](draft.pdf) · [LaTeX source](main.tex) ·
[Research plan](research-plan.md) · [Claim/evidence ledger](claims.md)

This version presents the completed Mission1 development studies as a coherent
technical report. It is not a peer-reviewed publication or an independent-mission
validation. The `draft.pdf` filename is retained so existing repository links keep
working.

## Scope of this version

The report covers the byte contract and causal recorder, native Mission1 replay,
seeded sampling controls, component ablations, capture/receiver mismatch, a temporal
AR(1) receiver, exploratory adjacent-pair background capture, and illustrative
finite-buffer delivery. Synthetic software checks are collected in an appendix.
The central distinction is between retaining event samples, retaining context,
and retaining the inputs required by a particular downstream receiver.

All mission results concern the same 11 validation events. The adjacent-pair control
was developed after inspecting the temporal result. Independent-mission performance,
novelty relative to established retention methods, and operational diagnostic value
remain unestablished. Versioning the report does not change those evidence limits.

## Build and refresh

From the repository root, with Tectonic and a thumbnail renderer installed:

```bash
make -C paper preview
python python/snapshot_paper.py --check
```

The build writes `paper/build/main.pdf`, then refreshes `paper/draft.pdf`,
`paper/preview.jpg`, and `paper/snapshot.json`. Commit the three snapshot files
with manuscript changes. The source manifest binds the PDF and preview to the
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
