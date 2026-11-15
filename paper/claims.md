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
| Asynchronous channels and intermittent downlink are modeled | Planned | Additional source semantics and contact/queue model required |
| Recorder fits an embedded CPU/RAM allocation | Not established | C++ integration and hardware/resource measurements required |
| Existing detector results validate this recorder | Unsupported | Detector results and retention results answer different questions |

| Seeded comparisons reduce concern about the original uniform sampling phase | Measured on the same validation events | `docs/results/randomized-retention.json`; 80 arms, all seeds reported; not independent new faults |
| Seed ranges are generalization confidence intervals | Unsupported | Sampling variation is conditional on the same 11 events |
| The retention study requires C++ | False | Capture, decoding, frozen receivers, and study orchestration are Python; C++ tools are optional |
