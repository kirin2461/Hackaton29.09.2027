"""Триангуляция рельефа методом Делоне (День 3).

Строим низкополигональную (low-poly) поверхность местности:
  1. Генерируем (или получаем) набор точек с высотами (x, y, z);
  2. scipy.spatial.Delaunay строит триангуляцию проекции точек
     на плоскость XY;
  3. Отдаём фронтенду два плоских массива — vertices и faces,
     из которых Three.js собирает BufferGeometry.

Демо-рельеф — аналитическая функция (пара холмов и ложбина),
но функция `triangulate` принимает любые точки: при наличии
реальной ЦМР (SRTM и т.п.) достаточно подменить источник точек.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import Delaunay

from ..config import TERRAIN_GRID, TERRAIN_SIZE_M


def demo_height(x: np.ndarray, y: np.ndarray,
                size: float = TERRAIN_SIZE_M) -> np.ndarray:
    """Синтетическая высота рельефа (метры) в точке (x, y).

    Сумма гауссовых холмов + пологая волнистость — даёт наглядный
    low-poly ландшафт после триангуляции.
    """
    s = size
    z = (
        30 * np.exp(-(((x - 0.30 * s) ** 2 + (y - 0.35 * s) ** 2) / (2 * (0.12 * s) ** 2)))
        + 18 * np.exp(-(((x - 0.70 * s) ** 2 + (y - 0.65 * s) ** 2) / (2 * (0.15 * s) ** 2)))
        + 6 * np.sin(x / s * 2 * np.pi) * np.cos(y / s * 2 * np.pi)
    )
    return z


def sample_terrain_points(size: float = TERRAIN_SIZE_M,
                          grid: int = TERRAIN_GRID) -> np.ndarray:
    """Сетка grid×grid точек с лёгким случайным джиттером.

    Джиттер убирает вырожденные случаи Делоне (4 точки на одной
    окружности у правильной сетки) и даёт более «естественный»
    low-poly узор. random.seed фиксирован — рельеф стабилен
    между перезапусками сервера.
    """
    rng = np.random.default_rng(seed=42)
    xs = np.linspace(0, size, grid)
    ys = np.linspace(0, size, grid)
    xx, yy = np.meshgrid(xs, ys)
    jitter = (size / grid) * 0.25
    xx = xx + rng.uniform(-jitter, jitter, xx.shape)
    yy = yy + rng.uniform(-jitter, jitter, yy.shape)
    zz = demo_height(xx, yy, size)
    return np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])


def triangulate(points: np.ndarray) -> dict:
    """Делоне-триангуляция облака точек (N, 3) -> vertices + faces.

    Возвращает:
      vertices: [x0,y0,z0, x1,y1,z1, ...]  — плоский массив вершин;
      faces:    [a0,b0,c0, a1,b1,c1, ...]  — индексы вершин треугольников;
      bounds:   охват рельефа для центровки камеры.
    """
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3 or len(pts) < 3:
        raise ValueError("Нужно не меньше трёх точек вида (x, y, z)")

    tri = Delaunay(pts[:, :2])  # триангулируем проекцию на XY

    return {
        "vertices": np.round(pts, 2).ravel().tolist(),
        "faces": tri.simplices.astype(int).ravel().tolist(),
        "bounds": [
            float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max()),
        ],
        "point_count": int(len(pts)),
        "triangle_count": int(len(tri.simplices)),
    }


def terrain_mesh(size: float = TERRAIN_SIZE_M) -> dict:
    """Готовый ответ для GET /api/terrain/mesh — демо-рельеф.

    size подгоняется под охват геоданных, чтобы рельеф накрывал
    всю карту (для реальных слоёв OSM она не обязана быть 1000×1000).
    """
    return triangulate(sample_terrain_points(size=size))
