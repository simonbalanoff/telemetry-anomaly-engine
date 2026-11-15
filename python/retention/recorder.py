"""Bounded, causal recorder policies; callers supply only observations and scores."""

from collections import deque
from dataclasses import dataclass
from enum import IntFlag
import math

from retention.codec import (
    HEADER,
    RAW_BYTES,
    SUMMARY_BYTES,
    Packet,
    RawRecord,
    Sample,
    SummaryRecord,
)


class Reason(IntFlag):
    PERIODIC = 1
    TRIGGER = 2
    PRE_TRIGGER = 4
    POST_TRIGGER = 8
    BACKGROUND = 16


@dataclass(frozen=True)
class RecorderConfig:
    epoch_us: int = 3_600_000_000
    budget_bytes: int = 1024
    threshold: float = 6.0
    pre_trigger_samples: int = 8
    post_trigger_samples: int = 4
    background_fraction: float = 0.2

    def __post_init__(self):
        if type(self.epoch_us) is not int or not 0 < self.epoch_us < 2**63:
            raise ValueError("Epoch duration must be a positive int64")
        if (
            type(self.budget_bytes) is not int
            or not HEADER.size + SUMMARY_BYTES <= self.budget_bytes < 2**32
        ):
            raise ValueError("Budget must fit at least one summary and header")
        if not math.isfinite(self.threshold) or self.threshold < 0:
            raise ValueError("Threshold must be finite and nonnegative")
        if (
            type(self.pre_trigger_samples) is not int
            or self.pre_trigger_samples < 0
            or type(self.post_trigger_samples) is not int
            or self.post_trigger_samples < 0
        ):
            raise ValueError("Context sizes must be nonnegative integers")
        if (
            not math.isfinite(self.background_fraction)
            or not 0 <= self.background_fraction <= 1
        ):
            raise ValueError("Background fraction must be in [0, 1]")

    @property
    def raw_capacity(self) -> int:
        return (self.budget_bytes - HEADER.size) // RAW_BYTES


class Recorder:
    """One active epoch packet plus a bounded ring; finished packets leave the object.

    observe() may return a finalized previous packet. finish() flushes the active
    epoch. There is no cross-epoch history, budget borrowing, or future input.
    """

    POLICIES = ("uniform", "summaries", "threshold", "adaptive")

    def __init__(self, policy: str, config: RecorderConfig):
        if policy not in self.POLICIES:
            raise ValueError(f"Unknown retention policy: {policy}")
        self.policy, self.config = policy, config
        self._epoch = None
        self._last_timestamp = None
        self._sealed_epoch = None
        self._reset()

    def _reset(self):
        self._records = {}
        self._history = deque(maxlen=self.config.pre_trigger_samples)
        self._summaries = {}
        self._last_periodic_slot = -1
        self._last_background_slot = -1
        self._background_used = 0
        self._trigger_used = 0
        self._post_remaining = 0

    def _emit(self, sample: Sample, reason: Reason, allowance: int) -> bool:
        if sample.timestamp_us in self._records or allowance <= 0:
            return False
        self._records[sample.timestamp_us] = RawRecord(sample, int(reason))
        return True

    def _sample_slot(self, sample: Sample, capacity: int) -> int:
        return (sample.timestamp_us - self._epoch) * capacity // self.config.epoch_us

    def _raw_policy(self, sample: Sample, score: float):
        capacity = self.config.raw_capacity
        if self.policy == "uniform":
            slot = self._sample_slot(sample, capacity)
            if slot != self._last_periodic_slot:
                self._emit(sample, Reason.PERIODIC, capacity - len(self._records))
                self._last_periodic_slot = slot
            return
        if self.policy == "threshold":
            if score >= self.config.threshold:
                self._emit(sample, Reason.TRIGGER, capacity - len(self._records))
            return

        reserved = math.ceil(capacity * self.config.background_fraction)
        trigger_capacity = capacity - reserved
        if reserved:
            slot = self._sample_slot(sample, reserved)
            if slot != self._last_background_slot:
                if self._emit(
                    sample, Reason.BACKGROUND, reserved - self._background_used
                ):
                    self._background_used += 1
                self._last_background_slot = slot
        if score >= self.config.threshold:
            remaining = trigger_capacity - self._trigger_used
            current_needed = int(sample.timestamp_us not in self._records)
            candidates = [
                previous
                for previous in self._history
                if previous.timestamp_us not in self._records
            ]
            affordable = max(0, remaining - current_needed)
            # Preserve the most recent context if the full ring cannot fit.
            selected = candidates[-affordable:] if affordable else []
            for previous in selected:
                if self._emit(
                    previous, Reason.PRE_TRIGGER, trigger_capacity - self._trigger_used
                ):
                    self._trigger_used += 1
            if self._emit(
                sample, Reason.TRIGGER, trigger_capacity - self._trigger_used
            ):
                self._trigger_used += 1
            self._post_remaining = self.config.post_trigger_samples
        elif self._post_remaining:
            if self._emit(
                sample, Reason.POST_TRIGGER, trigger_capacity - self._trigger_used
            ):
                self._trigger_used += 1
            self._post_remaining -= 1
        self._history.append(sample)

    def _summary_policy(self, sample: Sample):
        capacity = (self.config.budget_bytes - HEADER.size) // SUMMARY_BYTES
        slot = self._sample_slot(sample, capacity)
        previous = self._summaries.get(slot)
        if previous is None:
            start = (
                self._epoch + (slot * self.config.epoch_us + capacity - 1) // capacity
            )
            self._summaries[slot] = SummaryRecord(
                start, sample.values, sample.values, 1
            )
        else:
            self._summaries[slot] = SummaryRecord(
                previous.start_us,
                tuple(min(a, b) for a, b in zip(previous.minimum, sample.values)),
                tuple(max(a, b) for a, b in zip(previous.maximum, sample.values)),
                previous.count + 1,
            )

    def observe(self, sample: Sample, score: float = 0.0) -> Packet | None:
        if not math.isfinite(score) or score < 0:
            raise ValueError("Scores must be finite and nonnegative")
        if (
            self._last_timestamp is not None
            and sample.timestamp_us <= self._last_timestamp
        ):
            raise ValueError("Observations must be strictly chronological")
        epoch = sample.timestamp_us // self.config.epoch_us * self.config.epoch_us
        if self._sealed_epoch is not None and epoch <= self._sealed_epoch:
            raise ValueError("Cannot reopen a finalized epoch")
        finished = None
        if self._epoch is not None and epoch != self._epoch:
            finished = self.finish()
        self._epoch = epoch
        self._last_timestamp = sample.timestamp_us
        if self.policy == "summaries":
            self._summary_policy(sample)
        else:
            self._raw_policy(sample, score)
        return finished

    def finish(self) -> Packet | None:
        if self._epoch is None:
            return None
        records = (
            tuple(self._summaries[key] for key in sorted(self._summaries))
            if self.policy == "summaries"
            else tuple(self._records[key] for key in sorted(self._records))
        )
        packet = Packet(
            self._epoch, self.config.epoch_us, self.config.budget_bytes, records
        )
        packet.encode()  # Enforce the invariant at the actual serialization boundary.
        self._sealed_epoch = self._epoch
        self._epoch = None
        self._reset()
        return packet
