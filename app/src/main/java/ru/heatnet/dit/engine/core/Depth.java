package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.Point;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

/**
 * Задание на глубину (раздел 6, доп. задача): вертикальный профиль трассы.
 *
 * Режим включается ENGINE_DEPTH_MODE=1. В основной двумерной задаче (§8.1)
 * глубины не вычисляются — depth_start/depth_end = null, Kгл = 1.
 */
public final class Depth {

    private static final GeometryFactory GF = new GeometryFactory();

    private Depth() {
    }

    /** Квантование отметки шагом 0,5 м с соблюдением минимума 0,7 м. */
    public static double quantize(double depthM, RefData ref) {
        double step = ref.depthRule("step_m", 0.5);
        double dmin = ref.depthRule("min_depth_m", 0.7);
        return Math.max(dmin, Math.rint(Math.rint(depthM / step) * step * 1000.0) / 1000.0);
    }

    /** Целевая (базовая) глубина заложения, квантованная шагом. */
    public static double targetDepthM(RefData ref) {
        return quantize(ref.depthRule("base_depth_m", 3.0), ref);
    }

    /** Требуемые отметки на пересечениях: [startM, endM, depthM]. */
    @SuppressWarnings("unchecked")
    private static List<double[]> crossingConstraints(NewSegment seg, RefData ref,
                                                      List<Model.ConstraintZone> specialZones) {
        LineString line = GF.createLineString(seg.coords.toArray(new Coordinate[0]));
        double length = line.getLength();
        double base = targetDepthM(ref);
        double flat = ref.depthRule("crossing_flat_m", 4.0);
        List<double[]> out = new ArrayList<>();
        double envH = ref.envelopeHeightM(seg.diameterMm);

        for (Model.ConstraintZone z : specialZones) {
            if (!line.intersects(z.geom)) {
                continue;
            }
            Map<String, Object> rule = ref.restrictionRule(z.restrictionType);
            if (rule == null) {
                continue;
            }
            Object vert = rule.get("vertical_clearance_m");
            Object under = rule.get("under_clearance_m");
            if (vert == null && under == null) {
                continue;
            }
            Geometry inter = line.intersection(z.geom);
            List<double[]> pts = ConstraintGrid.intervalPoints(inter);
            if (pts.isEmpty()) {
                continue;
            }
            org.locationtech.jts.linearref.LengthIndexedLine lil =
                    new org.locationtech.jts.linearref.LengthIndexedLine(line);
            double dMin = Double.POSITIVE_INFINITY, dMax = Double.NEGATIVE_INFINITY;
            for (double[] p : pts) {
                double d = lil.indexOf(new Coordinate(p[0], p[1]));
                dMin = Math.min(dMin, d);
                dMax = Math.max(dMax, d);
            }
            double d = (dMin + dMax) / 2.0;
            if (under != null) {
                double need = quantize(RefData.num(under), ref); // верх габарита глубже просвета
                if (need > base) {
                    out.add(new double[]{Math.max(0.0, d - flat / 2),
                            Math.min(length, d + flat / 2), need});
                }
                continue;
            }
            // выше или ниже существующей коммуникации — что дешевле
            Map<String, Object> existMap = (Map<String, Object>) ref.depth.get("existing_depth_m");
            double existD = 1.5;
            if (existMap != null && z.restrictionType != null && existMap.get(z.restrictionType) != null) {
                existD = RefData.num(existMap.get(z.restrictionType));
            }
            double above = quantize(existD - RefData.num(vert) - envH, ref);
            double below = quantize(existD + RefData.num(vert) + envH, ref);
            double chosen = ref.depthK(above) <= ref.depthK(below) ? above : below;
            if (Math.abs(chosen - base) > 1e-9) {
                out.add(new double[]{Math.max(0.0, d - flat / 2),
                        Math.min(length, d + flat / 2), chosen});
            }
        }
        return out;
    }

    /**
     * Продольный профиль: [distanceM, depthM] с пандусами ≤ maxSlope.
     * Требуемые отметки соединяются с базовой глубиной пандусами
     * ограниченного уклона; результат квантуется шагом 0,5 м.
     */
    private static List<double[]> profile(double length, List<double[]> constraints,
                                          Double entryDepthM, RefData ref) {
        double base = targetDepthM(ref);
        double slope = Math.max(ref.depthRule("max_slope", 0.10), 1e-6);
        double step = 2.0;
        int n = Math.max(2, (int) (length / step) + 1);
        double[] xs = new double[n];
        for (int i = 0; i < n; i++) {
            xs[i] = i * length / (n - 1);
        }
        double[] target = new double[n];
        java.util.Arrays.fill(target, base);
        if (entryDepthM != null) {
            target[0] = quantize(entryDepthM, ref);
        }
        for (double[] c : constraints) {
            for (int i = 0; i < n; i++) {
                if (c[0] - 1e-9 <= xs[i] && xs[i] <= c[1] + 1e-9) {
                    if (c[2] > base) {
                        target[i] = Math.max(target[i], c[2]);
                    } else {
                        target[i] = target[i] == base ? c[2] : Math.min(target[i], c[2]);
                    }
                }
            }
        }

        // сглаживание уклоном: прямой и обратный проход
        double[] prof = target.clone();
        for (int iter = 0; iter < 4; iter++) {
            for (int i = 1; i < n; i++) {
                prof[i] = prof[i] > prof[i - 1]
                        ? Math.min(prof[i], prof[i - 1] + slope * (xs[i] - xs[i - 1]))
                        : Math.max(prof[i], prof[i - 1] - slope * (xs[i] - xs[i - 1]));
            }
            for (int i = n - 2; i >= 0; i--) {
                prof[i] = prof[i] > prof[i + 1]
                        ? Math.min(prof[i], prof[i + 1] + slope * (xs[i + 1] - xs[i]))
                        : Math.max(prof[i], prof[i + 1] - slope * (xs[i + 1] - xs[i]));
            }
            // ограничения — жёсткие: восстанавливаем после сглаживания
            for (double[] c : constraints) {
                for (int i = 0; i < n; i++) {
                    if (c[0] - 1e-9 <= xs[i] && xs[i] <= c[1] + 1e-9) {
                        if (c[2] > base) {
                            prof[i] = Math.max(prof[i], c[2]);
                        } else {
                            prof[i] = Math.min(prof[i], c[2]);
                        }
                    }
                }
            }
        }
        List<double[]> out = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            out.add(new double[]{xs[i], quantize(prof[i], ref)});
        }
        return out;
    }

    /**
     * Построить профиль §6, разрезать участок на отметке 3,0 м, посчитать Kгл.
     * Возвращает подучастки с depthStart/depthEnd и coords3d.
     */
    public static List<NewSegment> applyDepth(NewSegment seg, RefData ref, Map<String, Integer> seq,
                                              List<TechnicalNode> techNodes,
                                              List<Model.ConstraintZone> specialZones,
                                              Double entryDepthM) {
        LineString line = GF.createLineString(seg.coords.toArray(new Coordinate[0]));
        double length = line.getLength();
        double base = targetDepthM(ref);
        List<double[]> constraints = crossingConstraints(seg, ref, specialZones);
        List<double[]> prof = profile(length, constraints, entryDepthM, ref);

        // точки деления: где профиль пересекает базовую отметку
        TreeSet<Double> cuts = new TreeSet<>();
        cuts.add(0.0);
        for (int i = 1; i < prof.size(); i++) {
            double h0 = prof.get(i - 1)[1], h1 = prof.get(i)[1];
            if ((h0 - base) * (h1 - base) < 0) {
                double x0 = prof.get(i - 1)[0], x1 = prof.get(i)[0];
                double t = (base - h0) / (h1 - h0);
                cuts.add(x0 + t * (x1 - x0));
            }
        }
        cuts.add(length);
        List<Double> cutList = new ArrayList<>();
        for (double c : cuts) {
            cutList.add(Math.rint(c * 100.0) / 100.0);
        }
        cutList = new ArrayList<>(new TreeSet<>(cutList));

        List<NewSegment> parts = new ArrayList<>();
        String curStartNode = seg.startNodeId;
        for (int k = 0; k < cutList.size() - 1; k++) {
            double a = cutList.get(k), b = cutList.get(k + 1);
            if (b - a < 0.01) {
                continue;
            }
            LineString piece = Hydraulics.subline(line, a, b);
            double dA = depthAt(prof, a);
            double dB = depthAt(prof, b);
            boolean isLast = k == cutList.size() - 2;
            String endNode;
            if (isLast) {
                endNode = seg.endNodeId;
            } else {
                seq.merge("tech", 1, Integer::sum);
                endNode = "node-" + seq.get("tech");
                org.locationtech.jts.linearref.LengthIndexedLine lil =
                        new org.locationtech.jts.linearref.LengthIndexedLine(line);
                Coordinate pc = lil.extractPoint(b);
                techNodes.add(new TechnicalNode(endNode,
                        GF.createPoint(pc), "пересечение отметки 3,0 м (раздел 6)"));
            }
            NewSegment part = new NewSegment(
                    k == 0 && isLast ? seg.objectId : seg.objectId + "." + (k + 1),
                    new ArrayList<>(List.of(piece.getCoordinates())),
                    seg.flowTph, seg.role, seg.method, seg.kSpecial,
                    curStartNode, endNode);
            part.diameterMm = seg.diameterMm;
            part.warnings = new ArrayList<>(seg.warnings);
            part.depthStart = Math.rint(dA * 100.0) / 100.0;
            part.depthEnd = Math.rint(dB * 100.0) / 100.0;
            double kAvg = (ref.depthK(dA) + ref.depthK(dB)) / 2.0;
            part.tariffRubM = seg.tariffRubM;
            part.costRub = seg.costRub * (part.lengthM / Math.max(seg.lengthM, 1e-9)) * kAvg;
            part.coords3d = coords3d(piece, prof, a, b);
            parts.add(part);
            curStartNode = endNode;
        }

        if (parts.isEmpty()) { // вырожденный случай — участок как есть
            seg.depthStart = base;
            seg.depthEnd = base;
            List<double[]> c3 = new ArrayList<>();
            for (Coordinate c : seg.coords) {
                c3.add(new double[]{c.x, c.y, -base});
            }
            seg.coords3d = c3;
            parts.add(seg);
        }
        return parts;
    }

    /** Глубина профиля в точке x (линейная интерполяция). */
    private static double depthAt(List<double[]> prof, double x) {
        if (x <= prof.get(0)[0]) {
            return prof.get(0)[1];
        }
        if (x >= prof.get(prof.size() - 1)[0]) {
            return prof.get(prof.size() - 1)[1];
        }
        for (int i = 1; i < prof.size(); i++) {
            if (prof.get(i)[0] >= x) {
                double x0 = prof.get(i - 1)[0], h0 = prof.get(i - 1)[1];
                double x1 = prof.get(i)[0], h1 = prof.get(i)[1];
                double t = (x - x0) / Math.max(x1 - x0, 1e-9);
                return h0 + t * (h1 - h0);
            }
        }
        return prof.get(prof.size() - 1)[1];
    }

    /** 3D-координаты куска: Z = −глубина (м, ниже поверхности). */
    private static List<double[]> coords3d(LineString piece, List<double[]> prof,
                                           double a, double b) {
        List<double[]> out = new ArrayList<>();
        double len = piece.getLength();
        org.locationtech.jts.linearref.LengthIndexedLine lil =
                new org.locationtech.jts.linearref.LengthIndexedLine(piece);
        for (Coordinate c : piece.getCoordinates()) {
            double d = lil.indexOf(c);
            out.add(new double[]{c.x, c.y, -depthAt(prof, a + (len > 1e-9 ? d : 0.0))});
        }
        return out;
    }
}
