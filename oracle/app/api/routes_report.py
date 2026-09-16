"""Роут PDF-отчёта по техприсоединению."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from shapely.geometry import Polygon

from ..deps import get_normalized_layers
from ..gis.parser import LAYER_HEAT
from ..report.report_pdf import build_report
from ..routing.estimate import validate_path
from ..routing.netstats import impact as network_impact
from ..routing.netstats import reliability as network_reliability

router = APIRouter(prefix="/api/report", tags=["report"])

VARIANT_NAMES = {
    "shortest": "Кратчайший",
    "balanced": "Экономичный",
    "no_roads": "В обход дорог",
    "custom": "Ручная правка (gizmo)",
}


class ReportBuilding(BaseModel):
    polygon: list[list[float]] = Field(..., min_length=3)
    floors: int = Field(5, ge=1, le=100)
    name: str = "Новое здание"


class ReportRequest(BaseModel):
    """Тело POST /api/report/pdf — то же, что у сохранения проекта."""

    building: ReportBuilding
    network_id: str
    path: list[list[float]] = Field(..., min_length=2)
    variant: str = "custom"


@router.post("/pdf")
def report_pdf(req: ReportRequest,
               layers: dict = Depends(get_normalized_layers)):
    """Собирает PDF-отчёт: смета, живучесть сети до/после, карта."""
    heat_feats = layers.get(LAYER_HEAT, [])
    if not any(f["id"] == req.network_id for f in heat_feats):
        raise HTTPException(404, f"Теплосеть '{req.network_id}' не найдена")

    poly = Polygon(req.building.polygon)
    area = float(poly.area)
    building = {
        "polygon": req.building.polygon,
        "floors": req.building.floors,
        "area_m2": round(area, 1),
        "heat_load_kw": round(area * req.building.floors * 0.06, 1),
    }
    try:
        estimate = validate_path(req.path, layers)
    except ValueError as e:
        raise HTTPException(422, str(e))

    heat_lines = [f["coordinates"] for f in heat_feats]
    impact = network_impact(heat_lines, req.path)
    reliability = {
        "before": network_reliability(heat_lines),
        "after": network_reliability(heat_lines, req.path),
    }

    pdf_bytes = build_report(
        building, req.network_id, req.path,
        VARIANT_NAMES.get(req.variant, req.variant),
        estimate, impact, reliability, layers)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 "attachment; filename=heat_connection_report.pdf"},
    )
