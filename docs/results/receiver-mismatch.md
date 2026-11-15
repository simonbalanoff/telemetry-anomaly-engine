# Capture/receiver mismatch and delivery

Development results on the same Mission1 validation archive. Receiver normalization
and thresholds use training data only. PCA ranks are correlated sensitivity checks,
not independent faults. No independent-mission result is claimed.

## Capture mismatch at 1024 bytes per active hour

| Capture | Recorder | Actual MiB | PCA-3 events | Trigger-blind PCA-3 retained / recoverable | Pre-context | Post-context |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Difference | threshold | 0.81 | 10/11 | 0/1 | 0.0% | 5.7% |
| Difference | adaptive | 6.30 | 11/11 | 1/1 | 64.3% | 40.2% |
| Difference | coverage | 6.30 | 11/11 | 1/1 | 66.3% | 36.9% |
| Level | threshold | 1.38 | 10/11 | 0/1 | 0.0% | 4.8% |
| Level | adaptive | 6.67 | 11/11 | 1/1 | 65.1% | 33.2% |
| Level | coverage | 6.67 | 11/11 | 1/1 | 67.1% | 29.9% |
| PCA | threshold | 1.58 | 11/11 | 0/0 | 0.0% | 4.8% |
| PCA | adaptive | 8.86 | 11/11 | 0/0 | 65.1% | 33.2% |
| PCA | coverage | 8.75 | 11/11 | 0/0 | 66.3% | 29.9% |
| Disabled | threshold | 0.80 | 0/11 | 0/11 | 0.0% | 0.0% |
| Disabled | adaptive | 6.22 | 4/11 | 4/11 | 1.8% | 5.0% |
| Disabled | coverage | 6.22 | 6/11 | 6/11 | 2.9% | 5.3% |

Trigger-blind means no above-threshold capture score **within the annotated event**.
Context capture may still be triggered outside it. The blind denominator includes
only source-eligible events detectable by that downstream receiver in the full
archive. All source-eligible events remain in the overall denominator. A zero
blind denominator means no such cases, not perfect blind-spot protection.

Coverage is an experimental control: within each reserved background time stratum,
it replaces candidates to increase distance from previously retained background
observations in training-standardized units. Trigger/context records are protected.
This is not claimed as an original or optimal algorithm. The disabled-trigger arm
is an explicit stress control, not evidence of actual onboard model failure.

## Delivered evidence

| Recorder | Scenario | Transmitted wire MiB | Delivered / captured packets | PCA-3 events |
| --- | --- | ---: | ---: | ---: |
| uniform | ample | 28.24 | 26304/26304 | 5/11 |
| uniform | congested | 8.56 | 4498/26304 | 4/11 |
| uniform | lossy | 28.24 | 23638/26304 | 5/11 |
| adaptive | ample | 7.11 | 26304/26304 | 11/11 |
| adaptive | congested | 7.04 | 26182/26304 | 11/11 |
| adaptive | lossy | 7.11 | 23638/26304 | 10/11 |
| coverage | ample | 7.11 | 26304/26304 | 11/11 |
| coverage | congested | 7.04 | 26182/26304 | 11/11 |
| coverage | lossy | 7.11 | 23638/26304 | 10/11 |

Contacts are discrete six-hour service opportunities. Arrivals at contact time enter
before service. Ample/lossy cases allow 32,768 wire bytes per contact and a 16,384-byte
payload buffer; congestion allows 2,048 and 4,096 bytes, respectively. Each 128-byte
frame payload charges 16 overhead bytes. Lossy drops completed packets with probability
0.1 (one declared seed). No retransmission is modeled. These illustrative schedules
are not validated mission requirements. Loss variation needs additional seeds before
an uncertainty claim. Pending, evicted, rejected, or lost packets supply no evidence.

## Reproduce

```bash
python python/run_retention_benchmark.py --output data/results/benchmark-reproduction
```

This requires the verified native pilot and seeded-control streams. All caps, arms,
events, receiver recoverability, normal-observation exposure, stream hashes, and
delivery accounting are available in [the JSON report](receiver-mismatch.json).
A frozen independent-mission version is available in `run_retention_bundle_benchmark.py`.
