package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Point;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Существующая сеть: участки, камеры, источники.
 *
 * Число занятых примыканий камеры выводится из ГЕОМЕТРИИ (§2.1,
 * разъяснение №12): каждый линейный участок, геометрически
 * заканчивающийся в камере, — одно примыкание; линия, проходящая
 * через камеру и разделённая ею на две части, — два примыкания.
 * Реконструкция существующей сети отменена (§2.4, разъяснение №14),
 * поэтому цепочки upstream_object_id больше не используются.
 */
public class ExistingNetwork {

    public final Map<String, Model.Segment> segments;
    public final Map<String, Model.Chamber> chambers;
    public final Map<String, Model.Source> sources;

    public ExistingNetwork(Map<String, Model.Segment> segments,
                           Map<String, Model.Chamber> chambers,
                           Map<String, Model.Source> sources) {
        this.segments = segments;
        this.chambers = chambers;
        this.sources = sources;
    }

    // ---------- камеры ----------

    /**
     * Число занятых примыканий камеры — по геометрии (допуск snapM).
     * Конец участка в пределах snapM от камеры — примыкание; участок,
     * проходящий через камеру без конца в ней, — два примыкания.
     * Запасные источники (топология ранних наборов, occupied_connections)
     * учитываются как максимум.
     */
    public int chamberConnections(String chamberId, double snapM) {
        Model.Chamber chamber = chambers.get(chamberId);
        if (chamber == null) {
            return 0;
        }
        int geometric = 0;
        for (Model.Segment s : segments.values()) {
            if (s.geom.distance(chamber.geom) > snapM) {
                continue;
            }
            int ends = 0;
            Coordinate[] coords = s.geom.getCoordinates();
            if (chamber.geom.distance(s.geom.getFactory().createPoint(coords[0])) <= snapM) {
                ends++;
            }
            if (coords.length > 1
                    && chamber.geom.distance(
                            s.geom.getFactory().createPoint(coords[coords.length - 1])) <= snapM) {
                ends++;
            }
            geometric += ends > 0 ? ends : 2; // линия через камеру — два примыкания
        }
        // запасной подсчёт по топологии ранних наборов
        int incoming = 0;
        for (Model.Segment s : segments.values()) {
            if (chamberId.equals(s.nextObjectId)) {
                incoming++;
            }
        }
        int outgoing = chamber.nextObjectId != null && segments.containsKey(chamber.nextObjectId) ? 1 : 0;
        int topo = incoming + outgoing;
        return Math.max(geometric, Math.max(topo, chamber.occupiedConnections));
    }

    /** Свободные примыкания с учётом назначенных в этом расчёте. */
    public int chamberFreeConnections(String chamberId, Map<String, Integer> extraUsed,
                                      int maxConn, double snapM) {
        if (!chambers.containsKey(chamberId)) {
            return 0;
        }
        int used = chamberConnections(chamberId, snapM) + extraUsed.getOrDefault(chamberId, 0);
        return Math.max(0, maxConn - used);
    }

    // ---------- геометрический поиск ----------

    /** Участки в радиусе от точки: (object_id, distance_m), по возрастанию. */
    public List<Map.Entry<String, Double>> segmentsNear(Point point, double radiusM) {
        List<Map.Entry<String, Double>> out = new ArrayList<>();
        for (Map.Entry<String, Model.Segment> e : segments.entrySet()) {
            double d = e.getValue().geom.distance(point);
            if (d <= radiusM) {
                out.add(Map.entry(e.getKey(), d));
            }
        }
        out.sort(Map.Entry.comparingByValue());
        return out;
    }

    /** Камеры в радиусе от точки, по возрастанию расстояния. */
    public List<Map.Entry<String, Double>> chambersNear(Point point, double radiusM) {
        List<Map.Entry<String, Double>> out = new ArrayList<>();
        for (Map.Entry<String, Model.Chamber> e : chambers.entrySet()) {
            double d = e.getValue().geom.distance(point);
            if (d <= radiusM) {
                out.add(Map.entry(e.getKey(), d));
            }
        }
        out.sort(Map.Entry.comparingByValue());
        return out;
    }
}
