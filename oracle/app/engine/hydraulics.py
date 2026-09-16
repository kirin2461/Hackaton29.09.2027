"""Гидравлика новой сети: расходы, диаметры, предельные длины (§3, §4).

  - расходы суммируются на общих участках (ствол несёт сумму ветвей);
  - диаметр — минимальный Ду по таблице 4.1 (пропускная способность);
  - предельная длина (таблица 4.1) — максимум НЕПРЕРЫВНОЙ части одного
    диаметра (раздел 3): камера/техузел отсчёт НЕ сбрасывают, сбрасывает
    только смена диаметра; при превышении непрерывная цепочка одного Ду
    ПОВЫШАЕТСЯ на следующий диаметр (enforce_max_length_chains).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point

from .refdata import RefData


@dataclass
class NewSegment:
    """Новый участок сети (ствол, ветвь, спецпроходный кусок)."""

    object_id: str
    coords: list[tuple[float, float]]
    flow_tph: float
    role: str = "branch"          # trunk | branch
    method: str = "base"          # base | special (§10.1 laying_method)
    k_special: float | None = None  # Kспец зоны спецпрохода
    bend_factor: float = 1.0        # ×1,5 при нештатном угле отвода (протокол п.9)
    diameter_mm: float = 0.0
    length_m: float = 0.0
    cost_rub: float = 0.0
    warnings: list = field(default_factory=list)
    start_node_id: str | None = None   # §10.1
    end_node_id: str | None = None     # §10.1
    depth_start: float | None = None   # §10.1 (null в 2D-задаче, §8.1)
    depth_end: float | None = None
    coords3d: list | None = None       # координаты с Z (режим глубины)
    _tariff_rub_m: float = 0.0         # ставка ₽/м на момент расчёта

    def __post_init__(self):
        self.length_m = _path_length(self.coords)


@dataclass
class TechnicalNode:
    """Технический узел (граница спецучастка / пересечение отметки 3,0 м)."""

    object_id: str
    point: Point
    reason: str


def _path_length(coords) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(coords, coords[1:]))


def subline(line: LineString, start_m: float, end_m: float) -> LineString:
    """Кусок полилинии между двумя отметками длины."""
    n = 32
    pts = [line.interpolate(start_m + (end_m - start_m) * k / n) for k in range(n + 1)]
    return LineString([(p.x, p.y) for p in pts])


def nonstandard_bend(coords, standard_deg=(45.0, 90.0), tol_deg: float = 5.0) -> bool:
    """Протокол 16.09.2026 п.9: есть ли на полилинии отвод с нештатным углом.

    Штатные углы отвода — 45° и 90° (±tol_deg); отклонение ≤ tol_deg
    считается прямолинейным продолжением. Любой другой угол в вершине —
    нештатный отвод (×1,5 к стоимости участка).
    """
    pts = [(float(c[0]), float(c[1])) for c in coords]
    for i in range(1, len(pts) - 1):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[i + 1]
        v1 = (bx - ax, by - ay)
        v2 = (cx - bx, cy - by)
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        cos_a = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        dev = math.degrees(math.acos(cos_a))
        if dev <= tol_deg:
            continue  # прямолинейно
        if any(abs(dev - std) <= tol_deg for std in standard_deg):
            continue  # штатный отвод 45°/90°
        return True
    return False


def reprice(seg: NewSegment, refdata: RefData) -> None:
    """Пересчитать ставку и стоимость участка (после смены Ду/коэффициентов)."""
    tariff = refdata.lay_tariff(seg.diameter_mm)
    if seg.method == "special":
        tariff *= seg.k_special or 1.5
    tariff *= seg.bend_factor
    seg._tariff_rub_m = tariff
    seg.cost_rub = seg.length_m * tariff


def size_segment(seg: NewSegment, refdata: RefData) -> None:
    """Подобрать диаметр (расход + предельная длина) и стоимость участка.

    Если длина участка превышает предельную для подобранного Ду — диаметр
    повышается на ОДИН номенклатурный шаг (раздел 3 + протокол п.7);
    если длина всё ещё не вписывается — предупреждение.
    """
    d = refdata.diameter_for_flow(seg.flow_tph)
    if d["max_flow_tph"] < seg.flow_tph:
        seg.warnings.append(
            f"расход {seg.flow_tph} т/ч превышает справочный максимум {d['max_flow_tph']} т/ч"
        )
    dn = d["dn_mm"]
    # Протокол 16.09.2026 п.7: повышение Ду по предельной длине — не более
    # ОДНОГО номенклатурного шага (большее в датасете не встречается)
    if seg.length_m > refdata.max_len_for(dn) and dn < refdata.diameters[-1]["dn_mm"]:
        dn = refdata.next_diameter(dn)["dn_mm"]
    if seg.length_m > refdata.max_len_for(dn):
        seg.warnings.append(
            f"длина {seg.length_m:.0f} м превышает предельную "
            f"{refdata.max_len_for(dn):.0f} м для Ду{int(dn)} — допускается "
            "один шаг повышения (протокол п.7)"
        )
    seg.diameter_mm = dn
    reprice(seg, refdata)


def enforce_max_length_chains(segments: list[NewSegment], refdata: RefData,
                              warnings: list[str]) -> None:
    """Раздел 3: предельная длина НЕПРЕРЫВНОЙ цепочки одного диаметра.

    Участки одного Ду, стыкующиеся в общих узлах (камера/техузел отсчёт
    НЕ сбрасывают), объединяются в цепочки через узлы степени 2. Если
    суммарная длина цепочки превышает предельную для её Ду — вся цепочка
    повышается на следующий диаметр, не более одного шага (протокол п.7);
    стоимость пересчитывается по ставке нового Ду (Kспец и коэффициент
    отвода участка сохраняются).
    """
    for _pass in range(1):  # протокол п.7: не более одного шага повышения Ду
        # узлы -> инцидентные участки (по id концов)
        incidence: dict[str, list[int]] = {}
        for i, s in enumerate(segments):
            for nid in (s.start_node_id, s.end_node_id):
                if nid:
                    incidence.setdefault(nid, []).append(i)

        # union-find по участкам: стык «тот же Ду + узел степени 2»
        parent = list(range(len(segments)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for nid, idxs in incidence.items():
            if len(idxs) != 2:
                continue  # ветвление/конец — цепочка прерывается
            a, b = idxs
            if segments[a].diameter_mm == segments[b].diameter_mm:
                union(a, b)

        chains: dict[int, list[int]] = {}
        for i in range(len(segments)):
            chains.setdefault(find(i), []).append(i)

        bumped = False
        for idxs in chains.values():
            dn = segments[idxs[0]].diameter_mm
            total = sum(segments[i].length_m for i in idxs)
            max_len = refdata.max_len_for(dn)
            if total > max_len + 1e-6 and dn < refdata.diameters[-1]["dn_mm"]:
                new_dn = refdata.next_diameter(dn)["dn_mm"]
                warnings.append(
                    f"цепочка из {len(idxs)} уч. Ду{int(dn)} длиной {total:.0f} м "
                    f"> предельной {int(max_len)} м — повышение до Ду{int(new_dn)} (раздел 3)")
                for i in idxs:
                    s = segments[i]
                    s.diameter_mm = new_dn
                    reprice(s, refdata)
                if total > refdata.max_len_for(new_dn) + 1e-6:
                    warnings.append(
                        f"цепочка Ду{int(new_dn)} длиной {total:.0f} м всё ещё "
                        f"> предельной {int(refdata.max_len_for(new_dn))} м — "
                        "допускается один шаг повышения (протокол п.7)")
                bumped = True
        if not bumped:
            return
