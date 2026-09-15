"""Мульти-ОКС: кластеризация под общий ствол (§2.11 ТЗ, Спринт 2).

Перспективные ОКС, чьи точки подключения ближе cluster_radius_m,
рассматриваются как кандидаты на СОВМЕСТНОЕ подключение: один ствол
от точки врезки до камеры разветвления, от неё — ветви к каждому ОКС.
Эвристика по близости (Steiner-задача в общем виде NP-сложная);
раздельное подключение — допустимый результат и случается автоматически,
когда кластер состоит из одного ОКС.
"""

from __future__ import annotations

from .model import Building


def cluster_buildings(buildings: dict[str, Building], radius_m: float) -> list[list[Building]]:
    """Жадная кластеризация по близости точек подключения (union-find)."""
    items = list(buildings.values())
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    anchors = [b.anchor for b in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if anchors[i].distance(anchors[j]) <= radius_m:
                union(i, j)

    clusters: dict[int, list[Building]] = {}
    for idx, b in enumerate(items):
        clusters.setdefault(find(idx), []).append(b)

    # Крупные кластеры в начало — им важнее хорошая точка врезки
    return sorted(clusters.values(), key=lambda c: -len(c))
