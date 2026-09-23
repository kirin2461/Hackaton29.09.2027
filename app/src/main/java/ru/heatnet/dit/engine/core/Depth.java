package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

/**
 * Дополнительный режим с учётом глубины (§5 техприложения).
 *
 * Глубина — до ВЕРХА расчётного габарита. Обычная 3,0 м, минимальная 0,7 м,
 * максимальная не ограничена, дискретный шаг не задаётся (разъяснение №16).
 * Уклон спуска/подъёма ≤ 0,10 м/м. Kгл = 1 при h ≤ 3,0 м, иначе
 * Kгл = 1 + 0,10·(h − 3); на равномерном спуске/подъёме — среднее
 * арифметическое Kгл на концах. Пересечение отметки 3,0 м — технический
 * узел и деление участка. Z-координаты не формируются — только атрибуты
 * depth_start/depth_end.
 *
 * Режим включается ENGINE_DEPTH_MODE=1. В базовом 2D-режиме глубины null,
 * Kгл = 1.
 */
public final class Depth {

    private static final GeometryFactory GF = new GeometryFactory();

    private Depth() {
    }

    /** Приведение отметки: не ниже минимума 0,7 м, округление до сантиметра. */
    public static double quantize(double depthM, RefData ref) {
        double dmin = ref.depthRule("min_depth_m", 0.7);
        return Math.max(dmin, Math.rint(depthM * 100.0) / 100.0);
    }

    /** Базовая глубина заложения (до верха габарита). */
    public static double targetDepthM(RefData ref) {
        return ref.depthRule("base_depth_m", 3.0);
    }

    // типы ограничений профиля
    private static final int EXACT = 0;  // точная отметка (выше/ниже коммуникации)
    private static final int FLOOR = 1;  // нижняя граница (не мельче)

    /** Требуемые отметки на пересечениях: [startM, endM, depthM, type]. */
    private static List<double[]> crossingConstraints(NewSegment seg, RefData ref,
                                                      List<Model.ConstraintZone> specialZones,
                                                      ConstraintGrid grid) {
        LineString line = GF.createLineString(seg.coords.toArray(new Coordinate[0]));
        double length = line.getLength();
        double base = targetDepthM(ref);
        double minD = ref.depthRule("min_depth_m", 0.7);
        double flat = ref.depthRule("crossing_flat_m", 4.0);
        List<double[]> out = new ArrayList<>();
        double envH = ref.envelopeHeightM(seg.diameterMm);

        double slope = Math.max(ref.depthRule("max_slope", 0.10), 1e-6);
        org.locationtech.jts.linearref.LengthIndexedLine lil =
                new org.locationtech.jts.linearref.LengthIndexedLine(line);
        for (Model.ConstraintZone z : specialZones) {
            Map<String, Object> rule = ref.restrictionRule(z.restrictionType);
            if (rule == null) {
                continue;
            }
            Object vert = rule.get("vertical_clearance_m");
            Object under = rule.get("under_clearance_m");
            if (vert == null && under == null) {
                continue;
            }
            boolean hits = z.geom.distance(line) <= 1e-9;
            double d;      // ось препятствия вдоль линии
            double a, b;   // окно обязательной отметки
            if (hits) {
                Geometry inter = line.intersection(z.geom);
                List<double[]> pts = ConstraintGrid.intervalPoints(inter);
                if (pts.isEmpty()) {
                    continue;
                }
                double dMin = Double.POSITIVE_INFINITY, dMax = Double.NEGATIVE_INFINITY;
                for (double[] p : pts) {
                    double dd = lil.indexOf(new Coordinate(p[0], p[1]));
                    dMin = Math.min(dMin, dd);
                    dMax = Math.max(dMax, dd);
                }
                d = (dMin + dMax) / 2.0;
                a = Math.max(0.0, d - flat / 2);
                b = Math.min(length, d + flat / 2);
                // место присоединения к существующей сети — не пересечение
                // (разъяснение №10): вертикальные ограничения там не действуют
                if (grid != null) {
                    double extent = RefData.num(rule.getOrDefault("extent_m", 0.0));
                    if (grid.tapExclusionNear(z.objectId, lil, a, b, extent + 1.0)) {
                        continue;
                    }
                }
            } else {
                // Препятствие за пределами участка: его пандус (уклон ≤ 0,10)
                // может заходить в этот участок через граничный узел — тогда
                // на конце участка требуется та же отметка (§5). Параллельные
                // зоны (ближайшая точка — не конец) игнорируются.
                Coordinate[] np = org.locationtech.jts.operation.distance.DistanceOp
                        .nearestPoints(line, z.geom);
                double endIdx = lil.indexOf(np[0]);
                boolean atEnd = endIdx <= 1e-6 || endIdx >= length - 1e-6;
                if (!atEnd) {
                    continue;
                }
                d = endIdx;
                a = b = endIdx; // точечное требование на границе
            }
            double required; // требуемая отметка
            int type;
            if (under != null) {
                // дорога/трамвай: верх габарита не мельче заданной отметки
                required = quantize(RefData.num(under), ref);
                type = FLOOR;
            } else {
                // выше или ниже существующей коммуникации — что дешевле (§4, таблица 2)
                Map<String, Object> util = ref.existingUtility(z.restrictionType);
                if (util == null) {
                    continue;
                }
                double clearance = RefData.num(vert);
                double existTop = RefData.num(util.get("depth_top_m"));
                double existH = util.get("height_m") != null
                        ? RefData.num(util.get("height_m"))
                        : existingEnvelopeHeight(z, ref);
                double above = quantize(existTop - clearance - envH, ref); // верх новой выше низа существующей
                double below = quantize(existTop + existH + clearance, ref); // верх новой ниже низа существующей
                if (above < minD + 1e-9) {
                    required = below; // «выше» физически невозможно — только «ниже»
                } else {
                    required = ref.depthK(above) <= ref.depthK(below) ? above : below;
                }
                type = EXACT;
            }
            if (type == EXACT && Math.abs(required - base) <= 1e-9) {
                continue;
            }
            if (!hits) {
                // пандус дотягивается до этого участка только в пределах длины спуска
                double rampLen = Math.abs(required - base) / slope + flat / 2;
                double gap = z.geom.distance(line);
                if (gap > rampLen + 1e-9) {
                    continue;
                }
            }
            out.add(new double[]{a, b, required, type});
        }
        return out;
    }

    /** Габарит существующей тепловой сети — по таблице 1 (ДУ из параметров зоны). */
    private static double existingEnvelopeHeight(Model.ConstraintZone z, RefData ref) {
        Object dn = z.params != null ? z.params.get("diameter") : null;
        double dnMm = dn instanceof Number ? ((Number) dn).doubleValue() : 500.0;
        return ref.envelopeHeightM(dnMm);
    }

    /**
     * Продольный профиль: [distanceM, depthM] с пандусами ≤ maxSlope.
     * Точные отметки (выше/ниже коммуникаций) соединяются с базовой глубиной
     * пандусами ограниченного уклона; между близкими препятствиями изменённая
     * глубина сохраняется (§5). Нижние границы (дороги/трамваи) удерживаются
     * как «не мельче».
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
        double[] prof = new double[n];
        java.util.Arrays.fill(prof, base);
        boolean[] pin = new boolean[n]; // точные отметки неподвижны (§5)
        if (entryDepthM != null) {
            prof[0] = quantize(entryDepthM, ref);
            pin[0] = true;
        }
        for (double[] c : constraints) {
            if (c[3] != EXACT) {
                continue;
            }
            for (int i = 0; i < n; i++) {
                if (c[0] - 1e-9 <= xs[i] && xs[i] <= c[1] + 1e-9) {
                    if (c[2] > base) {
                        prof[i] = Math.max(prof[i], c[2]);
                    } else {
                        prof[i] = pin[i] ? Math.min(prof[i], c[2]) : c[2];
                    }
                    pin[i] = true;
                }
            }
        }

        // сглаживание уклоном: прямой и обратный проход; закреплённые точки
        // не трогаем — иначе прямой проход «съедает» пандус (восстановление
        // после обратного прохода зацикливается без распространения влево)
        for (int iter = 0; iter < 8; iter++) {
            for (int i = 1; i < n; i++) {
                if (pin[i]) {
                    continue;
                }
                double s = slope * (xs[i] - xs[i - 1]);
                prof[i] = prof[i] > prof[i - 1]
                        ? Math.min(prof[i], prof[i - 1] + s)
                        : Math.max(prof[i], prof[i - 1] - s);
            }
            for (int i = n - 2; i >= 0; i--) {
                if (pin[i]) {
                    continue;
                }
                double s = slope * (xs[i + 1] - xs[i]);
                prof[i] = prof[i] > prof[i + 1]
                        ? Math.min(prof[i], prof[i + 1] + s)
                        : Math.max(prof[i], prof[i + 1] - s);
            }
            // нижние границы (дороги/трамваи) удерживаем после каждого прохода
            for (double[] c : constraints) {
                if (c[3] != FLOOR) {
                    continue;
                }
                for (int i = 0; i < n; i++) {
                    if (c[0] - 1e-9 <= xs[i] && xs[i] <= c[1] + 1e-9) {
                        prof[i] = Math.max(prof[i], c[2]);
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
     * Построить профиль §5, разрезать участок на отметке 3,0 м, посчитать Kгл.
     * Возвращает подучастки с depthStart/depthEnd и служебным coords3d.
     */
    public static List<NewSegment> applyDepth(NewSegment seg, RefData ref, Map<String, Integer> seq,
                                              List<TechnicalNode> techNodes,
                                              List<Model.ConstraintZone> specialZones,
                                              Double entryDepthM) {
        return applyDepth(seg, ref, seq, techNodes, specialZones, entryDepthM, null);
    }

    /** Вариант с учётом точек присоединения (разъяснение №10). */
    public static List<NewSegment> applyDepth(NewSegment seg, RefData ref, Map<String, Integer> seq,
                                              List<TechnicalNode> techNodes,
                                              List<Model.ConstraintZone> specialZones,
                                              Double entryDepthM, ConstraintGrid grid) {
        LineString line = GF.createLineString(seg.coords.toArray(new Coordinate[0]));
        double length = line.getLength();
        double base = targetDepthM(ref);
        List<double[]> constraints = crossingConstraints(seg, ref, specialZones, grid);
        List<double[]> prof = profile(length, constraints, entryDepthM, ref);

        // точки деления: переходы «базовая отметка ↔ отклонение» (начало и
        // конец пандуса — §5: пересечение отметки 3,0 м = технический узел),
        // а также пересечение 3,0 м в середине пандуса (спуск «с мелкой на
        // глубокую»), чтобы каждый подучасток был равномерным по глубине.
        TreeSet<Double> cuts = new TreeSet<>();
        cuts.add(0.0);
        double tol = 5e-3;
        for (int i = 1; i < prof.size(); i++) {
            double h0 = prof.get(i - 1)[1], h1 = prof.get(i)[1];
            boolean atBase0 = Math.abs(h0 - base) <= tol;
            boolean atBase1 = Math.abs(h1 - base) <= tol;
            if (atBase0 != atBase1) {
                cuts.add(atBase0 ? prof.get(i - 1)[0] : prof.get(i)[0]);
            } else if (!atBase0 && (h0 - base) * (h1 - base) < 0) {
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
                        GF.createPoint(pc), "пересечение отметки 3,0 м (§5)"));
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
            // §5: на равномерном спуске/подъёме — среднее арифметическое Kгл
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

    /** Служебные 3D-координаты куска (в GeoJSON не выгружаются, §5). */
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
