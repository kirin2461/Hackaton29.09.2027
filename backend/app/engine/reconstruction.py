"""Реконструкция существующей сети (§2.5 ТЗ, Спринт 2).

Дополнительный расход от каждой точки врезки поднимается по цепочке
«ID следующего объекта» до источника и суммируется. Для каждого участка
сравнивается требуемый диаметр (существующий расход + добавка) с
существующим — при нехватке участок идёт в реконструкцию со стоимостью.
Камера, примыкания которой исчерпали лимит 4, тоже реконструируется.
"""

from __future__ import annotations

from dataclasses import dataclass

from .network import ExistingNetwork
from .refdata import RefData
from .tapping import Tap


@dataclass
class ReconSegment:
    object_id: str
    existing_dn: float
    required_dn: float
    existing_flow_tph: float
    added_flow_tph: float
    length_m: float
    cost_rub: float


@dataclass
class ReconChamber:
    object_id: str
    reason: str
    cost_rub: float


@dataclass
class Reconstruction:
    added_flows: dict            # segment_id -> добавленный расход
    segments: list               # list[ReconSegment]
    chambers: list               # list[ReconChamber]

    @property
    def total_cost_rub(self) -> float:
        return sum(s.cost_rub for s in self.segments) + sum(c.cost_rub for c in self.chambers)


def compute_reconstruction(net: ExistingNetwork, taps: list[Tap],
                           refdata: RefData, chamber_load: dict[str, int]) -> Reconstruction:
    """Полный расчёт реконструкции по всем точкам врезки."""
    added: dict[str, float] = {}
    for tap in taps:
        if not tap.chain_start_id:
            continue
        for oid in net.chain_to_source(tap.chain_start_id):
            if oid in net.segments:
                added[oid] = added.get(oid, 0.0) + tap.flow_tph

    recon_segments: list[ReconSegment] = []
    for sid, add in added.items():
        seg = net.segments[sid]
        existing_dn = seg.diameter_mm or 0.0
        required = refdata.diameter_for_flow(seg.flow_tph + add)
        if required["dn_mm"] > existing_dn:
            length = seg.geom.length
            cost = length * refdata.lay_tariff(required["dn_mm"]) \
                * refdata.tariffs["reconstruction_per_m_multiplier"]
            recon_segments.append(ReconSegment(
                object_id=sid,
                existing_dn=existing_dn,
                required_dn=required["dn_mm"],
                existing_flow_tph=seg.flow_tph,
                added_flow_tph=add,
                length_m=round(length, 1),
                cost_rub=round(cost, 2),
            ))

    recon_chambers: list[ReconChamber] = []
    max_conn = int(refdata.rule("max_chamber_connections"))
    for tap in taps:
        if tap.kind != "existing_chamber" or not tap.chamber_id:
            continue
        ch = net.chambers[tap.chamber_id]
        total = ch.occupied_connections + chamber_load.get(tap.chamber_id, 0)
        if total > max_conn:
            cid = tap.chamber_id
            if any(c.object_id == cid for c in recon_chambers):
                continue
            recon_chambers.append(ReconChamber(
                object_id=cid,
                reason=f"примыканий {total} > лимита {max_conn}",
                cost_rub=refdata.tariff("chamber_reconstruction"),
            ))

    return Reconstruction(added_flows=added, segments=recon_segments, chambers=recon_chambers)
