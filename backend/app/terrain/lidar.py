"""Лидарный рельеф из облака точек (LAS/LAZ).

Пайплайн:
  1. laspy читает LAS/LAZ (LAZ — через пакет lazrs);
  2. точки класса 2 (ground) → ЦМР: биннинг в регулярную сетку,
     средняя высота по ячейке, пустоты — ближайшим соседом,
     лёгкое сглаживание 3×3;
  3. продукты хранятся нормированными в [0, 1]² и масштабируются
     под охват текущего квартала при отдаче — поэтому лидарный
     рельеф переживает смену района;
  4. для визуализации облако субсэмплируется до ~400k точек,
     цвет — классический лидарный градиент по высоте.

Демо-файл app/data/lidar_demo.laz — фрагмент открытого датасета
Autzen Stadium (USGS 3DEP, public domain), ~1.8 млн точек.
В проде сюда же ложится LAZ с облёта площадки дроном.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

# Амплитуда рельефа при отдаче: доля от размера карты
# (для квартала 1.35 км даёт ~60 м перепада — правдоподобно
# для Москвы, но достаточно рельефно для демо).
Z_AMPLITUDE_REL = 0.045
GRID_N = 150            # разрешение ЦМР (150×150 ячеек)
MAX_RENDER_POINTS = 300_000  # потолок облака для WebGL


# --- внутреннее состояние (одно на процесс) ----------------------
_STATE: dict = {}


def _colormap(t: np.ndarray) -> np.ndarray:
    """Классический лидарный градиент: синий → циан → зелёный →
    жёлтый → красный. t ∈ [0,1], возвращает uint8 (N, 3)."""
    t = np.clip(t, 0.0, 1.0)
    stops = np.array([
        [0.00, 49, 54, 149],    # тёмно-синий
        [0.25, 33, 145, 230],   # циан
        [0.50, 50, 200, 90],    # зелёный
        [0.75, 250, 220, 60],   # жёлтый
        [1.00, 220, 40, 40],    # красный
    ])
    idx = np.searchsorted(stops[:, 0], t, side="right") - 1
    idx = np.clip(idx, 0, len(stops) - 2)
    t0 = stops[idx, 0]
    t1 = stops[idx + 1, 0]
    w = ((t - t0) / np.maximum(t1 - t0, 1e-9))[:, None]
    c = stops[idx, 1:] * (1 - w) + stops[idx + 1, 1:] * w
    return c.astype(np.uint8)


def load(path: str | Path, source_name: str | None = None) -> dict:
    """Читает LAS/LAZ и заполняет состояние: ЦМР + облако точек.

    Возвращает статистику для API. Бросает ValueError, если
    в файле нет классифицированных ground-точек.
    """
    import laspy  # лениво: пакет нужен только этой фиче

    las = laspy.read(str(path))
    n = len(las.x)
    if n < 1000:
        raise ValueError(f"Слишком мало точек в файле: {n}")

    x = np.asarray(las.x, dtype=np.float64)
    y = np.asarray(las.y, dtype=np.float64)
    z = np.asarray(las.z, dtype=np.float64)
    cls = np.asarray(las.classification)

    x0, x1 = float(x.min()), float(x.max())
    y0, y1 = float(y.min()), float(y.max())
    span = max(x1 - x0, y1 - y0)
    if span <= 0:
        raise ValueError("Вырожденный охват облака")

    ground = cls == 2
    if ground.sum() < 500:
        raise ValueError("В файле нет класса ground (2) — "
                         "нужен классифицированный лидар")

    # --- ЦМР: средняя высота земли по ячейкам сетки GRID_N² ---
    gx = ((x[ground] - x0) / (x1 - x0) * (GRID_N - 1)).astype(np.int32)
    gy = ((y[ground] - y0) / (y1 - y0) * (GRID_N - 1)).astype(np.int32)
    cell = gy * GRID_N + gx
    sums = np.bincount(cell, weights=z[ground],
                       minlength=GRID_N * GRID_N)
    counts = np.bincount(cell, minlength=GRID_N * GRID_N)
    with np.errstate(invalid="ignore"):
        dtm = (sums / np.maximum(counts, 1)).reshape(GRID_N, GRID_N)
    dtm[counts.reshape(GRID_N, GRID_N) == 0] = np.nan

    # Пустые ячейки — ближайшей занятой (cKDTree).
    from scipy.ndimage import uniform_filter
    from scipy.spatial import cKDTree
    yy, xx = np.mgrid[0:GRID_N, 0:GRID_N]
    filled = ~np.isnan(dtm)
    tree = cKDTree(np.column_stack([yy[filled], xx[filled]]))
    _, idx = tree.query(np.column_stack([yy[~filled], xx[~filled]]))
    dtm[~filled] = dtm[filled][idx]
    dtm = uniform_filter(dtm, size=3)  # лёгкое сглаживание

    z_min = float(dtm.min())
    dtm_norm = (dtm - z_min) / max(float(dtm.max() - z_min), 1e-9)

    # --- облако для рендера: субсэмплинг + градиент по высоте ---
    stride = max(1, n // MAX_RENDER_POINTS)
    sel = slice(0, n, stride)
    px = ((x[sel] - x0) / (x1 - x0)).astype(np.float32)
    py = ((y[sel] - y0) / (y1 - y0)).astype(np.float32)
    pz_raw = z[sel]
    pz = ((pz_raw - z_min) / max(float(z.max() - z_min), 1e-9))
    colors = _colormap(pz)
    pz = (pz_raw - float(z[ground].min()))
    pz = (pz / max(float(z[ground].max() - z[ground].min()), 1e-9))
    pz = pz.astype(np.float32)

    _STATE.clear()
    _STATE.update({
        "dtm": dtm_norm.astype(np.float32),
        "cloud_xy": np.column_stack([px, py]),
        "cloud_z": pz,
        "cloud_colors": colors,
        "meta": {
            "source": source_name or Path(path).name,
            "points_total": int(n),
            "points_ground": int(ground.sum()),
            "points_rendered": int(len(px)),
            "extent_m": round(span, 1),
            "z_range_m": round(float(z.max() - z.min()), 1),
        },
    })
    return status()


def load_precomputed(path: str | Path) -> dict:
    """Мгновенная загрузка заранее обработанного облака (.npz).

    Демо на слабом сервере: LAZ жмётся минуту, а готовые продукты
    (ЦМР + субсэмплированное облако) поднимаются за доли секунды.
    """
    import json as _json
    z = np.load(str(path))
    _STATE.clear()
    _STATE.update({
        "dtm": z["dtm"],
        "cloud_xy": z["cloud_xy"],
        "cloud_z": z["cloud_z"],
        "cloud_colors": z["cloud_colors"],
        "meta": _json.loads(str(z["meta"])),
    })
    return status()


def active() -> bool:
    return bool(_STATE)


def status() -> dict:
    if not _STATE:
        return {"active": False}
    return {"active": True, **_STATE["meta"]}


def clear() -> None:
    _STATE.clear()


def mesh(size: float) -> dict:
    """Меш лидарного рельефа под размер карты (формат /api/terrain/mesh)."""
    dtm = _STATE["dtm"]
    amp = size * Z_AMPLITUDE_REL
    xs = np.linspace(0, size, GRID_N, dtype=np.float32)
    xx, yy = np.meshgrid(xs, xs)
    zz = dtm * amp
    verts = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])

    # Регулярная сетка → два треугольника на ячейку.
    r, cidx = np.mgrid[0:GRID_N - 1, 0:GRID_N - 1]
    a = (r * GRID_N + cidx).ravel()
    b = a + 1
    cc = a + GRID_N
    dd = cc + 1
    # Порядок обхода — против часовой в XY (как у scipy Delaunay),
    # иначе после переноса в сцену (y -> -z) грани смотрят вниз.
    faces = np.column_stack([
        np.column_stack([a, b, cc]),
        np.column_stack([b, dd, cc]),
    ]).ravel()

    return {
        "vertices": np.round(verts, 2).ravel().tolist(),
        "faces": faces.astype(int).tolist(),
        "bounds": [0.0, 0.0, float(size), float(size)],
        "point_count": int(len(verts)),
        "triangle_count": int(faces.size // 3),
        "source": "lidar",
    }


def cloud_bytes(size: float) -> bytes:
    """Бинарный формат облака: uint32 N + float32 xyz × N + uint8 rgb × N.

    Z масштабируется той же амплитудой, что и меш, плюс небольшой
    подъём, чтобы точки читались над поверхностью.
    """
    xy = _STATE["cloud_xy"] * np.float32(size)
    z = _STATE["cloud_z"] * np.float32(size * Z_AMPLITUDE_REL) + np.float32(0.8)
    pos = np.column_stack([xy[:, 0], xy[:, 1], z]).astype(np.float32)
    n = len(pos)
    return (struct.pack("<I", n)
            + pos.tobytes()
            + _STATE["cloud_colors"].tobytes())
