"""Эндпоинты вычислительного движка (внутренние, снаружи недоступны).

Спринт 2: конвейер «файл вошёл — результат вышел» реализует
обязательные правила §2.3–2.6 ТЗ (см. pipeline.py). Если входной
файл не соответствует конкурсной схеме — возвращается заглушка
(совместимость со Спринтом 1 и демо-данными OSM).
"""

import json
import time
from pathlib import Path

import ijson
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .loader import PipelineInputError
from .pipeline import run_pipeline

router = APIRouter(prefix="/engine", tags=["engine"])


class ProcessRequest(BaseModel):
    job_id: str
    input_path: str
    result_path: str


class ProcessResponse(BaseModel):
    job_id: str
    status: str
    result_path: str
    features_in: int
    engine: str
    summary: dict | None = None


def _count_features(path: Path) -> int:
    """Потоковый подсчёт объектов во входном GeoJSON (без загрузки в память)."""
    count = 0
    with path.open("rb") as fh:
        for _ in ijson.items(fh, "features.item"):
            count += 1
    return count


@router.post("/process", response_model=ProcessResponse)
def process(req: ProcessRequest):
    input_path = Path(req.input_path)
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"входной файл не найден: {input_path}")

    result_path = Path(req.result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()

    try:
        summary = run_pipeline(input_path, result_path)
        return ProcessResponse(
            job_id=req.job_id,
            status="done" if not summary["unconnected_ids"] else "partial",
            result_path=str(result_path),
            features_in=summary["buildings_total"],
            engine="dit-sprint2",
            summary=summary,
        )
    except PipelineInputError:
        # Вход не по конкурсной схеме — заглушка Спринта 1
        pass
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"невалидный JSON: {exc}")

    try:
        features_in = _count_features(input_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"невалидный GeoJSON: {exc}")

    stub = {
        "type": "FeatureCollection",
        "metadata": {
            "job_id": req.job_id,
            "engine": "stub-sprint1",
            "features_in": features_in,
            "elapsed_ms": int((time.time() - started) * 1000),
        },
        "features": [],
    }
    with result_path.open("w", encoding="utf-8") as fh:
        json.dump(stub, fh, ensure_ascii=False)

    return ProcessResponse(
        job_id=req.job_id,
        status="done",
        result_path=str(result_path),
        features_in=features_in,
        engine="stub-sprint1",
    )
