package ru.heatnet.dit.engine.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.NullNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.MultiPolygon;
import org.locationtech.jts.geom.Point;
import org.locationtech.jts.geom.Polygon;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

/**
 * Экспорт результата в выходной GeoJSON — строго по разделу 10.
 *
 * Один файл FeatureCollection (EPSG:4326) содержит объекты ВСЕХ вариантов
 * (variant_id у каждого объекта). Ровно семь типов объектов, у каждого —
 * только свой набор атрибутов (таблицы 10.1–10.7), без посторонних полей
 * и без metadata.
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

            // --- §10.1: новые линейные участки ---
            for (NewSegment seg : variant.newSegments) {
                ObjectNode props = mapper.createObjectNode();
                props.put("id", seg.objectId);
                props.put("object_type", "heat_network");
                props.put("variant_id", vid);
                props.put("start_node_id", seg.startNodeId);
                props.put("end_node_id", seg.endNodeId);
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

            // --- §10.2: точки врезки ---
            for (Tapping.Tap tap : variant.taps) {
                String existingId;
                String existingType;
                double existingDn;
                if ("existing_chamber".equals(tap.kind)) {
                    Model.Chamber ch = data.chambers.get(tap.chamberId);
                    existingId = tap.chamberId;
                    existingType = "heat_chamber";
                    existingDn = chamberExistingDn(ch, data);
                } else {
                    Model.Segment seg0 = data.segments.get(tap.segmentId);
                    existingId = tap.segmentId;
                    existingType = "heat_network";
                    existingDn = seg0.diameterOrZero();
                }
                ObjectNode props = mapper.createObjectNode();
                props.put("id", tap.nodeId);
                props.put("object_type", "tie_in");
                props.put("variant_id", vid);
                props.put("existing_object_id", existingId);
                props.put("existing_object_type", existingType);
                props.put("existing_diameter", (int) existingDn);
                props.put("required_diameter", (int) tap.requiredDn);
                props.put("cost", Math.rint(tap.tapCostRub * 100.0) / 100.0);
                features.add(feature(mapper, pointTo4326(tap.point, workZone), props));
            }

            // --- §10.3: реконструкция линейных участков ---
            for (Reconstruction.ReconSegment rs : variant.recon.segments) {
                ObjectNode props = mapper.createObjectNode();
                props.put("id", rs.objectId);
                props.put("object_type", "heat_network_reconstruction");
                props.put("variant_id", vid);
                props.put("existing_object_id", rs.existingObjectId);
                props.put("existing_flow_tph", rs.existingFlow);
                props.put("added_flow_tph", rs.addedFlow);
                props.put("calculated_flow_tph", rs.calculatedFlow);
                props.put("existing_diameter", (int) rs.existingDn);
                props.put("required_diameter", (int) rs.requiredDn);
                props.put("length", rs.lengthM);
                props.put("cost", rs.costRub);
                features.add(feature(mapper, geomTo4326(rs.geom, workZone), props));
            }

            // --- §10.4: новые камеры ---
            for (Pipeline.NewChamber ch : variant.newChambers) {
                ObjectNode props = mapper.createObjectNode();
                props.put("id", ch.objectId);
                props.put("object_type", "heat_chamber");
                props.put("variant_id", vid);
                props.put("diameter", (int) ch.diameterMm);
                props.put("cost", Math.rint(ch.costRub * 100.0) / 100.0);
                features.add(feature(mapper, pointTo4326(ch.point, workZone), props));
            }

            // --- §10.5: реконструкция существующих камер ---
            for (Reconstruction.ReconChamber rc : variant.recon.chambers) {
                Model.Chamber src = data.chambers.get(rc.existingObjectId);
                ObjectNode props = mapper.createObjectNode();
                props.put("id", rc.objectId);
                props.put("object_type", "heat_chamber_reconstruction");
                props.put("variant_id", vid);
                props.put("existing_object_id", rc.existingObjectId);
                props.put("existing_diameter", (int) rc.existingDn);
                props.put("required_diameter", (int) rc.requiredDn);
                props.put("cost", rc.costRub);
                features.add(feature(mapper, pointTo4326(src.geom, workZone), props));
            }

            // --- §10.6: технические узлы ---
            for (TechnicalNode node : variant.techNodes) {
                ObjectNode props = mapper.createObjectNode();
                props.put("id", node.objectId);
                props.put("object_type", "technical_node");
                props.put("variant_id", vid);
                features.add(feature(mapper, pointTo4326(node.point, workZone), props));
            }

            // --- §10.7: сводная запись варианта (geometry: null) ---
            ObjectNode props = mapper.createObjectNode();
            props.put("id", "summary-" + vid);
            props.put("object_type", "variant_summary");
            props.put("variant_id", vid);
            props.put("rank", variant.rank);
            for (String k : List.of("construction_cost", "chamber_construction_cost",
                    "tie_in_cost", "reconstruction_cost", "chamber_reconstruction_cost",
                    "unconnected_penalty", "calculated_cost")) {
                props.put(k, variant.costs.get(k));
            }
            for (String k : List.of("new_network_length", "reconstruction_length", "length")) {
                props.put(k, variant.lengths.get(k));
            }
            props.put("score", variant.score);
            ArrayNode unc = mapper.createArrayNode();
            for (Pipeline.Unconnected u : variant.unconnected) {
                unc.add(u.buildingId);
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

    private static double chamberExistingDn(Model.Chamber ch, Model.ContestData data) {
        if (ch.diameterMm != null && ch.diameterMm != 0.0) {
            return ch.diameterMm;
        }
        double best = 0.0;
        for (Model.Segment s : data.segments.values()) {
            if (ch.objectId.equals(s.nextObjectId)) {
                best = Math.max(best, s.diameterOrZero());
            }
        }
        return best;
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

    private static JsonNode geomTo4326(Geometry geom, int zone) {
        if (geom instanceof Point) {
            return pointTo4326((Point) geom, zone);
        }
        if (geom instanceof LineString) {
            ArrayNode arr = JsonNodeFactory.instance.arrayNode();
            for (Coordinate c : geom.getCoordinates()) {
                arr.add(posTo4326(c.x, c.y, zone));
            }
            ObjectNode g = JsonNodeFactory.instance.objectNode();
            g.put("type", "LineString");
            g.set("coordinates", arr);
            return g;
        }
        if (geom instanceof Polygon) {
            return polygonTo4326((Polygon) geom, zone);
        }
        if (geom instanceof MultiPolygon) {
            ArrayNode polys = JsonNodeFactory.instance.arrayNode();
            for (int i = 0; i < geom.getNumGeometries(); i++) {
                polys.add(polygonCoordsTo4326((Polygon) geom.getGeometryN(i), zone));
            }
            ObjectNode g = JsonNodeFactory.instance.objectNode();
            g.put("type", "MultiPolygon");
            g.set("coordinates", polys);
            return g;
        }
        throw new IllegalArgumentException("неподдерживаемый тип геометрии выгрузки: "
                + geom.getGeometryType());
    }

    private static JsonNode pointTo4326(Point p, int zone) {
        ObjectNode g = JsonNodeFactory.instance.objectNode();
        g.put("type", "Point");
        g.set("coordinates", posTo4326(p.getX(), p.getY(), zone));
        return g;
    }

    private static JsonNode polygonTo4326(Polygon poly, int zone) {
        ObjectNode g = JsonNodeFactory.instance.objectNode();
        g.put("type", "Polygon");
        g.set("coordinates", polygonCoordsTo4326(poly, zone));
        return g;
    }

    private static ArrayNode polygonCoordsTo4326(Polygon poly, int zone) {
        ArrayNode rings = JsonNodeFactory.instance.arrayNode();
        ArrayNode shell = JsonNodeFactory.instance.arrayNode();
        for (Coordinate c : poly.getExteriorRing().getCoordinates()) {
            shell.add(posTo4326(c.x, c.y, zone));
        }
        rings.add(shell);
        for (int i = 0; i < poly.getNumInteriorRing(); i++) {
            ArrayNode hole = JsonNodeFactory.instance.arrayNode();
            for (Coordinate c : poly.getInteriorRingN(i).getCoordinates()) {
                hole.add(posTo4326(c.x, c.y, zone));
            }
            rings.add(hole);
        }
        return rings;
    }

    private static ArrayNode posTo4326(double x, double y, int zone) {
        double[] lonlat = Crs.inverse(x, y, zone);
        ArrayNode pos = JsonNodeFactory.instance.arrayNode();
        pos.add(lonlat[0]);
        pos.add(lonlat[1]);
        return pos;
    }
}
