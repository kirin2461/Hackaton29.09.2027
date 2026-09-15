"""Эндпоинты вычислительного движка (внутренние, снаружи недоступны).

Спринт 1 — заглушка конвейера «файл вошёл — результат вышел»:
входной GeoJSON читается ПОТОКОВО (ijson), чтобы файлы до 3 ГБ
не поднимались в память; результат — валидный FeatureCollection.
Полноценное ядро трассировки (§2.3–2.6 ТЗ) подключается в Спринте 2.
"""

import json
import time
from pathlib import Path

import ijson
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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

    started = time.time()
    try:
        features_in = _count_features(input_path)
    except Exception as exc:  # ijson.JSONError и прочие ошибки парсинга
        raise HTTPException(status_code=400, detail=f"невалидный GeoJSON: {exc}")

    result = {
        "type": "FeatureCollection",
        "metadata": {
            "job_id": req.job_id,
            "engine": "stub-sprint1",
            "features_in": features_in,
            "elapsed_ms": int((time.time() - started) * 1000),
        },
        "features": [],
    }

    result_path = Path(req.result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)

    return ProcessResponse(
        job_id=req.job_id,
        status="done",
        result_path=str(result_path),
        features_in=features_in,
    )
