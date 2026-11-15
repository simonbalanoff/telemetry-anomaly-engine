"""Detector-independent, seeded competitors with bounded epoch state.

Reservoir sampling is Algorithm R. Randomized uniform sampling shifts its K
scheduled targets by one shared random fraction of a stratum in each epoch.
Neither policy receives labels or uses anomaly scores.
"""

import hashlib
import random

from retention.codec import RawRecord
from retention.recorder import Reason, Recorder

RANDOMIZED_POLICIES = ("reservoir", "randomized_uniform")


class RandomizedRecorder(Recorder):
    def __init__(self, policy, config, seed):
        if policy not in RANDOMIZED_POLICIES:
            raise ValueError(f"Unknown randomized policy: {policy}")
        if type(seed) is not int or not 0 <= seed < 2**64:
            raise ValueError("Seed must be an unsigned 64-bit integer")
        self.seed = seed
        self.randomized_policy = policy
        super().__init__("uniform", config)
        self.policy = policy

    def _reset(self):
        super()._reset()
        self._rng = None
        self._seen = 0
        self._reservoir_slots = []
        self._phase = 0
        self._next_target = 0

    def _start_random_epoch(self):
        # Deliberately omit the budget: seeds couple the arms across capacities.
        # Empty/skipped epochs cannot shift the random sequence of another epoch.
        key = f"{self.randomized_policy}:{self.seed}:{self._epoch}".encode("ascii")
        epoch_seed = int.from_bytes(hashlib.sha256(key).digest(), "big")
        self._rng = random.Random(epoch_seed)
        if self.randomized_policy == "randomized_uniform":
            self._phase = self._rng.randrange(self.config.epoch_us)

    def _raw_policy(self, sample, score):
        if self._rng is None:
            self._start_random_epoch()
        capacity = self.config.raw_capacity
        if self.randomized_policy == "reservoir":
            self._seen += 1
            # Drawing at every observation preserves common random numbers across
            # budgets without changing Algorithm R's marginal uniform sampling.
            slot = self._rng.randrange(self._seen)
            timestamp = sample.timestamp_us
            if self._seen <= capacity:
                self._reservoir_slots.append(timestamp)
                self._records[timestamp] = RawRecord(sample, int(Reason.BACKGROUND))
            elif slot < capacity:
                del self._records[self._reservoir_slots[slot]]
                self._reservoir_slots[slot] = timestamp
                self._records[timestamp] = RawRecord(sample, int(Reason.BACKGROUND))
        else:
            # Target j is (j*T + phase)/K from epoch start. Integer arithmetic
            # avoids rounding a target into a different microsecond or epoch.
            position = (sample.timestamp_us - self._epoch) * capacity
            if (
                self._next_target < capacity
                and position >= self._next_target * self.config.epoch_us + self._phase
            ):
                self._emit(sample, Reason.PERIODIC, capacity - len(self._records))
                # A long gap can cross several targets: retain this sample once,
                # then skip targets already passed, never duplicate an observation.
                self._next_target = (position - self._phase) // self.config.epoch_us + 1
