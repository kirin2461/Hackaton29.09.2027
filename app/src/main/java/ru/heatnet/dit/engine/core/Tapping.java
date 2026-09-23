package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Point;

import java.util.List;
import java.util.Map;

/**
 * Выбор точки присоединения к существующей сети — §2.4 (разъяснение №11).
 *
 * Детерминированно:
 *   1) точка присоединения — ближайшая проекция цели на существующий
 *      участок сети (в радиусе tap_search_radius_m);
 *   2) если не далее 10 м от неё (или от самой цели) есть существующая
 *      камера, у которой после подключения будет не более четырёх
 *      примыканий, — используется эта камера (ближайшая из подходящих).
 *      Новый участок сети заканчивается в ней;
 *   3) иначе — НОВАЯ камера непосредственно в выбранной точке
 *      существующего участка. Отдельный геообъект места присоединения
 *      не формируется.
 *
 * Стоимость: врезка в существующую камеру — 5 млн ₽ за КАЖДЫЙ новый
 * линейный участок, заканчивающийся в ней (§3.2, считается в Costs);
 * стоимость новой камеры включает присоединение к сети.
 */
public final class Tapping {

    private Tapping() {
    }

    /** Выбранная точка присоединения. */
    public static class Tap {
        public final String kind;           // "existing_chamber" | "new_chamber_on_segment"
        public final Point point;           // точка присоединения (метрическая СК)
        public final double flowTph;        // расход, который войдёт в сеть в этой точке
        public double requiredDn;           // ДУ новой сети в точке присоединения
        public String chamberId;            // для existing_chamber
        public String segmentId;            // для new_chamber_on_segment
        public String nodeId;               // id узла (назначается конвейером)

        public Tap(String kind, Point point, double flowTph, double requiredDn,
                   String chamberId, String segmentId) {
            this.kind = kind;
            this.point = point;
            this.flowTph = flowTph;
            this.requiredDn = requiredDn;
            this.chamberId = chamberId;
            this.segmentId = segmentId;
        }
    }

    /** Строгое правило §2.4 выбора точки присоединения. */
    public static Tap chooseTapStrict(Point anchor, double flowTph,
                                      ExistingNetwork net, RefData refdata,
                                      Map<String, Integer> chamberLoad) {
        return chooseTapStrict(anchor, flowTph, net, refdata, chamberLoad, null);
    }

    /**
     * Строгое правило §2.4 + §3.1: новая камера не должна попадать в отступ
     * чужой запретной зоны. Если ближайшая проекция нарушает отступ,
     * точка сдвигается вдоль того же участка к ближайшей «чистой» позиции
     * (шаг 2 м, до ±30 м). Существующие камеры не сдвигаются — они часть
     * действующей сети.
     */
    public static Tap chooseTapStrict(Point anchor, double flowTph,
                                      ExistingNetwork net, RefData refdata,
                                      Map<String, Integer> chamberLoad,
                                      ConstraintGrid grid) {
        double maxDist = refdata.rule("chamber_tap_max_dist_m");
        int maxConn = (int) refdata.rule("max_chamber_connections");
        double snapM = refdata.rule("chamber_snap_m");
        double requiredDn = RefData.num(refdata.diameterForFlow(flowTph).get("dn_mm"));

        // --- шаг 1: точка присоединения — проекция на ближайший участок ---
        List<Map.Entry<String, Double>> near =
                net.segmentsNear(anchor, refdata.rule("tap_search_radius_m"));
        Point projection = null;
        String projectionSegmentId = null;
        if (!near.isEmpty()) {
            projectionSegmentId = near.get(0).getKey();
            Model.Segment seg = net.segments.get(projectionSegmentId);
            org.locationtech.jts.linearref.LengthIndexedLine lil =
                    new org.locationtech.jts.linearref.LengthIndexedLine(seg.geom);
            double along = lil.indexOf(anchor.getCoordinate());
            org.locationtech.jts.geom.Coordinate c = lil.extractPoint(along);
            projection = seg.geom.getFactory().createPoint(c);
        }

        // --- шаг 2: существующая камера ≤ 10 м от точки присоединения ---
        String best = null;
        double bestDist = Double.POSITIVE_INFINITY;
        if (projection != null) {
            for (Map.Entry<String, Double> e : net.chambersNear(projection, maxDist)) {
                if (net.chamberFreeConnections(e.getKey(), chamberLoad, maxConn, snapM) <= 0) {
                    continue;
                }
                if (e.getValue() < bestDist) {
                    bestDist = e.getValue();
                    best = e.getKey();
                }
            }
        }
        // камера рядом с самой целью (точку присоединения можно выбрать и там)
        for (Map.Entry<String, Double> e : net.chambersNear(anchor, maxDist)) {
            if (net.chamberFreeConnections(e.getKey(), chamberLoad, maxConn, snapM) <= 0) {
                continue;
            }
            double d = e.getValue();
            if (d < bestDist) {
                bestDist = d;
                best = e.getKey();
            }
        }
        if (best != null) {
            Model.Chamber ch = net.chambers.get(best);
            return new Tap("existing_chamber", ch.geom, flowTph, requiredDn, best, null);
        }

        // --- шаг 3: новая камера в выбранной точке существующего участка ---
        if (projection == null) {
            return null; // сети в радиусе поиска нет — точка уйдёт в неподключённые
        }
        // §3.1: точка новой камеры обязана выдерживать отступы запретных зон
        if (grid != null && grid.forbiddenReason(projection, requiredDn,
                java.util.Collections.<String>emptySet()) != null) {
            Model.Segment seg = net.segments.get(projectionSegmentId);
            org.locationtech.jts.linearref.LengthIndexedLine lil =
                    new org.locationtech.jts.linearref.LengthIndexedLine(seg.geom);
            double along = lil.indexOf(anchor.getCoordinate());
            double found = Double.NaN;
            for (double off = 2.0; off <= 30.0 && Double.isNaN(found); off += 2.0) {
                for (double sgn : new double[]{1.0, -1.0}) {
                    double idx = along + sgn * off;
                    if (idx < lil.getStartIndex() || idx > lil.getEndIndex()) {
                        continue;
                    }
                    Point cand = seg.geom.getFactory().createPoint(lil.extractPoint(idx));
                    if (grid.forbiddenReason(cand, requiredDn,
                            java.util.Collections.<String>emptySet()) == null) {
                        found = idx;
                        break;
                    }
                }
            }
            if (!Double.isNaN(found)) {
                projection = seg.geom.getFactory().createPoint(lil.extractPoint(found));
            }
            // чистой позиции на участке нет — оставляем исходную проекцию,
            // конвейер запишет предупреждение
        }
        return new Tap("new_chamber_on_segment", projection, flowTph, requiredDn,
                null, projectionSegmentId);
    }
}
