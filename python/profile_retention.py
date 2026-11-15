"""Synthetic host throughput and Python allocation measurements, not flight timing."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import tracemalloc

import numpy as np

from dataset import atomic_text
from retention.codec import Sample
from retention.coverage import CoverageRecorder
from retention.burst import BurstRecorder
from retention.randomized import RandomizedRecorder
from retention.recorder import Recorder, RecorderConfig

POLICIES = (
    "uniform",
    "threshold",
    "adaptive",
    "reservoir",
    "randomized_uniform",
    "coverage",
    "burst",
)


def make_recorder(policy, config):
    if policy in ("reservoir", "randomized_uniform"):
        return RandomizedRecorder(policy, config, 0)
    if policy == "burst":
        return BurstRecorder(config)
    if policy == "coverage":
        return CoverageRecorder(config, np.zeros(6), np.ones(6))
    return Recorder(policy, config)


def replay(policy, count, config, blocks=False):
    recorder = make_recorder(policy, config)
    digest = hashlib.sha256()
    encoded = packets = maximum = 0
    latencies = []
    started = block_start = time.perf_counter()
    for index in range(count):
        value = math.sin(index / 100) + (10 if index % 1000 == 0 else 0)
        sample = Sample(index * 1000000, (value,) * 6)
        packet = recorder.observe(sample, abs(value))
        if packet is not None:
            data = packet.encode()
            digest.update(data)
            encoded += len(data)
            packets += 1
            maximum = max(maximum, len(data))
        if blocks and (index + 1) % 1000 == 0:
            now = time.perf_counter()
            latencies.append((now - block_start) * 1e6 / 1000)
            block_start = now
    packet = recorder.finish()
    if packet is not None:
        data = packet.encode()
        digest.update(data)
        encoded += len(data)
        packets += 1
        maximum = max(maximum, len(data))
    elapsed = time.perf_counter() - started
    return dict(
        seconds=elapsed,
        samples_per_second=count / elapsed,
        block_mean_microseconds_per_observation=(
            {str(p): float(np.percentile(latencies, p)) for p in (50, 95, 99)}
            if latencies
            else None
        ),
        serialized_bytes=encoded,
        maximum_packet_bytes=maximum,
        packets=packets,
        packet_stream_sha256=digest.hexdigest(),
    )


def profile(count=100000, budget=1024):
    if type(count) is not int or count < 1000:
        raise ValueError("Profile at least 1,000 observations")
    config = RecorderConfig(budget_bytes=budget)
    results = {}
    for policy in POLICIES:
        timing = replay(policy, count, config, blocks=True)
        tracemalloc.start()
        try:
            allocated = replay(policy, count, config)
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        if timing["packet_stream_sha256"] != allocated["packet_stream_sha256"]:
            raise ValueError("Profiling changed recorder output")
        timing.update(python_traced_peak_bytes=peak, python_traced_final_bytes=current)
        results[policy] = timing
    return dict(
        python=platform.python_version(),
        numpy=np.__version__,
        platform=platform.platform(),
        observations=count,
        budget_bytes=budget,
        results=results,
        scope="Separate uninstrumented timing and tracemalloc passes; includes synthetic sample creation, encoding and hashing; excludes disk I/O and model training. Latency percentiles are 1,000-observation block means, not per-observation tail latency. Traced allocations are not process RSS or total NumPy/embedded RAM.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=int, default=100000)
    parser.add_argument("--budget", type=int, default=1024)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Preserve completed measurements; use a new output file")
    report = profile(args.observations, args.budget)
    atomic_text(args.output, json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Host profile: {args.output}")


if __name__ == "__main__":
    main()
