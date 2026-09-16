package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.linearref.LengthIndexedLine;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Гидравлика новой сети: расходы, диаметры, предельные длины (§3, §4).
 *
 *   - расходы суммируются на общих участках (ствол несёт сумму ветвей);
 *   - диаметр — минимальный Ду по таблице 4.1 (пропускная способность);
 *   - предельная длина (таблица 4.1) — максимум НЕПРЕРЫВНОЙ части одного
 *     диаметра (раздел 3); по протоколу 16.09.2026 (п.7) повышение —
 *     не более ОДНОГО номенклатурного шага.
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

    /**
     * Протокол 16.09.2026 п.9: есть ли на полилинии отвод с нештатным углом.
     * Штатные углы отвода — 45° и 90° (±tolDeg); отклонение ≤ tolDeg
     * считается прямолинейным продолжением. Иной угол — нештатный отвод.
     */
    public static boolean nonstandardBend(List<Coordinate> coords,
                                          double[] standardDeg, double tolDeg) {
        for (int i = 1; i < coords.size() - 1; i++) {
            Coordinate a = coords.get(i - 1), b = coords.get(i), c = coords.get(i + 1);
            double v1x = b.x - a.x, v1y = b.y - a.y;
            double v2x = c.x - b.x, v2y = c.y - b.y;
            double n1 = Math.hypot(v1x, v1y), n2 = Math.hypot(v2x, v2y);
            if (n1 < 1e-9 || n2 < 1e-9) {
                continue;
            }
            double cosA = Math.max(-1.0, Math.min(1.0, (v1x * v2x + v1y * v2y) / (n1 * n2)));
            double dev = Math.toDegrees(Math.acos(cosA));
            if (dev <= tolDeg) {
                continue; // прямолинейно
            }
            boolean standard = false;
            for (double std : standardDeg) {
                if (Math.abs(dev - std) <= tolDeg) {
                    standard = true;
                    break;
                }
            }
            if (!standard) {
                return true;
            }
        }
        return false;
    }

    /** Пересчитать ставку и стоимость участка (после смены Ду/коэффициентов). */
    public static void reprice(NewSegment seg, RefData refdata) {
        double tariff = refdata.layTariff(seg.diameterMm);
        if ("special".equals(seg.method)) {
            tariff *= seg.kSpecial != null ? seg.kSpecial : 1.5;
        }
        tariff *= seg.bendFactor;
        seg.tariffRubM = tariff;
        seg.costRub = seg.lengthM * tariff;
    }

    /**
     * Подобрать диаметр (расход + предельная длина) и стоимость участка.
     * Превышение предельной длины — повышение на ОДИН шаг (п.7), затем warning.
     */
    public static void sizeSegment(NewSegment seg, RefData refdata) {
        Map<String, Object> d = refdata.diameterForFlow(seg.flowTph);
        if (RefData.num(d.get("max_flow_tph")) < seg.flowTph) {
            seg.warnings.add(String.format(Locale.ROOT,
                    "расход %.1f т/ч превышает справочный максимум %.1f т/ч",
                    seg.flowTph, RefData.num(d.get("max_flow_tph"))));
        }
        double dn = RefData.num(d.get("dn_mm"));
        double maxDn = RefData.num(refdata.diameters.get(refdata.diameters.size() - 1).get("dn_mm"));
        // Протокол 16.09.2026 п.7: повышение Ду по предельной длине — не более
        // ОДНОГО номенклатурного шага (большее в датасете не встречается)
        if (seg.lengthM > refdata.maxLenFor(dn) && dn < maxDn) {
            dn = RefData.num(refdata.nextDiameter(dn).get("dn_mm"));
        }
        if (seg.lengthM > refdata.maxLenFor(dn)) {
            seg.warnings.add(String.format(Locale.ROOT,
                    "длина %.0f м превышает предельную %.0f м для Ду%d — допускается "
                            + "один шаг повышения (протокол п.7)",
                    seg.lengthM, refdata.maxLenFor(dn), (int) dn));
        }
        seg.diameterMm = dn;
        reprice(seg, refdata);
    }

    /**
     * Раздел 3: предельная длина НЕПРЕРЫВНОЙ цепочки одного диаметра.
     * Участки одного Ду, стыкующиеся в узлах степени 2, объединяются
     * в цепочки; при превышении — повышение на ОДИН шаг (протокол п.7).
     */
    public static void enforceMaxLengthChains(List<NewSegment> segments, RefData refdata,
                                              List<String> warnings) {
        double maxDn = RefData.num(refdata.diameters.get(refdata.diameters.size() - 1).get("dn_mm"));
        // узлы -> инцидентные участки (по id концов)
        Map<String, List<Integer>> incidence = new HashMap<>();
        for (int i = 0; i < segments.size(); i++) {
            NewSegment s = segments.get(i);
            if (s.startNodeId != null) {
                incidence.computeIfAbsent(s.startNodeId, k -> new ArrayList<>()).add(i);
            }
            if (s.endNodeId != null) {
                incidence.computeIfAbsent(s.endNodeId, k -> new ArrayList<>()).add(i);
            }
        }

        // union-find по участкам: стык «тот же Ду + узел степени 2»
        int[] parent = new int[segments.size()];
        for (int i = 0; i < segments.size(); i++) {
            parent[i] = i;
        }
        for (List<Integer> idxs : incidence.values()) {
            if (idxs.size() != 2) {
                continue; // ветвление/конец — цепочка прерывается
            }
            int a = idxs.get(0), b = idxs.get(1);
            if (segments.get(a).diameterMm == segments.get(b).diameterMm) {
                union(parent, a, b);
            }
        }

        Map<Integer, List<Integer>> chains = new HashMap<>();
        for (int i = 0; i < segments.size(); i++) {
            chains.computeIfAbsent(find(parent, i), k -> new ArrayList<>()).add(i);
        }

        for (List<Integer> idxs : chains.values()) {
            double dn = segments.get(idxs.get(0)).diameterMm;
            double total = 0.0;
            for (int i : idxs) {
                total += segments.get(i).lengthM;
            }
            double maxLen = refdata.maxLenFor(dn);
            if (total > maxLen + 1e-6 && dn < maxDn) {
                double newDn = RefData.num(refdata.nextDiameter(dn).get("dn_mm"));
                warnings.add(String.format(Locale.ROOT,
                        "цепочка из %d уч. Ду%d длиной %.0f м > предельной %d м — "
                                + "повышение до Ду%d (раздел 3)",
                        idxs.size(), (int) dn, total, (int) maxLen, (int) newDn));
                for (int i : idxs) {
                    NewSegment s = segments.get(i);
                    s.diameterMm = newDn;
                    reprice(s, refdata);
                }
                if (total > refdata.maxLenFor(newDn) + 1e-6) {
                    warnings.add(String.format(Locale.ROOT,
                            "цепочка Ду%d длиной %.0f м всё ещё > предельной %d м — "
                                    + "допускается один шаг повышения (протокол п.7)",
                            (int) newDn, total, (int) refdata.maxLenFor(newDn)));
                }
            }
        }
    }

    private static int find(int[] parent, int x) {
        while (parent[x] != x) {
            parent[x] = parent[parent[x]];
            x = parent[x];
        }
        return x;
    }

    private static void union(int[] parent, int a, int b) {
        int ra = find(parent, a), rb = find(parent, b);
        if (ra != rb) {
            parent[ra] = rb;
        }
    }
}
