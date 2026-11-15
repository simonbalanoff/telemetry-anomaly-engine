"""Training-only receiver diversity without replacing the original pilot model."""

from dataclasses import dataclass

import numpy as np

from retention.native_model import CHUNK, annotation_mask, fit_native_model
from run_retention_randomized import load_frozen_model

NAMES = ("level", "pca_1", "pca_2", "pca_3", "pca_4", "pca_5")
CAPTURE_MODELS = ("difference", "level", "pca_3", "disabled")


@dataclass(frozen=True)
class ReceiverBank:
    original: object
    basis: np.ndarray
    thresholds: np.ndarray

    def scores(self, values):
        normalized = (
            np.asarray(values, dtype=float) - self.original.mean
        ) / self.original.sigma
        original_scores = self.original.scores(values)
        columns = [original_scores[:, 0]]
        for rank in range(1, 6):
            if rank == 3:
                columns.append(original_scores[:, 1])
            else:
                basis = self.basis[:, :rank]
                residual = normalized - (normalized @ basis) @ basis.T
                columns.append(np.mean(residual**2, axis=1))
        return np.column_stack(columns)

    def to_dict(self):
        return dict(
            names=list(NAMES),
            original=self.original.to_dict(),
            basis=self.basis.tolist(),
            thresholds=self.thresholds.tolist(),
            interpretation="PCA ranks share normalization and are correlated receivers, not independent trials",
        )

    @classmethod
    def from_dict(cls, data):
        if data["names"] != list(NAMES):
            raise ValueError("Unexpected receiver bank schema")
        return cls(
            load_frozen_model(data["original"]),
            np.asarray(data["basis"]),
            np.asarray(data["thresholds"]),
        )


def fit_bank(timestamps, values, training_events, original, output):
    expanded = fit_native_model(
        timestamps,
        values,
        training_events,
        original.training_end_us,
        output / "expanded_training_scores.npy",
        original.quantile,
        components=5,
    )
    if not np.array_equal(expanded.mean, original.mean) or not np.array_equal(
        expanded.sigma, original.sigma
    ):
        raise ValueError(
            "Additional receivers must reuse the reference training normalization exactly"
        )
    bank = ReceiverBank(original, expanded.basis, np.zeros(len(NAMES)))
    stop = int(np.searchsorted(timestamps, original.training_end_us))
    eligible = ~annotation_mask(timestamps[:stop], training_events)
    scores = np.lib.format.open_memmap(
        output / "bank_training_scores.npy",
        mode="w+",
        dtype="<f8",
        shape=(original.training_count, len(NAMES)),
    )
    cursor = 0
    for first in range(0, stop, CHUNK):
        batch = values[first : min(first + CHUNK, stop)][
            eligible[first : first + CHUNK]
        ]
        if len(batch):
            scores[cursor : cursor + len(batch)] = bank.scores(batch)
            cursor += len(batch)
    if cursor != original.training_count:
        raise ValueError("Receiver calibration eligibility differs from reference")
    scores.flush()
    thresholds = np.array(
        [np.quantile(scores[:, i], original.quantile) for i in range(len(NAMES))]
    )
    # Preserve the original pilot's decision boundaries exactly, not just approximately.
    thresholds[0], thresholds[3] = original.thresholds
    return ReceiverBank(original, expanded.basis, thresholds)
