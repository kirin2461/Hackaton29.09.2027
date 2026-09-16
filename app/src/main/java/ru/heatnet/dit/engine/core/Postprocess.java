package ru.heatnet.dit.engine.core;

import org.locationtech.jts.algorithm.MinimumDiameter;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.Polygon;
import org.locationtech.jts.simplify.TopologyPreservingSimplifier;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Постобработка геометрии трасс (§2.6 ТЗ).
 *   - упрощение полилинии (Douglas–Peucker с сохранением топологии);
 *   - удаление зигзагов/«ступеней» — выбросы с разворотом > 150°;
 *   - проверка самопересечений новых участков вне общих узлов;
 *   - контроль угла пересечения дорог/трамваев (таблица 5.1: не менее 45°).
 */
public final class Postprocess {

    private static final GeometryFactory GF = new GeometryFactory();

    private Postprocess() {
    }

    /** Угол поворота в точке b (0° — прямо, 180° — полный разворот). */
    private static double angleDeg(Coordinate a, Coordinate b, Coordinate c) {
        double v1x = b.x - a.x, v1y = b.y - a.y;
        double v2x = c.x - b.x, v2y = c.y - b.y;
        double l1 = Math.hypot(v1x, v1y), l2 = Math.hypot(v2x, v2y);
        if (l1 < 1e-9 || l2 < 1e-9) {
            return 0.0;
        }
        double cos = Math.max(-1.0, Math.min(1.0, (v1x * v2x + v1y * v2y) / (l1 * l2)));
        return Math.toDegrees(Math.acos(-cos)); // разворот = 180° - угол между векторами
    }

    /** Выпрямление: упрощение Дугласа–Пекера + удаление зигзагов. */
    public static List<Coordinate> simplifyPath(List<Coordinate> points, double toleranceM) {
        if (points.size() < 3) {
            return points;
        }
        LineString line = GF.createLineString(points.toArray(new Coordinate[0]));
        LineString simplified = (LineString) TopologyPreservingSimplifier.simplify(line, toleranceM);
        List<Coordinate> pts = new ArrayList<>(List.of(simplified.getCoordinates()));

        // Удаление зигзагов: точки с разворотом > 150° («елочка» растра)
        double maxZigzag = 150.0;
        boolean changed = true;
        while (changed && pts.size() >= 3) {
            changed = false;
            for (int i = 1; i < pts.size() - 1; i++) {
                if (angleDeg(pts.get(i - 1), pts.get(i), pts.get(i + 1)) > maxZigzag) {
                    pts.remove(i);
                    changed = true;
                    break;
                }
            }
        }
        // Python round(x, 2) — half-even (rint)
        List<Coordinate> out = new ArrayList<>();
        for (Coordinate p : pts) {
            out.add(new Coordinate(Math.rint(p.x * 100.0) / 100.0,
                    Math.rint(p.y * 100.0) / 100.0));
        }
        return out;
    }

    /** true, если полилиния простая (без самопересечений вне узлов). */
    public static boolean checkSelfIntersection(List<Coordinate> points) {
        if (points.size() < 4) {
            return true;
        }
        return GF.createLineString(points.toArray(new Coordinate[0])).isSimple();
    }

    // ------------------------------------------------------------------
    // Угол пересечения (таблица 5.1: road / tram_tracks — не менее 45°)

    /**
     * Угол пересечения трассы с зоной (0–90°). null — пересечения нет.
     * Для полигонов направление зоны — главная ось минимального повёрнутого
     * прямоугольника; для линий — направление в точке пересечения.
     */
    public static Double crossingAngleDeg(LineString line, Geometry zoneGeom) {
        if (!line.intersects(zoneGeom)) {
            return null;
        }
        Geometry inter = line.intersection(zoneGeom);
        double[] chord = chordDirection(inter.getLength() > 1e-6 ? inter : line);
        if (chord == null) {
            return null;
        }
        double[] zoneDir;
        String t = zoneGeom.getGeometryType();
        if ("Polygon".equals(t) || "MultiPolygon".equals(t)) {
            zoneDir = rectDirection(new MinimumDiameter(zoneGeom).getMinimumRectangle());
        } else {
            zoneDir = chordDirection(zoneGeom);
        }
        if (zoneDir == null) {
            return null;
        }
        double dot = Math.abs(chord[0] * zoneDir[0] + chord[1] * zoneDir[1]);
        return Math.toDegrees(Math.acos(Math.max(-1.0, Math.min(1.0, dot))));
    }

    /** Единичный вектор направления по хорде «первая—последняя точка». */
    private static double[] chordDirection(Geometry geom) {
        Coordinate[] coords;
        String t = geom.getGeometryType();
        if ("LineString".equals(t)) {
            coords = geom.getCoordinates();
        } else if ("MultiLineString".equals(t)) {
            List<Coordinate> all = new ArrayList<>();
            for (int i = 0; i < geom.getNumGeometries(); i++) {
                all.addAll(List.of(geom.getGeometryN(i).getCoordinates()));
            }
            coords = all.toArray(new Coordinate[0]);
        } else if ("Point".equals(t)) {
            return null;
        } else {
            try {
                Geometry boundary = geom.getBoundary();
                if (boundary == null) {
                    return null;
                }
                coords = boundary.getCoordinates();
            } catch (RuntimeException ex) {
                return null;
            }
        }
        if (coords == null || coords.length < 2) {
            return null;
        }
        double dx = coords[coords.length - 1].x - coords[0].x;
        double dy = coords[coords.length - 1].y - coords[0].y;
        double l = Math.hypot(dx, dy);
        if (l < 1e-9) {
            return null;
        }
        return new double[]{dx / l, dy / l};
    }

    /** Направление длинной стороны минимального повёрнутого прямоугольника. */
    private static double[] rectDirection(Geometry rect) {
        if (!(rect instanceof Polygon)) {
            return null;
        }
        Coordinate[] coords = ((Polygon) rect).getExteriorRing().getCoordinates();
        int n = Math.min(coords.length, 4);
        double[] best = null;
        double bestLen = -1.0;
        for (int i = 0; i < n; i++) {
            Coordinate a = coords[i];
            Coordinate b = coords[(i + 1) % coords.length];
            double dx = b.x - a.x, dy = b.y - a.y;
            double l = Math.hypot(dx, dy);
            if (l > bestLen) {
                bestLen = l;
                best = l > 1e-9 ? new double[]{dx / l, dy / l} : null;
            }
        }
        return best;
    }

    /** Предупреждение, если пересечение дороги/трамвая острее 45°. */
    public static void checkCrossingAngles(LineString line, List<Model.ConstraintZone> specialZones,
                                           List<String> warnings, String owner) {
        for (Model.ConstraintZone z : specialZones) {
            String rtype = z.restrictionType;
            if (!"road".equals(rtype) && !"tram_tracks".equals(rtype)) {
                continue;
            }
            Double angle = crossingAngleDeg(line, z.geom);
            if (angle != null && angle < 45.0) {
                warnings.add(String.format(Locale.ROOT,
                        "%s: пересечение %s (%s) под углом %.0f° < 45° (таблица 5.1)",
                        owner, z.objectId, rtype, angle));
            }
        }
    }
}
