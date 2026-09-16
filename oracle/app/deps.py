"""Общие зависимости FastAPI (Dependency Injection).

Вынесены в отдельный модуль, чтобы роутерам не приходилось
импортировать main.py (иначе получился бы циклический импорт:
main подключает роутеры, роутеры импортируют main).
"""

from functools import lru_cache

from .config import DATA_DIR
from .gis.parser import GISParser
from .routing.planner import RoutePlanner


@lru_cache
def get_parser() -> GISParser:
    """Единый экземпляр ГИС-парсера на всё приложение.

    lru_cache гарантирует, что GeoJSON-файлы читаются с диска
    один раз за время жизни процесса, а не на каждый запрос.
    """
    return GISParser(DATA_DIR)


@lru_cache
def get_planner() -> RoutePlanner:
    """Единый весовой граф карты (День 6) на всё приложение.

    Строится из нормализованных слоёв парсера (те же координаты,
    что уходит на фронтенд в /api/map/layers). Растеризация слоёв
    в сетку делается один раз, дальше каждый запрос — только A*.
    """
    parser = get_parser()
    response = parser.to_response()
    bounds = response["bounds"] or [0.0, 0.0, 1000.0, 1000.0]
    return RoutePlanner(response["layers"], bounds)


@lru_cache
def get_normalized_layers() -> dict:
    """Слои карты в нормализованных координатах (как у фронтенда).

    Нужны валидатору трассы (Дни 12–14): коллизии и переходы
    считаются в той же системе координат, в которой фронтенд
    показывает сцену.
    """
    return get_parser().to_response()["layers"]
