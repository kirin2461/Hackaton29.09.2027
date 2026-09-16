"""Эндпоинты вычислительного движка (внутренние, снаружи недоступны).

Конвейер «файл вошёл — результат вышел» (pipeline.py) реализует правила
§2.3–2.6 ТЗ и техприложение. Входной файл, не соответствующий конкурсной
схеме или содержащий невалидную геометрию, отклоняется с диагностической
ошибкой 400 (протокол 16.09.2026, п.9) — без молчаливых заглушек.
"""

import json
from pathlib import Path

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


@router.post("/process", response_model=ProcessResponse)
def process(req: ProcessRequest):
    input_path = Path(req.input_path)
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"входной файл не найден: {input_path}")

    result_path = Path(req.result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        summary = run_pipeline(input_path, result_path)
    except PipelineInputError as exc:
        # Протокол п.9: диагностическая ошибка вместо заглушки
        raise HTTPException(status_code=400,
                            detail=f"невалидный входной набор: {exc}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"невалидный JSON: {exc}")

    return ProcessResponse(
        job_id=req.job_id,
        status="done" if not summary["unconnected_ids"] else "partial",
        result_path=str(result_path),
        features_in=summary["buildings_total"],
        engine="dit-sprint6",
        summary=summary,
    )
