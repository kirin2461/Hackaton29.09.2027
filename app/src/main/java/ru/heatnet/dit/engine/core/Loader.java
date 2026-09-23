package ru.heatnet.dit.engine.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.LinearRing;
import org.locationtech.jts.geom.MultiPolygon;
import org.locationtech.jts.geom.Point;
import org.locationtech.jts.geom.Polygon;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Потоковый загрузчик конкурсного GeoJSON (официальная схема §1,
 * актуальная редакция техприложения).
 *
 * Файл до 3 ГБ читается стримингом Jackson — объекты разбираются по одному,
 * в память не поднимаются целиком. СК формализованы техприложением:
 * вход — EPSG:4326 (валидируется, иное отклоняется), все расчёты —
 * в EPSG:32637 (переопределяется ENGINE_SOURCE_CRS / ENGINE_WORK_CRS).
 *
 * Цели подключения — точки oks_connection_point с собственным flow_tph;
 * полигоны ОКС приходят как restriction с restriction_type = oks (§1.2).
 * Невалидная геометрия — диагностическая ошибка.
 */
public final class Loader {

    private Loader() {
    }

    /** Типы объектов: официальные (таблица 2.1) + синонимы ранних наборов. */
    private static final Map<String, String> OBJECT_TYPE_ALIASES = new HashMap<>();

    static {
        OBJECT_TYPE_ALIASES.put("source", "source");
        OBJECT_TYPE_ALIASES.put("heat_source", "source");
        OBJECT_TYPE_ALIASES.put("heat_network", "existing_segment");
        OBJECT_TYPE_ALIASES.put("existing_segment", "existing_segment");
        OBJECT_TYPE_ALIASES.put("network_segment", "existing_segment");
        OBJECT_TYPE_ALIASES.put("existing_network", "existing_segment");
        OBJECT_TYPE_ALIASES.put("existing_network_segment", "existing_segment");
        OBJECT_TYPE_ALIASES.put("heat_chamber", "chamber");
        OBJECT_TYPE_ALIASES.put("chamber", "chamber");
        OBJECT_TYPE_ALIASES.put("thermal_chamber", "chamber");
        OBJECT_TYPE_ALIASES.put("oks_future", "legacy_building");
        OBJECT_TYPE_ALIASES.put("prospective_building", "legacy_building");
        OBJECT_TYPE_ALIASES.put("building", "legacy_building");
        OBJECT_TYPE_ALIASES.put("oks_connection_point", "connection_point");
        OBJECT_TYPE_ALIASES.put("connection_point", "connection_point");
        OBJECT_TYPE_ALIASES.put("oks_existing", "oks_existing");
        OBJECT_TYPE_ALIASES.put("existing_building", "oks_existing");
        OBJECT_TYPE_ALIASES.put("restriction", "constraint");
        OBJECT_TYPE_ALIASES.put("constraint", "constraint");
        OBJECT_TYPE_ALIASES.put("spatial_constraint", "constraint");
    }

    /** Синонимы типов ограничений → канонические restriction_type (таблица 5.1). */
    private static final Map<String, String> RESTRICTION_TYPE_ALIASES = new HashMap<>();

    static {
        RESTRICTION_TYPE_ALIASES.put("road", "road");
        RESTRICTION_TYPE_ALIASES.put("tram_tracks", "tram_tracks");
        RESTRICTION_TYPE_ALIASES.put("tram", "tram_tracks");
        RESTRICTION_TYPE_ALIASES.put("gas_pipeline", "gas_pipeline");
        RESTRICTION_TYPE_ALIASES.put("gas", "gas_pipeline");
        RESTRICTION_TYPE_ALIASES.put("power_cable", "power_cable");
        RESTRICTION_TYPE_ALIASES.put("cable", "power_cable");
        RESTRICTION_TYPE_ALIASES.put("heat_network", "heat_network");
        RESTRICTION_TYPE_ALIASES.put("park", "park");
        RESTRICTION_TYPE_ALIASES.put("social_area", "social_area");
        RESTRICTION_TYPE_ALIASES.put("prohibited_site", "prohibited_site");
        RESTRICTION_TYPE_ALIASES.put("water", "water");
        RESTRICTION_TYPE_ALIASES.put("railway", "railway");
        RESTRICTION_TYPE_ALIASES.put("rail", "railway");
        RESTRICTION_TYPE_ALIASES.put("oks", "oks");
        RESTRICTION_TYPE_ALIASES.put("oks_existing", "oks_existing");
        RESTRICTION_TYPE_ALIASES.put("forbidden", "prohibited_site");
        RESTRICTION_TYPE_ALIASES.put("no_build", "prohibited_site");
        RESTRICTION_TYPE_ALIASES.put("ban", "prohibited_site");
        RESTRICTION_TYPE_ALIASES.put("special_passage", "road");
        RESTRICTION_TYPE_ALIASES.put("special", "road");
        RESTRICTION_TYPE_ALIASES.put("min_distance", "oks_existing");
    }

    private static final Pattern EPSG_RE = Pattern.compile("EPSG[^0-9]{0,4}(\\d{4,5})", Pattern.CASE_INSENSITIVE);

    private static final GeometryFactory GF = new GeometryFactory();

    /** Разобрать конкурсный GeoJSON в доменную модель (метрическая СК). */
    public static Model.ContestData loadContestGeojson(Path path, RefData refdata) {
        String crsFrom = System.getenv().getOrDefault("ENGINE_SOURCE_CRS", "EPSG:4326");
        String declared = declaredCrs(path);
        if (declared != null) {
            Integer want = epsgCode(crsFrom);
            Integer got = epsgCode(declared);
            if (want == null || !want.equals(got)) {
                throw new PipelineInputException(
                        "входной файл в CRS '" + declared + "', ожидается " + crsFrom
                                + " (техприложение: вход строго в EPSG:4326)");
            }
        }
        String crsWork = System.getenv().getOrDefault("ENGINE_WORK_CRS", "EPSG:32637");
        Function<double[], double[]> project = projector(crsFrom, crsWork);

        Model.ContestData data = new Model.ContestData();
        data.crsFrom = crsFrom;
        data.crsWork = crsWork;

        Map<String, String> legacyOwner = new LinkedHashMap<>();   // точка -> oks_id (ранние наборы)
        Map<String, Double> legacyFlow = new LinkedHashMap<>();    // oks_id -> flow_tph (ранние наборы)
        List<Model.ConstraintZone> oksPolygons = new ArrayList<>(); // полигоны ОКС (oks/oks_existing)
        List<String> invalidGeom = new ArrayList<>();
        double[] bounds = {Double.POSITIVE_INFINITY, Double.POSITIVE_INFINITY,
                Double.NEGATIVE_INFINITY, Double.NEGATIVE_INFINITY};

        ObjectMapper mapper = new ObjectMapper();
        JsonFactory factory = new JsonFactory();
        try (JsonParser p = factory.createParser(Files.newInputStream(path))) {
            // доходим до массива features
            while (p.nextToken() != null) {
                if (p.currentToken() == JsonToken.FIELD_NAME && "features".equals(p.currentName())) {
                    p.nextToken(); // START_ARRAY
                    break;
                }
            }
            while (p.nextToken() == JsonToken.START_OBJECT) {
                JsonNode feat = mapper.readTree(p);
                JsonNode propsNode = feat.get("properties");
                Map<String, JsonNode> props = new LinkedHashMap<>();
                if (propsNode != null && propsNode.isObject()) {
                    propsNode.fields().forEachRemaining(e -> props.put(e.getKey(), e.getValue()));
                }
                String rawType = textOf(pick(props, "object_type", "type", "layer"));
                String kind = rawType == null ? null : OBJECT_TYPE_ALIASES.get(rawType.trim());
                if (kind == null) {
                    continue; // неизвестный тип объекта — пропуск без диагностики
                }
                JsonNode oidNode = pick(props, "object_id", "id", "uid");
                String oid = textOf(oidNode);
                if (oid == null) {
                    oid = kind + ":" + (data.segments.size() + data.chambers.size() + data.targets.size());
                }
                Geometry geom = project(buildGeom(feat.get("geometry")), project);
                String bad = geometryProblem(geom);
                if (bad != null) {
                    invalidGeom.add(oid + ": " + bad);
                    continue;
                }
                extendBounds(bounds, geom);

                switch (kind) {
                    case "source":
                        data.sources.put(oid, new Model.Source(oid,
                                geom instanceof Point ? (Point) geom : geom.getCentroid()));
                        break;
                    case "existing_segment":
                        if (!(geom instanceof LineString)) {
                            data.warnings.add(oid + ": сегмент сети не LineString — пропущен");
                            break;
                        }
                        data.segments.put(oid, new Model.Segment(
                                oid,
                                (LineString) geom,
                                asFloatObj(pick(props, "diameter", "diameter_mm", "dn_mm", "dn")),
                                orZero(asFloatObj(pick(props, "flow_tph", "flow", "consumption_tph"))),
                                textOf(pick(props, "upstream_object_id", "next_object_id", "next_id", "next"))));
                        break;
                    case "chamber":
                        data.chambers.put(oid, new Model.Chamber(
                                oid, oidNode,
                                geom instanceof Point ? (Point) geom : geom.getCentroid(),
                                asFloatObj(pick(props, "diameter", "diameter_mm", "dn_mm", "dn")),
                                (int) orZero(asFloatObj(pick(props, "occupied_connections", "occupied"))),
                                textOf(pick(props, "upstream_object_id", "next_object_id", "next_id", "next"))));
                        break;
                    case "legacy_building": {
                        // Ранняя схема: oks_future с flow_tph на полигоне.
                        // Полигон — ограничение oks (таблица 2), расход наследуют
                        // привязанные точки подключения без собственного flow_tph.
                        double flow = orZero(asFloatObj(pick(props, "flow_tph", "flow", "consumption_tph")));
                        legacyFlow.put(oid, flow);
                        if (geom instanceof Polygon || geom instanceof MultiPolygon) {
                            Model.ConstraintZone zone = new Model.ConstraintZone(
                                    oid, geom, "forbidden", propsToMap(props), "oks");
                            data.constraints.add(zone);
                            oksPolygons.add(zone);
                        }
                        break;
                    }
                    case "connection_point": {
                        // §1.1: самостоятельная цель с собственным flow_tph
                        Point pt = geom instanceof Point ? (Point) geom : geom.getCentroid();
                        double flow = orZero(asFloatObj(pick(props, "flow_tph", "flow", "consumption_tph")));
                        data.targets.put(oid, new Model.ConnectionTarget(oid, oidNode, pt, flow));
                        String owner = textOf(pick(props, "oks_id", "building_id", "parent_id"));
                        if (owner != null) {
                            legacyOwner.put(oid, owner);
                        }
                        break;
                    }
                    case "oks_existing": {
                        // Существующий ОКС — запретная зона с отступом по ДУ (таблица 2)
                        Model.ConstraintZone zone = new Model.ConstraintZone(
                                oid, geom, "forbidden", propsToMap(props), "oks_existing");
                        data.constraints.add(zone);
                        if (geom instanceof Polygon || geom instanceof MultiPolygon) {
                            oksPolygons.add(zone);
                        }
                        break;
                    }
                    case "constraint": {
                        Model.ConstraintZone zone = resolveConstraint(oid, props, geom, refdata, data.warnings);
                        if (zone != null) {
                            data.constraints.add(zone);
                            if (isOks(zone.restrictionType)
                                    && (zone.geom instanceof Polygon || zone.geom instanceof MultiPolygon)) {
                                oksPolygons.add(zone);
                            }
                        }
                        break;
                    }
                    default:
                        break;
                }
            }
        } catch (IOException e) {
            throw new PipelineInputException("не удалось прочитать входной файл: " + e.getMessage());
        }

        // Протокол 16.09.2026 п.9: невалидная геометрия — диагностическая ошибка
        if (!invalidGeom.isEmpty()) {
            String shown = String.join("; ", invalidGeom.subList(0, Math.min(20, invalidGeom.size())));
            String more = invalidGeom.size() > 20 ? "; и ещё " + (invalidGeom.size() - 20) : "";
            throw new PipelineInputException(
                    "невалидная геометрия (" + invalidGeom.size() + " объектов): " + shown + more);
        }

        // Наследование расхода из ранних наборов (oks_id -> flow_tph полигона)
        for (Map.Entry<String, String> e : legacyOwner.entrySet()) {
            Model.ConnectionTarget t = data.targets.get(e.getKey());
            Double flow = legacyFlow.get(e.getValue());
            if (t != null && t.flowTph == 0.0 && flow != null) {
                t.flowTph = flow;
            }
        }

        // §2.2: связь точки подключения с полигоном ОКС — пространственная
        // (идентификатором не задаётся). Содержащий полигон — «свой»:
        // к нему применяется правило финального прямого участка.
        for (Model.ConnectionTarget t : data.targets.values()) {
            Model.ConstraintZone best = null;
            for (Model.ConstraintZone zone : oksPolygons) {
                if (org.locationtech.jts.geom.prep.PreparedGeometryFactory.prepare(zone.geom)
                        .covers(t.point)) {
                    if (best == null || zone.geom.getArea() < best.geom.getArea()) {
                        best = zone;
                    }
                }
            }
            if (best != null) {
                t.oksZoneId = best.objectId;
            }
        }

        if (data.segments.isEmpty() && data.chambers.isEmpty()) {
            throw new PipelineInputException(
                    "во входном файле не найдено объектов конкурсной схемы "
                            + "(heat_network / heat_chamber с properties.object_type)");
        }
        if (data.targets.isEmpty()) {
            data.warnings.add("точки подключения ОКС (oks_connection_point) не найдены — результат пуст");
        }
        if (bounds[0] == Double.POSITIVE_INFINITY) {
            throw new PipelineInputException("входной файл не содержит геометрий");
        }
        data.bounds = bounds;
        return data;
    }

    // ------------------------------------------------------------------
    // СК

    /** Функция проецирования координат из crsFrom в crsWork (поддержка 4326 ↔ UTM). */
    private static Function<double[], double[]> projector(String crsFrom, String crsWork) {
        if (Crs.zoneOf(crsFrom) == 0 && Crs.zoneOf(crsWork) > 0) {
            int zone = Crs.zoneOf(crsWork);
            return xy -> Crs.forward(xy[0], xy[1], zone);
        }
        if (Crs.zoneOf(crsFrom) > 0 && Crs.zoneOf(crsWork) == 0) {
            int zone = Crs.zoneOf(crsFrom);
            return xy -> Crs.inverse(xy[0], xy[1], zone);
        }
        if (crsFrom.equals(crsWork)) {
            return xy -> xy;
        }
        throw new PipelineInputException("неподдерживаемая пара СК: " + crsFrom + " -> " + crsWork);
    }

    /** Верхнеуровневый член 'crs' GeoJSON (если задан в файле). */
    private static String declaredCrs(Path path) {
        ObjectMapper mapper = new ObjectMapper();
        JsonFactory factory = new JsonFactory();
        try (JsonParser p = factory.createParser(Files.newInputStream(path))) {
            int depth = 0;
            while (p.nextToken() != null) {
                JsonToken t = p.currentToken();
                if (t == JsonToken.START_OBJECT || t == JsonToken.START_ARRAY) {
                    depth++;
                } else if (t == JsonToken.END_OBJECT || t == JsonToken.END_ARRAY) {
                    depth--;
                } else if (t == JsonToken.FIELD_NAME && depth == 1) {
                    String name = p.currentName();
                    if ("crs".equals(name)) {
                        p.nextToken();
                        JsonNode crs = mapper.readTree(p);
                        JsonNode props = crs.get("properties");
                        JsonNode n = props != null ? props.get("name") : null;
                        return n != null && n.isTextual() ? n.asText() : null;
                    }
                    if ("features".equals(name)) {
                        return null;
                    }
                }
            }
        } catch (IOException e) {
            throw new PipelineInputException("не удалось прочитать входной файл: " + e.getMessage());
        }
        return null;
    }

    /**
     * Код EPSG из обозначения СК. CRS84 (стандартный CRS GeoJSON по
     * RFC 7946, долгота/широта WGS 84) эквивалентен EPSG:4326 в порядке
     * координат GeoJSON — официальный датасет объявляет именно его.
     */
    private static Integer epsgCode(String text) {
        if (text == null) {
            return null;
        }
        String up = text.toUpperCase(java.util.Locale.ROOT);
        if (up.contains("CRS84") || up.contains("CRS:84")) {
            return 4326;
        }
        Matcher m = EPSG_RE.matcher(text);
        return m.find() ? Integer.parseInt(m.group(1)) : null;
    }

    // ------------------------------------------------------------------
    // геометрия

    /** Shapely-аналог: геометрия из GeoJSON (Point/LineString/Polygon/MultiPolygon). */
    private static Geometry buildGeom(JsonNode geom) {
        if (geom == null || !geom.isObject()) {
            return null;
        }
        JsonNode typeNode = geom.get("type");
        JsonNode coords = geom.get("coordinates");
        if (typeNode == null || coords == null) {
            return null;
        }
        switch (typeNode.asText()) {
            case "Point":
                return GF.createPoint(toCoordinate(coords));
            case "LineString":
                return GF.createLineString(toCoordinates(coords));
            case "MultiLineString": {
                List<LineString> lines = new ArrayList<>();
                for (JsonNode part : coords) {
                    lines.add(GF.createLineString(toCoordinates(part)));
                }
                return GF.createMultiLineString(lines.toArray(new LineString[0]));
            }
            case "Polygon": {
                List<Coordinate[]> rings = new ArrayList<>();
                for (JsonNode ring : coords) {
                    rings.add(toCoordinates(ring));
                }
                if (rings.isEmpty()) {
                    return null;
                }
                LinearRing shell = GF.createLinearRing(rings.get(0));
                LinearRing[] holes = new LinearRing[rings.size() - 1];
                for (int i = 1; i < rings.size(); i++) {
                    holes[i - 1] = GF.createLinearRing(rings.get(i));
                }
                return GF.createPolygon(shell, holes);
            }
            case "MultiPolygon": {
                List<Polygon> polys = new ArrayList<>();
                for (JsonNode poly : coords) {
                    List<Coordinate[]> rings = new ArrayList<>();
                    for (JsonNode ring : poly) {
                        rings.add(toCoordinates(ring));
                    }
                    if (rings.isEmpty()) {
                        continue;
                    }
                    LinearRing shell = GF.createLinearRing(rings.get(0));
                    LinearRing[] holes = new LinearRing[rings.size() - 1];
                    for (int i = 1; i < rings.size(); i++) {
                        holes[i - 1] = GF.createLinearRing(rings.get(i));
                    }
                    polys.add(GF.createPolygon(shell, holes));
                }
                return GF.createMultiPolygon(polys.toArray(new Polygon[0]));
            }
            default:
                return null;
        }
    }

    private static Coordinate toCoordinate(JsonNode pos) {
        return new Coordinate(pos.get(0).asDouble(), pos.get(1).asDouble());
    }

    private static Coordinate[] toCoordinates(JsonNode arr) {
        Coordinate[] out = new Coordinate[arr.size()];
        for (int i = 0; i < arr.size(); i++) {
            out[i] = toCoordinate(arr.get(i));
        }
        return out;
    }

    private static Geometry project(Geometry g, Function<double[], double[]> project) {
        if (g == null) {
            return null;
        }
        Geometry copy = g.copy();
        copy.apply((org.locationtech.jts.geom.CoordinateFilter) c -> {
            double[] xy = project.apply(new double[]{c.x, c.y});
            c.x = xy[0];
            c.y = xy[1];
        });
        return copy;
    }

    /**
     * Диагностика невалидной геометрии (протокол 16.09.2026 п.9).
     * null — геометрия корректна; иначе — текст причины.
     */
    static String geometryProblem(Geometry geom) {
        if (geom == null) {
            return "отсутствует или неподдерживаемый тип геометрии";
        }
        if (geom.isEmpty()) {
            return "пустая геометрия";
        }
        var env = geom.getEnvelopeInternal();
        if (!Double.isFinite(env.getMinX()) || !Double.isFinite(env.getMinY())
                || !Double.isFinite(env.getMaxX()) || !Double.isFinite(env.getMaxY())) {
            return "неконечные координаты";
        }
        if ((geom instanceof Polygon || geom instanceof MultiPolygon) && !geom.isValid()) {
            return "невалидный полигон (самопересечение, OGC)";
        }
        if (geom instanceof LineString && geom.getLength() <= 0) {
            return "нулевая длина линии";
        }
        return null;
    }

    private static void extendBounds(double[] bounds, Geometry g) {
        var env = g.getEnvelopeInternal();
        bounds[0] = Math.min(bounds[0], env.getMinX());
        bounds[1] = Math.min(bounds[1], env.getMinY());
        bounds[2] = Math.max(bounds[2], env.getMaxX());
        bounds[3] = Math.max(bounds[3], env.getMaxY());
    }

    // ------------------------------------------------------------------
    // ограничения

    /** ОКС-тип ограничения (свои полигоны подключения). */
    static boolean isOks(String restrictionType) {
        return "oks".equals(restrictionType) || "oks_existing".equals(restrictionType);
    }

    /** Свести restriction к виду правила (forbidden / special_passage). */
    private static Model.ConstraintZone resolveConstraint(String oid, Map<String, JsonNode> props,
                                                          Geometry geom, RefData refdata,
                                                          List<String> warnings) {
        String raw = textOf(pick(props, "restriction_type", "constraint_type", "kind"));
        raw = raw == null ? "" : raw.trim();
        String rtype = RESTRICTION_TYPE_ALIASES.getOrDefault(raw, raw);
        Map<String, Object> rule = refdata != null ? refdata.restrictionRule(rtype) : null;
        if (rule == null) {
            warnings.add(oid + ": неизвестный тип ограничения '" + raw + "' — пропущен");
            return null;
        }
        String kind = "forbidden".equals(rule.get("rule")) ? "forbidden" : "special_passage";
        return new Model.ConstraintZone(oid, geom, kind, propsToMap(props), rtype);
    }

    // ------------------------------------------------------------------
    // утилиты атрибутов

    static JsonNode pick(Map<String, JsonNode> props, String... names) {
        for (String name : names) {
            JsonNode v = props.get(name);
            if (v != null && !v.isNull()) {
                return v;
            }
        }
        return null;
    }

    static String textOf(JsonNode node) {
        if (node == null || node.isNull()) {
            return null;
        }
        return node.isTextual() ? node.asText() : node.asText();
    }

    static Double asFloatObj(JsonNode node) {
        if (node == null || node.isNull()) {
            return null;
        }
        try {
            if (node.isNumber()) {
                return node.asDouble();
            }
            return Double.parseDouble(node.asText().trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    static double orZero(Double v) {
        return v == null ? 0.0 : v;
    }

    static Map<String, Object> propsToMap(Map<String, JsonNode> props) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map.Entry<String, JsonNode> e : props.entrySet()) {
            JsonNode v = e.getValue();
            if (v.isNumber()) {
                out.put(e.getKey(), v.asDouble());
            } else if (v.isTextual()) {
                out.put(e.getKey(), v.asText());
            } else if (v.isBoolean()) {
                out.put(e.getKey(), v.asBoolean());
            } else {
                out.put(e.getKey(), v.toString());
            }
        }
        return out;
    }
}
