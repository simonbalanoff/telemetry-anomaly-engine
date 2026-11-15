# Research manuscript

**Working title:** Preserving Fault Evidence under Telemetry Budgets: A Causal Recorder and Evaluation Protocol.

This is an initial research draft, not a submission-ready or published paper.
The author is Simon Balanoff; affiliation and any venue-specific disclosures remain to be confirmed. It claims an implemented
prototype, synthetic protocol checks, and an initial native validation pilot. It
does not claim independent mission generalization, operational diagnosis, or novelty
of triggered recording itself.

## Read the draft

[Open the PDF snapshot](draft.pdf) · [First-page preview](preview.jpg) ·
[Next experiments and writing gaps](research-plan.md)

GitHub can render the checked-in PDF when opened from the repository. The root
README displays a clickable first-page image rather than an embedded PDF viewer.
These links become live on GitHub after the files are committed and pushed.

## Build and reproduce

With the existing core Python environment and Tectonic installed:

```bash
python python/run_retention_demo.py --latex paper/generated/smoke_results.tex
cd paper
make pdf
```

The PDF is written to `paper/build/main.pdf`. The generated table is committed so
LaTeX can also build without running an experiment. Tectonic fetches TeX packages
on first use. A conventional pdflatex/bibtex workflow also works with this standard
article/natbib source. The build directory and LaTeX intermediates are ignored.

## Refresh the README snapshot

```bash
make -C paper preview
python python/snapshot_paper.py --check
```

Run these from the repository root. Thumbnail rendering uses macOS `sips` or
Poppler's `pdftoppm`. Commit `paper/draft.pdf`, `paper/preview.jpg`, and
`paper/snapshot.json` with manuscript changes. The manifest binds the snapshot to
its LaTeX/BibTeX/generated-table/figure source and hashes both artifacts; it does not
require bit-identical output across different compilers or build dates.

CI checks the source/artifact hashes, regenerates the synthetic table, and builds
a fresh PDF artifact. The checked-in snapshot is refreshed explicitly; CI does
not automatically commit files or publish a release. Workflow artifacts may require
GitHub sign-in, while the repository PDF follows the repository's visibility.

## Evidence and editing rules

- Update measured tables through the experiment script, not by editing numbers.
- Keep planned work separate from implemented behavior and measured results.
- Preserve native observations; do not call forward-filled samples raw evidence.
- Report actual serialized bytes alongside common budget caps.
- Treat summary overlap as coarse evidence, not precise onset recovery.
- The historical Mission1 test period has already been examined. Plan a fresh
  independent evaluation before claiming generalization.
- Every external reference must be verified against its primary source. The
  current bibliography is a starting point, not an exhaustive novelty review.

## Next research milestones

1. **Completed initial pilot:** native Mission1 replay with four policies and four byte caps; see `docs/results/native-retention.md`.
2. **Completed seeded controls:** reservoir and randomized-phase sampling, ten seeds
   per cap, using the same frozen receivers. Receiver-model swaps remain planned.
3. Contact scheduling, losses, storage eviction, and realistic transport overhead.
4. Measured CPU/memory constraints; optional native implementation if justified.
5. Frozen independent-mission evaluation and engineering review.

See `docs/retention-research.md` for the implementation/protocol map and
`paper/claims.md` for the evidence ledger.
