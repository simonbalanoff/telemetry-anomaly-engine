"""Adjacent-pair background control for future temporal receivers.

Commit two consecutive original observations within a background time stratum,
provided the native gap is at most the declared reset gap. Unpaired observations
are not emitted as background. This trades temporal spread for usable transitions.
"""

import math

from retention.codec import RawRecord
from retention.recorder import Reason, Recorder


class BurstRecorder(Recorder):
    def __init__(self, config, reset_gap_us=150000000):
        if type(reset_gap_us) is not int or reset_gap_us <= 0:
            raise ValueError("Reset gap must be a positive integer")
        self.reset_gap_us = reset_gap_us
        super().__init__("adaptive", config)

    def _reset(self):
        super()._reset()
        self._pending_background = None
        self._pending_slot = None
        self._completed_slot = -1

    def _emit(self, sample, reason, allowance):
        existing = self._records.get(sample.timestamp_us)
        if existing is not None:
            self._records[sample.timestamp_us] = RawRecord(
                sample, existing.reason | int(reason)
            )
            return False
        return super()._emit(sample, reason, allowance)

    def _raw_policy(self, sample, score):
        reserved = math.ceil(self.config.raw_capacity * self.config.background_fraction)
        pairs = reserved // 2
        if reserved:
            # Suppress the singleton background step while preserving base quotas.
            self._last_background_slot = self._sample_slot(sample, reserved)
        if pairs:
            slot = self._sample_slot(sample, pairs)
            previous = self._pending_background
            if previous is not None:
                if (
                    self._pending_slot == slot
                    and sample.timestamp_us - previous.timestamp_us <= self.reset_gap_us
                ):
                    for observation in (previous, sample):
                        if self._emit(
                            observation,
                            Reason.BACKGROUND,
                            reserved - self._background_used,
                        ):
                            self._background_used += 1
                    self._completed_slot = slot
                self._pending_background = None
            if self._completed_slot != slot:
                self._pending_background = sample
                self._pending_slot = slot
        super()._raw_policy(sample, score)
