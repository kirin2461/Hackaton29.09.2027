package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.Point;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Доменная модель конкурсного набора (официальная схема §2.1 техприложения).
 * Типы объектов входного GeoJSON (properties.object_type, таблица 2.1):
 * source, heat_network, heat_chamber, oks_future, oks_connection_point,
 * oks_existing, restriction.
 */
public final class Model {

    private Model() {
    }

    /** Источник теплоснабжения (корень цепочки upstream_object_id). */
    public static class Source {
        public final String objectId;
        public final Point geom;

        public Source(String objectId, Point geom) {
            this.objectId = objectId;
            this.geom = geom;
        }
    }

    /** Участок существующей тепловой сети. */
    public static class Segment {
        public final String objectId;
        public final LineString geom;
        public Double diameterMm;          // может отсутствовать во входе
        public double flowTph;
        public String nextObjectId;        // upstream_object_id — к источнику

        public Segment(String objectId, LineString geom, Double diameterMm,
                       double flowTph, String nextObjectId) {
            this.objectId = objectId;
            this.geom = geom;
            this.diameterMm = diameterMm;
            this.flowTph = flowTph;
            this.nextObjectId = nextObjectId;
        }

        public double diameterOrZero() {
            return diameterMm == null ? 0.0 : diameterMm;
        }
    }

    /**
     * Тепловая камера (существующая). diameterMm — входное значение:
     * максимальный условный диаметр существующих участков, уже примыкающих
     * к камере (§2.2).
     */
    public static class Chamber {
        public final String objectId;
        public final Point geom;
        public Double diameterMm;
        public int occupiedConnections;    // запасной ввод (не из официальной схемы)
        public String nextObjectId;        // upstream_object_id

        public Chamber(String objectId, Point geom, Double diameterMm,
                       int occupiedConnections, String nextObjectId) {
            this.objectId = objectId;
            this.geom = geom;
            this.diameterMm = diameterMm;
            this.occupiedConnections = occupiedConnections;
            this.nextObjectId = nextObjectId;
        }
    }

    /** Перспективный ОКС. */
    public static class Building {
        public final String objectId;
        public final Geometry geom;        // Polygon / MultiPolygon / Point
        public final double flowTph;
        public Point connectionPoint;      // заполняется при загрузке
        public String connectionPointId;   // id точки подключения (§2.2: oks_id)

        public Building(String objectId, Geometry geom, double flowTph) {
            this.objectId = objectId;
            this.geom = geom;
            this.flowTph = flowTph;
        }

        /** Точка привязки: точка подключения, иначе центроид. */
        public Point anchor() {
            if (connectionPoint != null) {
                return connectionPoint;
            }
            if (geom instanceof Point) {
                return (Point) geom;
            }
            return geom.getCentroid();
        }
    }

    /**
     * Пространственное ограничение (restriction, таблица 5.1).
     * kind: forbidden | special_passage — правило обработки;
     * restrictionType — исходный тип (road, oks_existing, ...).
     */
    public static class ConstraintZone {
        public final String objectId;
        public final Geometry geom;        // Polygon / MultiPolygon / LineString / Point
        public final String kind;
        public final Map<String, Object> params;
        public final String restrictionType;

        public ConstraintZone(String objectId, Geometry geom, String kind,
                              Map<String, Object> params, String restrictionType) {
            this.objectId = objectId;
            this.geom = geom;
            this.kind = kind;
            this.params = params;
            this.restrictionType = restrictionType;
        }
    }

    /** Разобранный конкурсный набор в метрической СК. */
    public static class ContestData {
        public Map<String, Segment> segments = new LinkedHashMap<>();
        public Map<String, Chamber> chambers = new LinkedHashMap<>();
        public Map<String, Building> buildings = new LinkedHashMap<>();
        public Map<String, Source> sources = new LinkedHashMap<>();
        public List<ConstraintZone> constraints = new ArrayList<>();
        public String crsFrom;             // исходная СК (EPSG:4326 по техприложению)
        public String crsWork;             // рабочая метрическая СК
        public double[] bounds;            // {minx, miny, maxx, maxy} в рабочей СК
        public List<String> warnings = new ArrayList<>();
    }
}
