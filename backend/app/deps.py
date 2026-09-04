"""Общие зависимости FastAPI (Dependency Injection).

Вынесены в отдельный модуль, чтобы роутерам не приходилось
импортировать main.py (иначе получился бы циклический импорт:
main подключает роутеры, роутеры импортируют main).
"""

from functools import lru_cache

from .config import DATA_DIR
from .gis.parser import GISParser


@lru_cache
def get_parser() -> GISParser:
    """Единый экземпляр ГИС-парсера на всё приложение.

    lru_cache гарантирует, что GeoJSON-файлы читаются с диска
    один раз за время жизни процесса, а не на каждый запрос.
    """
    return GISParser(DATA_DIR)
