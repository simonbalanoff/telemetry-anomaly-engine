# Claim and evidence ledger

| Statement | Status | Evidence or requirement |
| --- | --- | --- |
| Packet headers, record prefixes, timestamps, and measurements are charged | Implemented | `retention/codec.py`; exact-size and corruption tests |
| Every active epoch respects its serialized packet cap | Implemented/tested | Serialization guard; randomized irregular multi-epoch tests |
| Adaptive background capacity is independent of trigger scores | Implemented/tested | Separate quota; continuous-trigger reservation test |
| Retained context can precede a trigger without using future observations | Implemented/tested | Bounded raw ring and prefix-invariance test |
| The smoke table reproduces from decoded packet files | Measured synthetic check | `run_retention_demo.py`; `docs/results/retention-smoke.json` |
| Native validation retention evidence improves over the current uniform baseline | Measured on validation only | `docs/results/native-retention.json`; 11 events, four caps, simple fixed receivers; not a generalization claim |
| Adaptive capture improves independent mission performance or physical diagnosis | Not established | Untouched mission and operator evaluation required |
| The method is novel relative to adaptive sampling/triggered recorders | Not established | Expanded prior-art review required |
| Native synchronized source replay is implemented | Implemented/measured | Hash-bound native source cache; 3,248,700 validation observations; decoded packet streams |
| Finite-buffer contact/loss delivery is modeled | Implemented/measured illustrative scenarios | `docs/results/receiver-mismatch.json`; schedules are not validated mission requirements |
| Asynchronous channels are supported | Not established | Six synchronized native channels remain required |
| Recorder fits an embedded CPU/RAM allocation | Not established | Deployment implementation and hardware/resource measurements required |
| Existing detector results validate this recorder | Unsupported | Detector results and retention results answer different questions |
| Seeded comparisons reduce concern about the original uniform sampling phase | Measured on the same validation events | `docs/results/randomized-retention.json`; 80 arms, all seeds reported; not independent new faults |
| Seed ranges are generalization confidence intervals | Unsupported | Sampling variation is conditional on the same 11 events |
| The retention study requires C++ | False | Capture, decoding, frozen receivers, and study orchestration are Python; the former native runtime has been retired |
| Pre-trigger buffering preserves pre-event context in the pilot | Measured component ablation | `docs/results/ablation-retention.json`; 64.3% to 1.8% at 1,024 bytes; same validation events |
| Mission2 fault-retention generalization is established | Not established | Frozen follow-up completed, but the fixed subset has zero eligible anomaly events; primary analysis is uninformative |
| Receiver mismatch is evaluated | Measured on validation only | `docs/results/receiver-mismatch.json`; six correlated pointwise receivers, four capture conditions, 132 arms |
| Singleton background evidence supports arbitrary future temporal models | Unsupported | `docs/results/temporal-retention.json`; disabled-trigger adaptive retains 0/11 AR(1) events despite 4/11 PCA events |
| Adjacent-pair background can preserve some temporal evidence under a disabled trigger | Exploratory validation result | `docs/results/burst-retention.json`; 2/11 AR(1) events at 1,024 bytes; policy developed after inspecting validation |
| Host resource measurements demonstrate onboard capacity | Unsupported | `docs/results/retention-resource-profile.json`; synthetic host timing/traced allocations only |
| A real Mission2 follow-up completed under the frozen protocol | Measured/executed | `docs/results/mission2-benchmark.json` and `mission2-temporal.json`; 148 capture and 36 temporal arms; lock commit `d5366f3` |
| Paired background supplies temporal inputs on Mission2 | Measured input availability only | 45,935 versus zero scorable native pairs at the 1,024-byte cap; this is not anomaly recall |
| Zero eligible events implies successful or failed event detection | Unsupported | `docs/results/mission2-primary.json` sets `informative=false`; event recall is unavailable |
| The Mission2 subset contains only rare nominal annotations | Independently checked after evaluation | `docs/datasets/mission2-annotation-support.json`; 252 source rows, 150 evaluation rows, no anomaly rows; raw CSV agrees with bundle |
