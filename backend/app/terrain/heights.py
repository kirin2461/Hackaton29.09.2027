"""Серверный сэмплер высот рельефа (геодезия).

Фронтенд считает высоты raycast-ом по мешу, а бэкенду высоты нужны
для профиля трассы (продольный разрез) и паспорта объекта. Чтобы
обе стороны видели один и тот же рельеф, сэмплер строится из того
же меша, что отдаёт GET /api/terrain/mesh: линейная интерполяция
по вершинам триангуляции (LinearNDInterpolator по XY).

Интерполятор кэшируется: пересоздаётся только при смене источника
рельефа (демо ↔ лидар) или размера карты.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import LinearNDInterpolator

from . import lidar
from .triangulation import terrain_mesh

_cache: dict = {}


def _current_mesh(size: float) -> dict:
    """Тот же выбор источника, что в routes_terrain.get_terrain_mesh."""
    if lidar.active():
        return lidar.mesh(size)
    return terrain_mesh(size=size)


def get_sampler(size: float):
    """Возвращает функцию h(x, y) -> высота рельефа в метрах.

    size — размер карты (как в /api/terrain/mesh, с запасом ×1.05).
    За пределами меша возвращается высота ближайшей вершины
    (nearest fallback), чтобы профиль не обрывался на краю.
    """
    key = (lidar.active(), round(size, 1))
    if _cache.get("key") != key:
        mesh = _current_mesh(size)
        v = np.asarray(mesh["vertices"], dtype=float).reshape(-1, 3)
        lin = LinearNDInterpolator(v[:, :2], v[:, 2])
        # Nearest — запасной вариант вне выпуклой оболочки.
        from scipy.interpolate import NearestNDInterpolator
        near = NearestNDInterpolator(v[:, :2], v[:, 2])
        _cache.clear()
        _cache.update({"key": key, "lin": lin, "near": near})

    lin, near = _cache["lin"], _cache["near"]

    def sample(x: float, y: float) -> float:
        z = lin([x, y])[0]
        if np.isnan(z):
            z = near([x, y])[0]
        return float(z)

    return sample
