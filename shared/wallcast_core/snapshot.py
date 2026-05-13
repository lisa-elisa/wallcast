"""Atomic snapshot of shared camera state - pass between threads by value."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CameraSnapshot:
    """Immutable view of the most recent processed frame.

    `frame`, `M`, `corners` may be None when no camera is initialised yet.
    Pass copies (np.ndarray.copy) when populating to avoid aliasing.
    """

    frame: np.ndarray | None
    M: np.ndarray | None
    corners: np.ndarray | None
    found: bool
