"""Роуты картографических слоёв (День 2)."""

from fastapi import APIRouter, Depends

from ..deps import get_parser
from ..gis.parser import GISParser

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
