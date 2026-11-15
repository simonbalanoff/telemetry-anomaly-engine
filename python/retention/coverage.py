"""Bounded coverage control: novelty-gated background slots plus trigger context.

This is a comparison candidate, not a claimed new sampling algorithm. A fixed
fraction of raw slots still belongs to trigger/context capture. Within each
background time stratum, keep the observation furthest from already retained
background observations in frozen training-standardized units. Replacement uses
only past/current observations and does not expand the raw quota.
"""

import math

import numpy as np

from retention.codec import RawRecord
from retention.recorder import Reason, Recorder


class CoverageRecorder(Recorder):
    def __init__(self, config, mean, sigma):
        self.mean = np.asarray(mean, dtype=float)
        self.sigma = np.asarray(sigma, dtype=float)
        if (
            self.mean.shape != (6,)
            or self.sigma.shape != (6,)
            or not np.isfinite(self.mean).all()
            or not np.isfinite(self.sigma).all()
            or np.any(self.sigma <= 0)
        ):
            raise ValueError(
                "Coverage normalization requires six finite means and positive scales"
            )
        super().__init__("adaptive", config)

    def _reset(self):
        super()._reset()
        self._coverage_vectors = {}
        self._coverage_slot = None
        self._coverage_timestamp = None
        self._coverage_priority = -1.0

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
        if reserved:
            slot = self._sample_slot(sample, reserved)
            vector = (np.asarray(sample.values) - self.mean) / self.sigma
            if slot != self._coverage_slot:
                self._coverage_slot = slot
                self._coverage_timestamp = None
                self._coverage_priority = -1.0
            others = [
                value
                for timestamp, value in self._coverage_vectors.items()
                if timestamp != self._coverage_timestamp
            ]
            priority = (
                min(float(np.sum((vector - value) ** 2)) for value in others)
                if others
                else 0.0
            )
            if self._coverage_timestamp is None:
                if self._emit(
                    sample, Reason.BACKGROUND, reserved - self._background_used
                ):
                    self._background_used += 1
                    self._coverage_timestamp = sample.timestamp_us
                    self._coverage_vectors[sample.timestamp_us] = vector
                    self._coverage_priority = priority
            elif priority > self._coverage_priority:
                previous = self._coverage_timestamp
                # Protect records already requested as trigger context. Replacing
                # such a record would turn a coverage comparison into context eviction.
                if self._records[previous].reason == int(Reason.BACKGROUND):
                    del self._records[previous]
                    del self._coverage_vectors[previous]
                    self._records[sample.timestamp_us] = RawRecord(
                        sample, int(Reason.BACKGROUND)
                    )
                    self._coverage_vectors[sample.timestamp_us] = vector
                    self._coverage_timestamp = sample.timestamp_us
                    self._coverage_priority = priority
            # Suppress only the base recorder's periodic background step. Keep
            # its trigger/context quotas, ordering, history, and epoch semantics.
            self._last_background_slot = slot
        super()._raw_policy(sample, score)
