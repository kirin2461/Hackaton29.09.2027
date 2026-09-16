package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Point;

import java.util.List;
import java.util.Map;

/**
 * Выбор точки врезки в существующую сеть — строгое правило §8.2.
 *
 * Никакой эвристики ранжирования кандидатов. Детерминированно:
 *   1) если от точки подключения до существующей камеры ≤ 10 м
 *      и у камеры меньше 4 примыкающих участков (считая уже назначенные
 *      в этом расчёте) — врезка в эту камеру (ближайшую из подходящих);
 *   2) иначе — строительство НОВОЙ камеры на ближайшей проекции
 *      точки подключения на существующий участок сети (в радиусе
 *      tap_search_radius_m); если участков в радиусе нет — null
 *      (ОКС уйдёт в unconnected, §2.9).
 *
 * Стоимость врезки — 5 000 000 ₽ за КАЖДУЮ врезку (§8.2), независимо
 * от вида точки врезки.
 */
public final class Tapping {

    private Tapping() {
    }

    /** Выбранная точка врезки. */
    public static class Tap {
        public final String kind;           // "existing_chamber" | "new_chamber_on_segment"
        public final Point point;           // точка врезки (метрическая СК)
        public final double flowTph;        // расход, который войдёт в сеть в этой точке
        public double requiredDn;           // Ду новой сети в точке врезки (§10.2)
        public String chamberId;            // для existing_chamber
        public String segmentId;            // для new_chamber_on_segment
        public double alongM;               // отметка точки врезки вдоль участка (для §7)
        public String chainStartId;         // с чего начинать цепочку к источнику
        public double tapCostRub;
        public String nodeId;               // tie-N (назначается конвейером)

        public Tap(String kind, Point point, double flowTph, double requiredDn,
                   String chamberId, String segmentId, double alongM,
                   String chainStartId, double tapCostRub) {
            this.kind = kind;
            this.point = point;
            this.flowTph = flowTph;
            this.requiredDn = requiredDn;
            this.chamberId = chamberId;
            this.segmentId = segmentId;
            this.alongM = alongM;
            this.chainStartId = chainStartId;
            this.tapCostRub = tapCostRub;
        }
    }

    /** Строгое правило §8.2 выбора точки врезки. */
    public static Tap chooseTapStrict(org.locationtech.jts.geom.Point anchor,
                                      double flowTph,
                                      ExistingNetwork net,
                                      RefData refdata,
                                      Map<String, Integer> chamberLoad) {
        double maxDist = refdata.rule("chamber_tap_max_dist_m");
        int maxConn = (int) refdata.rule("max_chamber_connections");
        double requiredDn = RefData.num(refdata.diameterForFlow(flowTph).get("dn_mm"));
        double tieCost = refdata.tieInCost();

        // --- шаг 1: камера ≤ 10 м со свободными примыканиями ---
        String best = null;
        double bestDist = Double.POSITIVE_INFINITY;
        for (Map.Entry<String, Double> e : net.chambersNear(anchor, maxDist)) {
            if (net.chamberFreeConnections(e.getKey(), chamberLoad, maxConn) <= 0) {
                continue; // камера рядом, но примыканий уже 4 — новая камера
            }
            if (e.getValue() < bestDist) {
                bestDist = e.getValue();
                best = e.getKey();
            }
        }
        if (best != null) {
            Model.Chamber ch = net.chambers.get(best);
            return new Tap("existing_chamber", ch.geom, flowTph, requiredDn,
                    best, null, 0.0, best, tieCost);
        }

        // --- шаг 2: новая камера на ближайшей проекции на участок ---
        List<Map.Entry<String, Double>> near =
                net.segmentsNear(anchor, refdata.rule("tap_search_radius_m"));
        if (near.isEmpty()) {
            return null;
        }
        String sid = near.get(0).getKey();
        Model.Segment seg = net.segments.get(sid);
        org.locationtech.jts.linearref.LengthIndexedLine lil =
                new org.locationtech.jts.linearref.LengthIndexedLine(seg.geom);
        double along = lil.indexOf(anchor.getCoordinate());
        org.locationtech.jts.geom.Coordinate c = lil.extractPoint(along);
        Point pt = seg.geom.getFactory().createPoint(c);
        return new Tap("new_chamber_on_segment", pt, flowTph, requiredDn,
                null, sid, along, sid, tieCost);
    }
}
