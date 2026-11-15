# Research roadmap

The implementation is a tool for testing hypotheses, not a prerequisite that must
be finished before research starts. The next release targets this question:

> Can a causal recorder preserve evidence for downstream detectors that disagree
> with, or replace, the detector used for capture?

## Deliverables and acceptance criteria

| Workstream | Deliverable | Acceptance criterion |
| --- | --- | --- |
| Detector mismatch | Training-calibrated receiver bank; capture/receiver matrix; trigger-blind event analysis | All source-eligible events remain in denominators; training-only calibration; report full-archive recoverability and evidence lost to retention |
| Stronger retention control | Bounded coverage-based sampler combined with trigger/context capture | Exact packet cap, deterministic replay, causal prefix invariance; compare against established simple policies, without claiming algorithmic novelty |
| Realistic delivery | Finite FIFO buffer, scheduled contacts, fragmentation overhead, loss, and eviction | Explicit arrival/service order; charge actual wire bytes; evaluate only delivered packets; include conservation and boundary tests |
| Reusable benchmark | One command for native development study; verified external mission bundle preparation | Label-free capture stage; all arm configurations and input/model/code hashes recorded; refuse to overwrite results |
| Resource measurements | Separate replay-throughput and allocation profiling | Report measurement scope/environment; avoid embedded or flight claims |
| Research artifact | Generated tables, inspectable JSON, manuscript methods/results and reproduction commands | Every reported numerical finding traces to a completed report |

## Experimental order

1. Keep the original native pilot, randomized controls, and component ablations as
   historical development evidence; do not silently change their models or streams.
2. Fit additional downstream PCA ranks on eligible training data only. Compare
   first-difference, level, and PCA-guided capture with the same frozen receiver
   bank. A deliberately disabled trigger is a stress control, not a real fault model.
3. Compare trigger-only capture, existing adaptive capture, and a coverage-based
   alternative. Include uniform, reservoir, and random-phase controls. Report
   event evidence, context, byte cost, and normal-observation exposure.
4. Replay delivered packets under declared contact/buffer/loss scenarios. A
   simulator provides conditional results, not evidence of operational downlink
   requirements or physical diagnostic usefulness.
5. Freeze retention settings, channel/split choices, and analysis before an
   independent-mission evaluation. Recalibrate receivers using that mission's
   training partition only. Publish all attempts and prior label exposure.
6. Expand the prior-art comparison and request domain review before claiming
   novelty or submitting a paper. A benchmark or negative result may be the
   contribution even if the proposed recorder does not win.

## External evidence still required

An untouched independent-mission dataset, engineering requirements for a realistic
contact model, and operator assessment of diagnostic usefulness are not present in
this repository. Software and synthetic tests cannot substitute for those inputs.
The current packet schema requires six synchronized channels. Asynchronous channels
and arbitrary-width records require a separate versioned format and should follow
a concrete dataset/deployment requirement, rather than silently changing the
current benchmark's evidence semantics.

## Implementation record

The receiver-mismatch benchmark, coverage control, transport simulator, bundle
preparation/locked independent runner, temporal AR(1) assessment, adjacent-pair
control, resource profiler, and generated-artifact tools are implemented. See
[benchmark methods and commands](benchmark.md). Native measurements include 132
mismatch arms, 28 temporal evaluations, and an eight-arm exploratory pair control.
The software acceptance criteria above are covered by regression/integration tests.
Actual external evidence listed above remains pending; do not mark those research
questions complete because their runners exist.
