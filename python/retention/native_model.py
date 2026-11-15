"""Training-only normalization and frozen receivers for the native-data pilot."""

from dataclasses import dataclass

import numpy as np

CHUNK = 262144
RECEIVERS = ("level", "pca")


def observation_interval(timestamps, start, stop):
    left = int(np.searchsorted(timestamps, start))
    right = int(
        np.searchsorted(timestamps, stop, side="right" if start == stop else "left")
    )
    return left, right


def annotation_mask(timestamps, events):
    excluded = np.zeros(len(timestamps), dtype=bool)
    for event in events:
        left, right = observation_interval(
            timestamps, event["start_us"], event["end_us"]
        )
        excluded[left:right] = True
    return excluded


@dataclass(frozen=True)
class NativeModel:
    mean: np.ndarray
    sigma: np.ndarray
    basis: np.ndarray
    thresholds: np.ndarray
    training_count: int
    training_end_us: int
    quantile: float

    def scores(self, values):
        normalized = (np.asarray(values, dtype=float) - self.mean) / self.sigma
        residual = normalized - (normalized @ self.basis) @ self.basis.T
        return np.column_stack(
            (np.max(np.abs(normalized), axis=1), np.mean(residual**2, axis=1))
        )

    def to_dict(self):
        return dict(
            mean=self.mean.tolist(),
            sigma=self.sigma.tolist(),
            basis=self.basis.tolist(),
            thresholds=dict(zip(RECEIVERS, self.thresholds.tolist())),
            training_count=self.training_count,
            training_end_us=self.training_end_us,
            quantile=self.quantile,
            pca_components=self.basis.shape[1],
        )


def fit_native_model(
    timestamps,
    values,
    events,
    training_end_us,
    score_path,
    quantile=0.999,
    components=3,
):
    """Fit moments and score quantiles on eligible native training samples only."""
    stop = int(np.searchsorted(timestamps, training_end_us))
    eligible = ~annotation_mask(timestamps[:stop], events)
    count = 0
    mean, scatter = np.zeros(6), np.zeros((6, 6))
    for first in range(0, stop, CHUNK):
        batch = np.asarray(
            values[first : min(first + CHUNK, stop)][eligible[first : first + CHUNK]],
            dtype=float,
        )
        if not len(batch):
            continue
        batch_mean = batch.mean(axis=0)
        centered = batch - batch_mean
        delta = batch_mean - mean
        total = count + len(batch)
        scatter += (
            centered.T @ centered + np.outer(delta, delta) * count * len(batch) / total
        )
        mean += delta * len(batch) / total
        count = total
    if count < 2:
        raise ValueError("Insufficient eligible native training observations")
    covariance = scatter / (count - 1)
    sigma = np.maximum(1e-12, np.sqrt(np.diag(covariance)))
    _, eigenvectors = np.linalg.eigh(covariance / np.outer(sigma, sigma))
    basis = eigenvectors[:, ::-1][:, :components]
    model = NativeModel(
        mean, sigma, basis, np.zeros(2), count, training_end_us, quantile
    )
    scores = np.lib.format.open_memmap(
        score_path, mode="w+", dtype="<f8", shape=(count, 2)
    )
    cursor = 0
    for first in range(0, stop, CHUNK):
        batch = values[first : min(first + CHUNK, stop)][
            eligible[first : first + CHUNK]
        ]
        if len(batch):
            scores[cursor : cursor + len(batch)] = model.scores(batch)
            cursor += len(batch)
    scores.flush()
    thresholds = np.array(
        [np.quantile(scores[:, column], quantile) for column in range(2)]
    )
    return NativeModel(mean, sigma, basis, thresholds, count, training_end_us, quantile)


def causal_capture_scores(timestamps, values, sigma, reset_gap_us=150_000_000):
    """First difference in frozen training units; never compare across long gaps."""
    scores = np.zeros(len(timestamps))
    for first in range(1, len(timestamps), CHUNK):
        stop = min(first + CHUNK, len(timestamps))
        difference = (
            np.asarray(values[first:stop], dtype=float) - values[first - 1 : stop - 1]
        )
        scores[first:stop] = np.max(np.abs(difference) / sigma, axis=1)
        scores[first:stop][np.diff(timestamps[first - 1 : stop]) > reset_gap_us] = 0
    return scores
