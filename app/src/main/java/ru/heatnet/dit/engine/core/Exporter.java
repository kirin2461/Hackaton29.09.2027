package ru.heatnet.dit.engine.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.NullNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.locationtech.jts.geom.Coordinate;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

/**
 * Экспорт результата в выходной GeoJSON — строго по §7 техприложения
 * (актуальная редакция).
 *
 * Один файл FeatureCollection (EPSG:4326) содержит объекты ВСЕХ вариантов
 * (variant_id у каждого объекта). Четыре типа объектов (§7.1):
 * heat_network (новые участки), heat_chamber (новые камеры),
 * technical_node, variant_summary (geometry: null).
 * Идентификаторы oks_connection_point и существующих heat_chamber в
 * ссылочных полях и unconnected_oks_ids сохраняют исходный тип (§7.2).
 */
public final class Exporter {

    private Exporter() {
    }

    /** Записать результат: все варианты в один FeatureCollection (EPSG:4326). */
    public static void writeResult(Path path, Model.ContestData data,
                                   List<Pipeline.Variant> variants,
                                   Map<String, Object> summary) {
        int workZone = Crs.zoneOf(data.crsWork);

        ObjectMapper mapper = new ObjectMapper();
        ArrayNode features = mapper.createArrayNode();

        for (Pipeline.Variant variant : variants) {
            String vid = String.valueOf(variant.rank);

            // --- §7.2: новые линейные участки ---
            for (NewSegment seg : variant.newSegments) {
                ObjectNode props = mapper.createObjectNode();
                props.put("id", seg.objectId);
                props.put("object_type", "heat_network");
                props.put("variant_id", vid);
                putNodeId(props, "start_node_id", seg.startNodeId, data);
                putNodeId(props, "end_node_id", seg.endNodeId, data);
                props.put("flow_tph", Math.rint(seg.flowTph * 1000.0) / 1000.0);
                props.put("diameter", (int) seg.diameterMm);
                props.put("length", Math.rint(seg.lengthM * 10.0) / 10.0);
                props.put("laying_method", seg.method);   // base | special
                if (seg.depthStart != null) {
                    props.put("depth_start", seg.depthStart);
                } else {
                    props.set("depth_start", NullNode.getInstance());
                }
                if (seg.depthEnd != null) {
                    props.put("depth_end", seg.depthEnd);
                } else {
                    props.set("depth_end", NullNode.getInstance());
                }
                props.put("cost", Math.rint(seg.costRub * 100.0) / 100.0);
                features.add(feature(mapper, lineTo4326(seg.coords, workZone), props));
            }

            // --- §7.2: новые камеры ---
            for (Pipeline.NewChamber ch : variant.newChambers) {
                ObjectNode props = mapper.createObjectNode();
                props.put("id", ch.objectId);
                props.put("object_type", "heat_chamber");
                props.put("variant_id", vid);
                props.put("diameter", (int) ch.diameterMm);
                props.put("cost", Math.rint(ch.costRub * 100.0) / 100.0);
                features.add(feature(mapper, pointTo4326(ch.point, workZone), props));
            }

            // --- §7.2: технические узлы ---
            for (TechnicalNode node : variant.techNodes) {
                ObjectNode props = mapper.createObjectNode();
                props.put("id", node.objectId);
                props.put("object_type", "technical_node");
                props.put("variant_id", vid);
                props.put("reason", node.reason); // доп. поле (§7: допускается)
                features.add(feature(mapper, pointTo4326(node.point, workZone), props));
            }

            // --- §7.2: сводка по варианту (geometry: null) ---
            ObjectNode props = mapper.createObjectNode();
            props.put("id", "summary-" + vid);
            props.put("object_type", "variant_summary");
            props.put("variant_id", vid);
            props.put("rank", variant.rank);
            props.put("construction_cost", variant.costs.get("construction_cost"));
            props.put("chamber_construction_cost",
                    variant.costs.get("chamber_construction_cost"));
            props.put("existing_chamber_tie_in_count",
                    variant.costs.get("existing_chamber_tie_in_count").intValue());
            props.put("existing_chamber_tie_in_cost",
                    variant.costs.get("existing_chamber_tie_in_cost"));
            props.put("unconnected_penalty", variant.costs.get("unconnected_penalty"));
            props.put("calculated_cost", variant.costs.get("calculated_cost"));
            props.put("new_network_length", variant.lengths.get("new_network_length"));
            props.put("score", variant.score);
            ArrayNode unc = mapper.createArrayNode();
            for (Pipeline.Unconnected u : variant.unconnected) {
                // §7.2: тип идентификатора сохраняется как во входных данных
                Model.ConnectionTarget t = data.targets.get(u.buildingId);
                if (t != null && t.idRaw != null && (t.idRaw.isNumber() || t.idRaw.isTextual())) {
                    unc.add(t.idRaw);
                } else {
                    unc.add(u.buildingId);
                }
            }
            props.set("unconnected_oks_ids", unc);
            features.add(feature(mapper, null, props));
        }

        ObjectNode root = mapper.createObjectNode();
        root.put("type", "FeatureCollection");
        root.set("features", features);

        try {
            Path parent = path.getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            mapper.writeValue(path.toFile(), root);
        } catch (IOException e) {
            throw new IllegalStateException("не удалось записать результат: " + e.getMessage(), e);
        }
    }

    // ------------------------------------------------------------------

    /**
     * Ссылка на узел (§7.2): для oks_connection_point и существующих
     * heat_chamber — исходный id с сохранением типа; для новых узлов —
     * внутренний строковый идентификатор.
     */
    private static void putNodeId(ObjectNode props, String key, String nodeId,
                                  Model.ContestData data) {
        if (nodeId == null) {
            props.set(key, NullNode.getInstance());
            return;
        }
        Model.ConnectionTarget t = data.targets.get(nodeId);
        if (t != null && t.idRaw != null && (t.idRaw.isNumber() || t.idRaw.isTextual())) {
            props.set(key, t.idRaw);
            return;
        }
        Model.Chamber ch = data.chambers.get(nodeId);
        if (ch != null && ch.idRaw != null && (ch.idRaw.isNumber() || ch.idRaw.isTextual())) {
            props.set(key, ch.idRaw);
            return;
        }
        props.put(key, nodeId);
    }

    private static ObjectNode feature(ObjectMapper mapper, JsonNode geom, ObjectNode props) {
        ObjectNode f = mapper.createObjectNode();
        f.put("type", "Feature");
        if (geom != null) {
            f.set("geometry", geom);
        } else {
            f.set("geometry", NullNode.getInstance());
        }
        f.set("properties", props);
        return f;
    }

    // ------------------------------------------------------------------
    // GeoJSON mapping (EPSG:4326)

    private static JsonNode lineTo4326(List<Coordinate> coords, int zone) {
        ArrayNode arr = JsonNodeFactory.instance.arrayNode();
        for (Coordinate c : coords) {
            arr.add(posTo4326(c.x, c.y, zone));
        }
        ObjectNode g = JsonNodeFactory.instance.objectNode();
        g.put("type", "LineString");
        g.set("coordinates", arr);
        return g;
    }

    private static JsonNode pointTo4326(org.locationtech.jts.geom.Point p, int zone) {
        ObjectNode g = JsonNodeFactory.instance.objectNode();
        g.put("type", "Point");
        g.set("coordinates", posTo4326(p.getX(), p.getY(), zone));
        return g;
    }

    private static ArrayNode posTo4326(double x, double y, int zone) {
        double[] lonlat = Crs.inverse(x, y, zone);
        ArrayNode pos = JsonNodeFactory.instance.arrayNode();
        pos.add(lonlat[0]);
        pos.add(lonlat[1]);
        return pos;
    }
}
