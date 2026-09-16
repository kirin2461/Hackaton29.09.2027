"""Реконструкция существующей сети (раздел 7) и камер (§8.2).

Раздел 7:
  - дополнительный расход от каждой точки врезки поднимается по цепочке
    upstream_object_id до источника и СУММИРУЕТСЯ на общих частях;
  - врезка в середину участка → реконструируется только ЧАСТЬ участка
    от точки врезки по направлению к источнику (partial geometry);
  - несколько врезок на одном участке → участок режется на интервалы,
    на каждом свой суммарный добавленный расход;
  - требуемый диаметр — минимальный подходящий под (существующий +
    добавленный) расход по таблице 4.1;
  - стоимость = длина части × ставка РЕКОНСТРУКЦИИ требуемого Ду
    (таблица 4.1); Kспец и Kгл НЕ применяются;
  - каждая реконструируемая часть — отдельный объект со своей геометрией.

Раздел 8.2 (камеры) с уточнением протокола 16.09.2026 (п.8):
  - реконструкция тарифицируется ТОЛЬКО для камер-точек врезки: камера
    реконструируется, если требуемый Ду (максимум по врезке в неё и по
    примыкающим участкам ПОСЛЕ реконструкции) больше входного диаметра;
    стоимость — по шкале §8.2, один раз на камеру;
  - транзитные камеры (через которые лишь вырос расход upstream)
    НЕ реконструируются и в стоимость не входят.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString

from .hydraulics import subline
from .network import ExistingNetwork
from .refdata import RefData
from .tapping import Tap


@dataclass
class ReconSegment:
    object_id: str            # recon-N (новый id объекта реконструкции)
    existing_object_id: str   # id исходного участка (§10.3)
    existing_dn: float
    required_dn: float
    existing_flow: float
    added_flow: float
    calculated_flow: float
    length_m: float
    cost_rub: float
    geom: LineString          # реконструируемая ЧАСТЬ участка


@dataclass
class ReconChamber:
    object_id: str            # recon-ch-N
    existing_object_id: str   # id исходной камеры
    existing_dn: float
    required_dn: float
    cost_rub: float


@dataclass
class Reconstruction:
    segments: list            # list[ReconSegment]
    chambers: list            # list[ReconChamber]

    @property
    def segments_cost_rub(self) -> float:
        return sum(s.cost_rub for s in self.segments)

    @property
    def chambers_cost_rub(self) -> float:
        return sum(c.cost_rub for c in self.chambers)

    @property
    def total_cost_rub(self) -> float:
        return self.segments_cost_rub + self.chambers_cost_rub


def _source_end_pos(net: ExistingNetwork, seg) -> float:
    """Отметка (0 или L) конца участка, БЛИЖАЙШЕГО к следующему объекту цепочки."""
    nxt = net.get(seg.next_object_id) if seg.next_object_id else None
    L = seg.geom.length
    if nxt is None:
        return L  # обрыв цепочки = источник за дальним концом
    g = getattr(nxt, "geom", None)
    if g is None:
        return L
    p0 = seg.geom.interpolate(0.0)
    p1 = seg.geom.interpolate(L)
    return 0.0 if g.distance(p0) <= g.distance(p1) else L


def compute_reconstruction(net: ExistingNetwork, taps: list[Tap],
                           refdata: RefData, warnings: list[str] | None = None) -> Reconstruction:
    """Полный расчёт реконструкции по всем точкам врезки."""
    warnings = warnings if warnings is not None else []

    # --- накопление интервалов добавленного расхода по участкам ---
    # segment_id -> [(start_m, end_m, flow)]
    intervals: dict[str, list[tuple[float, float, float]]] = {}

    def _add(sid: str, a: float, b: float, flow: float) -> None:
        lo, hi = min(a, b), max(a, b)
        if hi - lo > 0.01:
            intervals.setdefault(sid, []).append((lo, hi, flow))

    for tap in taps:
        if not tap.chain_start_id:
            continue
        flow = tap.flow_tph
        if tap.kind == "new_chamber_on_segment" and tap.segment_id:
            # врезка в середину участка: часть от врезки к источнику
            seg = net.segments[tap.segment_id]
            L = seg.geom.length
            src_pos = _source_end_pos(net, seg)
            _add(tap.segment_id, tap.along_m, src_pos, flow)
            start_from = seg.next_object_id
        else:
            # врезка в камеру: цепочка начинается со следующего объекта
            ch = net.chambers.get(tap.chain_start_id)
            start_from = ch.next_object_id if ch else None
        for oid in net.chain_to_source(start_from) if start_from else []:
            if oid in net.segments:
                seg = net.segments[oid]
                _add(oid, 0.0, seg.geom.length, flow)

    # --- режем участки на элементарные части, считаем требуемый Ду ---
    recon_segments: list[ReconSegment] = []
    seq = 0
    for sid, ivs in sorted(intervals.items()):
        seg = net.segments[sid]
        L = seg.geom.length
        existing_dn = seg.diameter_mm or 0.0
        cuts = sorted({0.0, L} | {x for a, b, _ in ivs for x in (a, b)})
        for a, b in zip(cuts, cuts[1:]):
            if b - a < 0.01:
                continue
            mid = (a + b) / 2.0
            added = sum(f for ia, ib, f in ivs if ia <= mid <= ib)
            if added <= 0:
                continue
            calculated = seg.flow_tph + added
            required = refdata.diameter_for_flow(calculated)
            if required["dn_mm"] <= existing_dn:
                continue  # пропускной способности хватает
            if required["max_flow_tph"] < calculated:
                warnings.append(
                    f"{sid}: расход {calculated:.1f} т/ч превышает максимум "
                    f"справочника {required['max_flow_tph']} т/ч")
            piece = subline(seg.geom, a, b)
            seq += 1
            length_m = round(piece.length, 1)
            recon_segments.append(ReconSegment(
                object_id=f"recon-{seq}",
                existing_object_id=sid,
                existing_dn=existing_dn,
                required_dn=required["dn_mm"],
                existing_flow=round(seg.flow_tph, 3),
                added_flow=round(added, 3),
                calculated_flow=round(calculated, 3),
                length_m=length_m,
                cost_rub=round(length_m * refdata.recon_tariff(required["dn_mm"]), 2),
                geom=piece,
            ))

    # --- реконструкция камер (§8.2): требуемый Ду > входного диаметра ---
    # требуемый Ду примыкающих участков после реконструкции
    seg_required: dict[str, float] = {}
    for rs in recon_segments:
        seg_required[rs.existing_object_id] = max(
            seg_required.get(rs.existing_object_id, 0.0), rs.required_dn)
    # врезки по камерам
    tap_required: dict[str, float] = {}
    for tap in taps:
        if tap.kind == "existing_chamber" and tap.chamber_id:
            tap_required[tap.chamber_id] = max(
                tap_required.get(tap.chamber_id, 0.0), tap.required_dn)

    recon_chambers: list[ReconChamber] = []
    cseq = 0
    # Протокол 16.09.2026 п.8: реконструируются ТОЛЬКО камеры-точки врезки;
    # транзитные камеры в стоимость не входят.
    for cid in sorted(tap_required):
        ch = net.chambers.get(cid)
        if ch is None:
            continue
        adj_ids = net.chamber_adjacent_segment_ids(cid)
        required = 0.0
        for sid in adj_ids:
            s = net.segments[sid]
            required = max(required, seg_required.get(sid, s.diameter_mm or 0.0))
        required = max(required, tap_required.get(cid, 0.0))
        existing = ch.diameter_mm
        if not existing and adj_ids:
            existing = max((net.segments[s].diameter_mm or 0.0) for s in adj_ids)
        existing = existing or 0.0
        if required > (existing or 0.0):
            cseq += 1
            recon_chambers.append(ReconChamber(
                object_id=f"recon-ch-{cseq}",
                existing_object_id=cid,
                existing_dn=existing or 0.0,
                required_dn=required,
                cost_rub=refdata.chamber_cost(required),
            ))

    return Reconstruction(segments=recon_segments, chambers=recon_chambers)
