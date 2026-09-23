package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.linearref.LengthIndexedLine;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Гидравлика новой сети: расходы, диаметры, предельные длины (§2.3, таблица 1).
 *
 *   - расход участка — сумма flow_tph всех точек подключения далее по сети;
 *   - ДУ — минимальный, удовлетворяющий И расходу, И предельной длине
 *     (разъяснение №1: повышение на сколько угодно шагов, не произвольное);
 *   - предельная длина проверяется по каждому непрерывному пути отдельно;
 *     общий участок учитывается в каждом пути, ветви не суммируются;
 *     камера/техузел без смены ДУ новый отсчёт не начинают (разъяснение №2);
 *   - по направлению от точки подключения к месту присоединения ДУ
 *     не уменьшается (монотонность).
 */
public final class Hydraulics {

    private static final GeometryFactory GF = new GeometryFactory();

    private Hydraulics() {
    }

    /** Кусок полилинии между двумя отметками длины (передискретизация на 32 точки). */
    public static LineString subline(LineString line, double startM, double endM) {
        int n = 32;
        LengthIndexedLine lil = new LengthIndexedLine(line);
        Coordinate[] pts = new Coordinate[n + 1];
        for (int k = 0; k <= n; k++) {
            pts[k] = lil.extractPoint(startM + (endM - startM) * k / n);
        }
        return GF.createLineString(pts);
    }

    /** Пересчитать ставку и стоимость участка (после смены ДУ). */
    public static void reprice(NewSegment seg, RefData refdata) {
        double tariff = refdata.layTariff(seg.diameterMm);
        if ("special".equals(seg.method)) {
            tariff *= seg.kSpecial != null ? seg.kSpecial : 1.5;
        }
        seg.tariffRubM = tariff;
        seg.costRub = seg.lengthM * tariff;
    }

    /** Первичный подбор ДУ — минимальный по расходу (таблица 1). */
    public static void sizeSegment(NewSegment seg, RefData refdata) {
        Map<String, Object> d = refdata.diameterForFlow(seg.flowTph);
        if (RefData.num(d.get("max_flow_tph")) < seg.flowTph) {
            seg.warnings.add(String.format(Locale.ROOT,
                    "расход %.1f т/ч превышает справочный максимум %.1f т/ч",
                    seg.flowTph, RefData.num(d.get("max_flow_tph"))));
        }
        seg.diameterMm = RefData.num(d.get("dn_mm"));
        reprice(seg, refdata);
    }

    /** Минимальный ДУ, покрывающий и расход, и предельную длину (§2.3). */
    private static double minDnFor(double flowTph, double lengthM, RefData ref) {
        for (Map<String, Object> d : ref.diameters) {
            if (RefData.num(d.get("max_flow_tph")) >= flowTph
                    && RefData.num(d.get("max_len_m")) >= lengthM) {
                return RefData.num(d.get("dn_mm"));
            }
        }
        return RefData.num(ref.diameters.get(ref.diameters.size() - 1).get("dn_mm"));
    }

    /**
     * §2.3: предельная длина по каждому непрерывному пути + монотонность ДУ.
     *
     * Новая сеть — лес деревьев (проверяется assertTree). Для каждого пути
     * «место присоединения → точка подключения» непрерывные серии одного ДУ
     * не должны превышать предельную длину этого ДУ; при нарушении серия
     * повышается до минимального подходящего ДУ. Затем обеспечивается
     * монотонность: от точки к месту присоединения ДУ не уменьшается.
     * Итерации повторяются до стабилизации (ДУ только растёт — сходимость
     * ограничена числом номенклатурных шагов).
     */
    public static void enforceDiameterRules(List<NewSegment> segments, RefData ref,
                                            List<String> warnings) {
        if (segments.isEmpty()) {
            return;
        }
        // узел -> входящий участок (дерево: не более одного)
        Map<String, NewSegment> incoming = new HashMap<>();
        Map<String, List<NewSegment>> outgoing = new HashMap<>();
        for (NewSegment s : segments) {
            if (s.endNodeId != null) {
                incoming.put(s.endNodeId, s);
            }
            if (s.startNodeId != null) {
                outgoing.computeIfAbsent(s.startNodeId, k -> new ArrayList<>()).add(s);
            }
        }
        // корни — стартовые узлы без входящего участка; листья — конечные без исходящих
        List<String> roots = new ArrayList<>();
        for (NewSegment s : segments) {
            if (s.startNodeId != null && !incoming.containsKey(s.startNodeId)
                    && !roots.contains(s.startNodeId)) {
                roots.add(s.startNodeId);
            }
        }
        // все пути «корень → лист» (списки участков в порядке от корня)
        List<List<NewSegment>> paths = new ArrayList<>();
        for (String root : roots) {
            for (NewSegment first : outgoing.getOrDefault(root, List.of())) {
                collectPaths(first, incoming, outgoing, new ArrayList<>(), paths);
            }
        }
        if (paths.isEmpty()) {
            return;
        }

        boolean changed = true;
        int guard = 0;
        while (changed && guard++ < 64) {
            changed = false;
            // 1) предельная длина непрерывных серий одного ДУ в каждом пути
            for (List<NewSegment> path : paths) {
                int i = 0;
                while (i < path.size()) {
                    double dn = path.get(i).diameterMm;
                    int j = i;
                    double runLen = 0.0;
                    double runFlow = 0.0;
                    while (j < path.size() && path.get(j).diameterMm == dn) {
                        runLen += path.get(j).lengthM;
                        runFlow = Math.max(runFlow, path.get(j).flowTph);
                        j++;
                    }
                    double needDn = minDnFor(runFlow, runLen, ref);
                    if (needDn > dn) {
                        warnings.add(String.format(Locale.ROOT,
                                "серия из %d уч. Ду%d длиной %.0f м > предельной %d м — "
                                        + "повышение до Ду%d (§2.3)",
                                j - i, (int) dn, runLen, (int) ref.maxLenFor(dn), (int) needDn));
                        for (int k = i; k < j; k++) {
                            path.get(k).diameterMm = needDn;
                        }
                        changed = true;
                    }
                    i = j;
                }
            }
            // 2) монотонность: от точки подключения к месту присоединения ДУ
            //    не уменьшается (идём по пути от листа к корню)
            for (List<NewSegment> path : paths) {
                double prev = 0.0;
                for (int k = path.size() - 1; k >= 0; k--) {
                    NewSegment s = path.get(k);
                    if (s.diameterMm < prev) {
                        s.diameterMm = prev;
                        changed = true;
                    }
                    prev = s.diameterMm;
                }
            }
        }

        for (NewSegment s : segments) {
            reprice(s, ref);
        }
    }

    /** Обход дерева от участка к листьям: собрать пути (списки участков). */
    private static void collectPaths(NewSegment first, Map<String, NewSegment> incoming,
                                     Map<String, List<NewSegment>> outgoing,
                                     List<NewSegment> prefix, List<List<NewSegment>> out) {
        List<NewSegment> path = new ArrayList<>(prefix);
        path.add(first);
        List<NewSegment> next = first.endNodeId != null
                ? outgoing.getOrDefault(first.endNodeId, List.of()) : List.of();
        if (next.isEmpty()) {
            out.add(path);
            return;
        }
        for (NewSegment s : next) {
            collectPaths(s, incoming, outgoing, path, out);
        }
    }

    /** Сводка диаметров путей (диагностика). */
    static Map<String, Double> pathDiameters(List<NewSegment> path) {
        Map<String, Double> m = new LinkedHashMap<>();
        for (NewSegment s : path) {
            m.put(s.objectId, s.diameterMm);
        }
        return m;
    }
}
