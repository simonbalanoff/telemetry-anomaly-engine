from collections.abc import Iterator

import numpy as np

from write_binary import (
    ALL_CHANNELS,
    MAX_FILL,
    MAX_STALENESS,
    PERIOD_US,
    Frame,
)


def iter_grid_frames(
    timestamps_us: np.ndarray,
    values: np.ndarray,
) -> Iterator[Frame]:
    timestamps = np.asarray(timestamps_us, dtype=np.int64)
    measurements = np.asarray(values)

    if timestamps.ndim != 1:
        raise ValueError("Timestamps must be one-dimensional")

    if measurements.ndim != 2 or measurements.shape[1] != 6:
        raise ValueError("Measurements must have six columns")

    if len(timestamps) == 0 or len(timestamps) != len(measurements):
        raise ValueError("Invalid telemetry dimensions")

    if np.any(np.diff(timestamps) <= 0):
        raise ValueError("Timestamps must be strictly increasing")

    if not np.all(np.isfinite(measurements)):
        raise ValueError("Measurements must be finite")

    cells = timestamps // PERIOD_US

    last_cell = int(cells[0])
    last_observed = tuple(float(v) for v in measurements[0])
    last_observed = tuple(
        float(v) for v in np.asarray(last_observed, dtype=np.float32)
    )

    staleness = 0

    for i in range(1, len(timestamps)):
        current_cell = int(cells[i])

        if current_cell == last_cell:
            last_observed = tuple(
                float(v) for v in np.asarray(
                    measurements[i], dtype=np.float32
                )
            )
            continue

        yield Frame(
            last_observed,
            ALL_CHANNELS,
            ALL_CHANNELS,
            0,
        )

        for _ in range(last_cell + 1, current_cell):
            staleness = min(staleness + 1, MAX_STALENESS)

            if staleness <= MAX_FILL:
                yield Frame(
                    last_observed,
                    0,
                    ALL_CHANNELS,
                    staleness,
                )
            else:
                yield Frame(
                    (0.0,) * 6,
                    0,
                    0,
                    staleness,
                )

        last_observed = tuple(
            float(v) for v in np.asarray(
                measurements[i], dtype=np.float32
            )
        )

        last_cell = current_cell
        staleness = 0

    yield Frame(
        last_observed,
        ALL_CHANNELS,
        ALL_CHANNELS,
        0,
    )
