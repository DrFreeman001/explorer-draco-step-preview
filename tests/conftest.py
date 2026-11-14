"""Fixtures de test, sans dépendance au code testé."""
import os
from dataclasses import dataclass

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@dataclass
class Mesh:
    positions: np.ndarray
    faces: np.ndarray


def make_cube() -> Mesh:
    positions = np.array(
        [[0, 0, 0], [20, 0, 0], [20, 20, 0], [0, 20, 0], [0, 0, 20], [20, 0, 20], [20, 20, 20], [0, 20, 20]],
        dtype=np.float32,
    )
    faces = np.array(
        [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
         [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]],
        dtype=np.uint32,
    )
    return Mesh(positions, faces)


def make_grid(cells: int) -> Mesh:
    """Surface ondulée de cells x cells carrés, soit 2 * cells² triangles."""
    side = np.linspace(-50.0, 50.0, cells + 1, dtype=np.float32)
    x, y = np.meshgrid(side, side)
    z = 5.0 * np.sin(x / 7.0) * np.cos(y / 9.0)
    positions = np.stack([x.ravel(), y.ravel(), z.ravel()], axis=1).astype(np.float32)
    index = np.arange((cells + 1) ** 2, dtype=np.uint32).reshape(cells + 1, cells + 1)
    a, b = index[:-1, :-1].ravel(), index[:-1, 1:].ravel()
    c, d = index[1:, :-1].ravel(), index[1:, 1:].ravel()
    faces = np.concatenate([np.stack([a, b, d], axis=1), np.stack([a, d, c], axis=1)])
    return Mesh(positions, np.ascontiguousarray(faces))


@pytest.fixture
def cube() -> Mesh:
    return make_cube()


@pytest.fixture
def dense() -> Mesh:
    return make_grid(120)
