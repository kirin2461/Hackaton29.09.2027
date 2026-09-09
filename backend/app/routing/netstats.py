"""Метрики живучести тепловой сети (сетевой анализ графа).

Идея: теплосеть — это взвешенный граф (узлы = вершины полилиний,
рёбра = сегменты труб с длинами). По графу считаем независимые
метрики из теории сетей:

  - энтропия Шеннона распределения длин сегментов (C. Shannon, 1948):
    p_i = L_i / ΣL, H = -Σ p_i·log2(p_i); нормируем на log2(m) —
    показывает равномерность нагрузки сети (0..1);
  - цикломатическое число m - n + p — сколько независимых колец
    в сети (кольцевание = резервирование по СП 124.13330);
  - число Фидлера (M. Fiedler, 1973) — второе собственное значение
    лапласиана графа: алгебраическая связность, «прочность» сети;
  - доля тупиковых узлов (степень 1) — потребители без резерва.

Главное применение — Δ-импакт: как добавление новой ветки (трассы
подключения) меняет эти метрики. Считается мгновенно, поэтому
вызывается и из /api/route/compute (по каждому варианту A*), и из
/api/route/validate (при каждом перетаскивании узла gizmo'м).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# Узлы склеиваем с точностью 1 мм — этого хватает, чтобы стыки
# полилиний из ГИС-данных сходились в один узел графа.
_NODE_PREC = 2


def _key(x: float, y: float) -> tuple[float, float]:
    return (round(x, _NODE_PREC), round(y, _NODE_PREC))


def build_graph(lines: list[list[list[float]]]):
    """Строит граф из списка полилиний.

    Возвращает (nodes, edges): nodes — {ключ: индекс}, edges —
    список (u, v, length). Продольная разбивка сохраняется: каждая
    пара соседних вершин полилинии — отдельное ребро.
    """
    nodes: dict[tuple[float, float], int] = {}
    edges: list[tuple[int, int, float]] = []

    def idx(x: float, y: float) -> int:
        k = _key(x, y)
        if k not in nodes:
            nodes[k] = len(nodes)
        return nodes[k]

    for line in lines:
        for (x1, y1), (x2, y2) in zip(line, line[1:]):
            w = math.hypot(x2 - x1, y2 - y1)
            if w < 1e-6:
                continue
            u, v = idx(x1, y1), idx(x2, y2)
            if u != v:
                edges.append((u, v, w))
    return nodes, edges


def _components(n: int, edges: list[tuple[int, int, float]]) -> int:
    """Число компонент связности (union-find)."""
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for u, v, _ in edges:
        parent[find(u)] = find(v)
    return len({find(i) for i in range(n)}) if n else 0


def _fiedler(n: int, edges: list[tuple[int, int, float]]) -> float:
    """Число Фидлера главной компоненты: собственные значения
    лапласиана, вес ребра = 1/длина (близкие узлы связаны сильнее)."""
    if n < 3:
        return 0.0
    # оставляем только крупнейшую компоненту
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for u, v, _ in edges:
        parent[find(u)] = find(v)
    comp: dict[int, list[int]] = {}
    for i in range(n):
        comp.setdefault(find(i), []).append(i)
    main = max(comp.values(), key=len)
    if len(main) < 3:
        return 0.0
    remap = {old: new for new, old in enumerate(main)}
    k = len(main)
    lap = np.zeros((k, k))
    for u, v, w in edges:
        if u in remap and v in remap:
            i, j = remap[u], remap[v]
            c = 1.0 / max(w, 1e-6)  # проводимость ~ 1/длина
            lap[i, i] += c
            lap[j, j] += c
            lap[i, j] -= c
            lap[j, i] -= c
    eig = np.linalg.eigvalsh(lap)
    return float(eig[1]) if len(eig) > 1 else 0.0


def graph_metrics(n: int, edges: list[tuple[int, int, float]],
                  degrees: list[int]) -> dict[str, Any]:
    """Все метрики по графу: энтропия, кольца, Фидлер, тупики."""
    m = len(edges)
    comps = _components(n, edges)
    total_len = sum(w for _, _, w in edges)
    if m > 1 and total_len > 0:
        ent = -sum((w / total_len) * math.log2(w / total_len)
                   for _, _, w in edges)
        ent_norm = ent / math.log2(m)
    else:
        ent = ent_norm = 0.0
    return {
        "nodes": n,
        "edges": m,
        "components": comps,
        "total_length_m": round(total_len, 1),
        "entropy_bits": round(ent, 4),
        "entropy_norm": round(ent_norm, 4),
        "loops": m - n + comps,  # цикломатическое число
        "dead_ends": sum(1 for d in degrees if d == 1),
        "fiedler": round(_fiedler(n, edges), 6),
    }


def network_metrics(lines: list[list[list[float]]]) -> dict[str, Any]:
    """Метрики сети целиком: lines — полилинии теплосети."""
    nodes, edges = build_graph(lines)
    deg = [0] * len(nodes)
    for u, v, _ in edges:
        deg[u] += 1
        deg[v] += 1
    return graph_metrics(len(nodes), edges, deg)


def _with_branch(network_lines: list[list[list[float]]],
                 path: list[list[float]]):
    """Сеть + новая ветка: сегмент в точке врезки разбивается на два,
    сама ветка начинается строго из точки врезки."""
    attach = path[0]
    lines = [list(l) for l in network_lines]
    best = None  # (dist, li, si, px, py)
    for li, line in enumerate(lines):
        for si in range(len(line) - 1):
            (x1, y1), (x2, y2) = line[si], line[si + 1]
            dx, dy = x2 - x1, y2 - y1
            seg_len = math.hypot(dx, dy)
            if seg_len < 1e-6:
                continue
            t = max(0.0, min(1.0,
                ((attach[0] - x1) * dx + (attach[1] - y1) * dy) / (seg_len ** 2)))
            px, py = x1 + t * dx, y1 + t * dy
            d = math.hypot(px - attach[0], py - attach[1])
            if best is None or d < best[0]:
                best = (d, li, si, px, py)
    if best is not None and best[0] < 25.0:
        _, li, si, px, py = best
        line = lines[li]
        # не дублируем существующие вершины
        if math.hypot(px - line[si][0], py - line[si][1]) > 0.01 and \
           math.hypot(px - line[si + 1][0], py - line[si + 1][1]) > 0.01:
            lines[li] = line[:si + 1] + [[px, py]] + line[si + 1:]
        # саму ветку начинаем строго из точки врезки
        path = [[px, py]] + [list(p) for p in path[1:]]
    return lines + [path]


def impact(network_lines: list[list[list[float]]],
           path: list[list[float]]) -> dict[str, Any]:
    """Δ-импакт новой ветки: метрики сети до и после подключения."""
    before = network_metrics(network_lines)
    after = network_metrics(_with_branch(network_lines, path))
    delta = {}
    for k in ("entropy_norm", "fiedler", "loops", "dead_ends"):
        delta[k] = round(after[k] - before[k], 6)
    return {"before": before, "after": after, "delta": delta}


# ---------- отказоустойчивость: N-1 и Монте-Карло ----------

def _unserved_share(n: int, edges: list[tuple[int, int, float]],
                    skip: set[int]) -> float:
    """Доля длины сети, отрезанной от крупнейшей компоненты,
    если удалить рёбра с индексами из skip."""
    total = sum(w for _, _, w in edges)
    if total <= 0:
        return 0.0
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for ei, (u, v, _) in enumerate(edges):
        if ei not in skip:
            parent[find(u)] = find(v)
    comp_len: dict[int, float] = {}
    for ei, (u, v, w) in enumerate(edges):
        if ei not in skip:
            root = find(u)
            comp_len[root] = comp_len.get(root, 0.0) + w
    if not comp_len:
        return 0.0
    return 1.0 - max(comp_len.values()) / total


def reliability(network_lines: list[list[list[float]]],
                path: list[list[float]] | None = None,
                mc_trials: int = 300, fail_prob: float = 0.05) -> dict[str, Any]:
    """Отказоустойчивость сети (опционально — с новой веткой).

    N-1 (точный перебор): удаляем каждое ребро по очереди и смотрим,
    какая доля сети (по длине) остаётся отрезанной от крупнейшей
    компоненты — худший и средний случаи.

    Монте-Карло: каждое ребро отказывает независимо с вероятностью
    fail_prob (двойные-тройные отказы), ожидаемый недоотпуск —
    средняя доля отрезанной сети по серии испытаний.

    «Крупнейшая компонента» играет роль части сети, оставшейся
    под питанием от источника тепла.
    """
    lines = (network_lines if path is None
             else _with_branch(network_lines, path))
    _, edges = build_graph(lines)
    n = max((max(u, v) for u, v, _ in edges), default=-1) + 1
    m = len(edges)
    if m == 0:
        return {"n1_worst_pct": 0.0, "n1_mean_pct": 0.0,
                "mc_unserved_pct": 0.0, "mc_trials": 0}

    # N-1: точный перебор единичных отказов
    shares = [_unserved_share(n, edges, {i}) for i in range(m)]
    n1_worst = max(shares) * 100
    n1_mean = sum(shares) / m * 100

    # Монте-Карло множественных отказов (фиксированный seed —
    # результаты воспроизводимы между запросами)
    rng = np.random.default_rng(2027)
    mc = 0.0
    for _ in range(mc_trials):
        skip = {i for i in range(m) if rng.random() < fail_prob}
        if skip:
            mc += _unserved_share(n, edges, skip)
    mc_pct = mc / mc_trials * 100

    return {
        "n1_worst_pct": round(n1_worst, 2),
        "n1_mean_pct": round(n1_mean, 2),
        "mc_unserved_pct": round(mc_pct, 2),
        "mc_trials": mc_trials,
        "fail_prob": fail_prob,
    }
