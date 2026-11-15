"""Training-only ridge AR(1) receiver requiring consecutive native observations.

Sparse retained observations are never treated as consecutive. A forecast score
can count as retained evidence only when both original endpoints survive.
"""

from dataclasses import dataclass

import numpy as np

from retention.native_model import CHUNK, annotation_mask


@dataclass(frozen=True)
class ForecastReceiver:
    mean: np.ndarray
    sigma: np.ndarray
    coefficients: np.ndarray
    residual_sigma: np.ndarray
    threshold: float
    training_pairs: int
    training_end_us: int
    reset_gap_us: int = 150000000
    ridge: float = 0.001
    quantile: float = 0.999

    def scores(self, timestamps, values):
        result = np.full(len(timestamps), np.nan)
        for first in range(1, len(timestamps), CHUNK):
            stop = min(first + CHUNK, len(timestamps))
            previous = (
                np.asarray(values[first - 1 : stop - 1], dtype=float) - self.mean
            ) / self.sigma
            current = (
                np.asarray(values[first:stop], dtype=float) - self.mean
            ) / self.sigma
            prediction = previous @ self.coefficients[:6] + self.coefficients[6]
            score = np.max(np.abs(current - prediction) / self.residual_sigma, axis=1)
            score[np.diff(timestamps[first - 1 : stop]) > self.reset_gap_us] = np.nan
            result[first:stop] = score
        return result

    def to_dict(self):
        return {
            name: value.tolist() if isinstance(value, np.ndarray) else value
            for name, value in vars(self).items()
        }


def fit_forecast(
    timestamps,
    values,
    training_events,
    normalizer,
    output,
    ridge=0.001,
    reset_gap_us=150000000,
):
    if not np.isfinite(ridge) or ridge <= 0:
        raise ValueError("Ridge regularization must be finite and positive")
    if type(reset_gap_us) is not int or reset_gap_us <= 0:
        raise ValueError("Reset gap must be a positive integer")
    stop = int(np.searchsorted(timestamps, normalizer.training_end_us))
    clean = ~annotation_mask(timestamps[:stop], training_events)
    eligible = clean[1:] & clean[:-1] & (np.diff(timestamps[:stop]) <= reset_gap_us)
    count = int(eligible.sum())
    if count < 8:
        raise ValueError("Insufficient eligible consecutive training pairs")
    gram, cross = np.zeros((7, 7)), np.zeros((7, 6))
    for first in range(1, stop, CHUNK):
        end = min(first + CHUNK, stop)
        selection = eligible[first - 1 : end - 1]
        previous = (
            np.asarray(values[first - 1 : end - 1][selection], dtype=float)
            - normalizer.mean
        ) / normalizer.sigma
        current = (
            np.asarray(values[first:end][selection], dtype=float) - normalizer.mean
        ) / normalizer.sigma
        design = np.column_stack((previous, np.ones(len(previous))))
        gram += design.T @ design
        cross += design.T @ current
    penalty = np.diag([ridge * count] * 6 + [0])
    coefficients = np.linalg.solve(gram + penalty, cross)
    scatter = np.zeros(6)
    for first in range(1, stop, CHUNK):
        end = min(first + CHUNK, stop)
        selection = eligible[first - 1 : end - 1]
        previous = (
            np.asarray(values[first - 1 : end - 1][selection], dtype=float)
            - normalizer.mean
        ) / normalizer.sigma
        current = (
            np.asarray(values[first:end][selection], dtype=float) - normalizer.mean
        ) / normalizer.sigma
        residual = current - previous @ coefficients[:6] - coefficients[6]
        scatter += np.sum(residual**2, axis=0)
    residual_sigma = np.maximum(1e-12, np.sqrt(scatter / count))
    provisional = ForecastReceiver(
        normalizer.mean,
        normalizer.sigma,
        coefficients,
        residual_sigma,
        0.0,
        count,
        normalizer.training_end_us,
        reset_gap_us,
        ridge,
        normalizer.quantile,
    )
    scores = provisional.scores(timestamps[:stop], values[:stop])[1:][eligible]
    np.save(output / "forecast_training_scores.npy", scores)
    threshold = float(np.quantile(scores, normalizer.quantile))
    return ForecastReceiver(
        normalizer.mean,
        normalizer.sigma,
        coefficients,
        residual_sigma,
        threshold,
        count,
        normalizer.training_end_us,
        reset_gap_us,
        ridge,
        normalizer.quantile,
    )


def pair_evidence(retained, positive):
    retained, positive = np.asarray(retained, dtype=bool), np.asarray(
        positive, dtype=bool
    )
    if retained.shape != positive.shape or retained.ndim != 1:
        raise ValueError("Retention and positivity must be matching vectors")
    evidence = np.zeros(len(retained), dtype=bool)
    evidence[1:] = retained[1:] & retained[:-1] & positive[1:]
    return evidence
