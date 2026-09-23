package ru.heatnet.dit.engine.core;

import com.fasterxml.jackson.databind.JsonNode;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.Point;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Доменная модель конкурсного набора (официальная схема §1 техприложения,
 * актуальная редакция). Типы объектов входного GeoJSON
 * (properties.object_type, таблица §1.1):
 * source, heat_network, heat_chamber, oks_connection_point, restriction.
 * Полигоны ОКС передаются как restriction с restriction_type = oks (§1.2).
 */
public final class Model {

    private Model() {
    }

    /** Источник теплоснабжения. */
    public static class Source {
        public final String objectId;
        public final Point geom;

        public Source(String objectId, Point geom) {
            this.objectId = objectId;
            this.geom = geom;
        }
    }

    /** Участок существующей тепловой сети (обязательные атрибуты: id, diameter). */
    public static class Segment {
        public final String objectId;
        public final LineString geom;
        public Double diameterMm;          // может отсутствовать во входе
        public double flowTph;             // необязательный атрибут (расширение)
        public String nextObjectId;        // необязательный upstream (ранние наборы)

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

    /** Существующая тепловая камера (обязательные атрибуты: id). */
    public static class Chamber {
        public final String objectId;
        public final JsonNode idRaw;       // исходный id (для ссылок в выгрузке)
        public final Point geom;
        public Double diameterMm;          // необязательный атрибут
        public int occupiedConnections;    // запасной ввод (не из официальной схемы)
        public String nextObjectId;        // необязательный upstream (ранние наборы)

        public Chamber(String objectId, JsonNode idRaw, Point geom, Double diameterMm,
                       int occupiedConnections, String nextObjectId) {
            this.objectId = objectId;
            this.idRaw = idRaw;
            this.geom = geom;
            this.diameterMm = diameterMm;
            this.occupiedConnections = occupiedConnections;
            this.nextObjectId = nextObjectId;
        }
    }

    /**
     * Точка подключения ОКС (oks_connection_point) — самостоятельная цель
     * подключения (§1.1, разъяснение №4). Расход flow_tph задан на самой
     * точке. Связь с полигоном ОКС идентификатором не задаётся — полигон
     * находится пространственно (restriction_type = oks, §2.2).
     */
    public static class ConnectionTarget {
        public final String objectId;
        public final JsonNode idRaw;       // исходный id (тип сохраняется, §7.2)
        public final Point point;
        public double flowTph;
        public String oksZoneId;           // id содержащего полигона ОКС (или null)

        public ConnectionTarget(String objectId, JsonNode idRaw, Point point, double flowTph) {
            this.objectId = objectId;
            this.idRaw = idRaw;
            this.point = point;
            this.flowTph = flowTph;
        }

        /** Точка привязки — сама точка подключения. */
        public Point anchor() {
            return point;
        }
    }

    /**
     * Пространственное ограничение (restriction, таблица 2).
     * kind: forbidden | special_passage — правило обработки;
     * restrictionType — канонический тип (road, oks, railway, ...).
     */
    public static class ConstraintZone {
        public final String objectId;
        public final Geometry geom;        // Polygon / MultiPolygon / LineString / MultiLineString
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

    /** Разобранный конкурсный набор в метрической СК (EPSG:32637). */
    public static class ContestData {
        public Map<String, Segment> segments = new LinkedHashMap<>();
        public Map<String, Chamber> chambers = new LinkedHashMap<>();
        public Map<String, ConnectionTarget> targets = new LinkedHashMap<>();
        public Map<String, Source> sources = new LinkedHashMap<>();
        public List<ConstraintZone> constraints = new ArrayList<>();
        public String crsFrom;             // исходная СК (EPSG:4326 по техприложению)
        public String crsWork;             // рабочая метрическая СК
        public double[] bounds;            // {minx, miny, maxx, maxy} в рабочей СК
        public List<String> warnings = new ArrayList<>();
    }
}
