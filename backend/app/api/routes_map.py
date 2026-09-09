"""Роуты картографических слоёв (День 2)."""

from fastapi import APIRouter, Depends

from ..deps import get_normalized_layers, get_parser
from ..gis.parser import LAYER_HEAT, GISParser
from ..routing.netstats import network_metrics

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/layers")
def get_layers(parser: GISParser = Depends(get_parser)):
    """Все слои карты одним запросом: здания, дороги, теплосети.

    Формат ответа:
      {
        "crs": "EPSG:32637",
        "bounds": [minx, miny, maxx, maxy],
        "layers": {
          "buildings":     [ {id, geometry_type, coordinates, properties}, ... ],
          "roads":         [ ... ],
          "heat_networks": [ ... ]
        }
      }
    """
    return parser.to_response()


@router.get("/network/stats")
def get_network_stats(layers: dict = Depends(get_normalized_layers)):
    """Метрики живучести существующей теплосети (без новых веток).

    Энтропия распределения длин сегментов, цикломатическое число
    (кольцевание), число Фидлера, доля тупиковых узлов — базовая
    линия, с которой сравнивается Δ-импакт нового подключения.
    """
    lines = [f["coordinates"] for f in layers.get(LAYER_HEAT, [])]
    return network_metrics(lines)
