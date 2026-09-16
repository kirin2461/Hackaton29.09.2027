package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Point;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Граф существующей сети по цепочкам upstream_object_id (§2.2).
 *
 * Каждый участок/камера знает ID следующего объекта по направлению
 * к источнику. Цепочка ведёт от любого объекта до источника — это путь
 * распространения дополнительного расхода для реконструкции (раздел 7).
 *
 * Число занятых примыканий камеры выводится из ТОПОЛОГИИ (официальная
 * схема ввода не содержит такого атрибута): участки, указывающие на
 * камеру как на следующий объект, плюс исходящая цепочка самой камеры.
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

    public Object get(String objectId) {
        Object o = segments.get(objectId);
        if (o == null) {
            o = chambers.get(objectId);
        }
        if (o == null) {
            o = sources.get(objectId);
        }
        return o;
    }

    static String nextIdOf(Object obj) {
        if (obj instanceof Model.Segment) {
            return ((Model.Segment) obj).nextObjectId;
        }
        if (obj instanceof Model.Chamber) {
            return ((Model.Chamber) obj).nextObjectId;
        }
        return null;
    }

    /**
     * Цепочка object_id от объекта до источника (включительно).
     * Обрыв (upstream_object_id отсутствует в наборе) трактуем как
     * «достигнут источник». Циклы обрезаются.
     */
    public List<String> chainToSource(String startId) {
        List<String> chain = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        String cur = startId;
        while (cur != null && !seen.contains(cur)) {
            seen.add(cur);
            Object obj = get(cur);
            if (obj == null) {
                break;
            }
            chain.add(cur);
            cur = nextIdOf(obj);
        }
        return chain;
    }

    // ---------- камеры ----------

    /**
     * Число занятых примыканий камеры — из топологии цепочек.
     * Если топология не задана совсем — запасной ввод occupied_connections.
     */
    public int chamberConnections(String chamberId) {
        Model.Chamber chamber = chambers.get(chamberId);
        if (chamber == null) {
            return 0;
        }
        int incoming = 0;
        for (Model.Segment s : segments.values()) {
            if (chamberId.equals(s.nextObjectId)) {
                incoming++;
            }
        }
        int outgoing = chamber.nextObjectId != null && segments.containsKey(chamber.nextObjectId) ? 1 : 0;
        int topo = incoming + outgoing;
        return Math.max(topo, chamber.occupiedConnections);
    }

    /** Свободные примыкания с учётом назначенных в этом расчёте. */
    public int chamberFreeConnections(String chamberId, Map<String, Integer> extraUsed, int maxConn) {
        if (!chambers.containsKey(chamberId)) {
            return 0;
        }
        int used = chamberConnections(chamberId) + extraUsed.getOrDefault(chamberId, 0);
        return Math.max(0, maxConn - used);
    }

    /** ID участков, примыкающих к камере (обе стороны цепочки). */
    public List<String> chamberAdjacentSegmentIds(String chamberId) {
        List<String> ids = new ArrayList<>();
        for (Map.Entry<String, Model.Segment> e : segments.entrySet()) {
            if (chamberId.equals(e.getValue().nextObjectId)) {
                ids.add(e.getKey());
            }
        }
        Model.Chamber ch = chambers.get(chamberId);
        if (ch != null && ch.nextObjectId != null && segments.containsKey(ch.nextObjectId)) {
            ids.add(ch.nextObjectId);
        }
        return ids;
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
