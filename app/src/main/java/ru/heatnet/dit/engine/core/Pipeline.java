package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.Point;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Оркестрация расчёта: конвейер «файл вошёл — результат вышел».
 *
 * Соответствие техприложению ЛЦТ-2026:
 *   §2.1–2.2 — официальная входная схема (Loader);
 *   §3       — предельные длины непрерывных цепочек одного Ду (Hydraulics);
 *   §4       — диаметры/ставки по таблице 4.1 (RefData);
 *   §5.1     — ограничения: отступы 5/7/9 м по Ду, спецпроходы с Kспец,
 *              границы спецучастков, угол пересечения ≥45° (grid/postprocess);
 *   §6       — задание на глубину, режим ENGINE_DEPTH_MODE=1 (Depth);
 *   §7       — реконструкция существующей сети, частичная геометрия (Reconstruction);
 *   §8.2     — врезки (5 млн ₽) и камеры по шкале (Tapping/Costs);
 *   §8.3     — штраф 100 млн + 500 тыс.×G за неподключённый ОКС (Costs);
 *   §9       — ранжирование S = 0,3·C/25 млн + 0,7·L/100;
 *   §10      — выходной GeoJSON, строгий контракт (Exporter).
 *
 * Протокол 16.09.2026: п.7 (один шаг Ду), п.8 (реконструкция только
 * камер-врезок), п.9 (отводы ×1,5; отказ при дороговизне; диагностика
 * невалидной геометрии — Loader).
 */
public final class Pipeline {

    public static final String ENGINE_VERSION = "dit-sprint6.0-java";

    private static final GeometryFactory GF = new GeometryFactory();

    private Pipeline() {
    }

    // ------------------------------------------------------------------
    // Типы конвейера

    /** Нерподключённый ОКС (§2.9 + штраф §8.3). */
    public static class Unconnected {
        public final String buildingId;
        public final Point point;
        public final double flowTph;
        public final String reason;

        public Unconnected(String buildingId, Point point, double flowTph, String reason) {
            this.buildingId = buildingId;
            this.point = point;
            this.flowTph = flowTph;
            this.reason = reason;
        }
    }

    /** Новая камера (§8.2/§10.4). */
    public static class NewChamber {
        public final String objectId;
        public final String kind;            // tapping_on_segment | branching
        public final Point point;
        public final String segmentId;       // для камеры на участке
        public final double tapRequiredDn;
        public double diameterMm;            // пост-проход finalizeChambers
        public double costRub;

        public NewChamber(String objectId, String kind, Point point,
                          String segmentId, double tapRequiredDn) {
            this.objectId = objectId;
            this.kind = kind;
            this.point = point;
            this.segmentId = segmentId;
            this.tapRequiredDn = tapRequiredDn;
        }
    }

    /** Один вариант схемы подключения. */
    public static class Variant {
        public String label;
        public List<NewSegment> newSegments = new ArrayList<>();
        public List<NewChamber> newChambers = new ArrayList<>();
        public List<TechnicalNode> techNodes = new ArrayList<>();
        public List<Tapping.Tap> taps = new ArrayList<>();
        public Reconstruction.Result recon;
        public List<Unconnected> unconnected = new ArrayList<>();
        public List<String> warnings = new ArrayList<>();
        public Map<String, Double> costs = new LinkedHashMap<>();
        public Map<String, Double> lengths = new LinkedHashMap<>();
        public int rank;
        public double score;
        public boolean recommended;

        public List<String> unconnectedIds() {
            List<String> ids = new ArrayList<>();
            for (Unconnected u : unconnected) {
                ids.add(u.buildingId);
            }
            return ids;
        }
    }

    /** Стратегия построения варианта. */
    static final class Strategy {
        final String label;
        final boolean cluster;               // совместное подключение кластеров ОКС
        final double turnPenaltyMult;        // множитель штрафа за поворот
        final boolean avoidPrevious;         // обходить коридоры предыдущих вариантов

        Strategy(String label, boolean cluster, double turnPenaltyMult, boolean avoidPrevious) {
            this.label = label;
            this.cluster = cluster;
            this.turnPenaltyMult = turnPenaltyMult;
            this.avoidPrevious = avoidPrevious;
        }
    }

    private static final List<Strategy> STRATEGIES = List.of(
            new Strategy("Совместное подключение, базовый коридор", true, 1.0, false),
            new Strategy("Раздельное подключение", false, 1.0, false),
            new Strategy("Совместное подключение, альтернативный коридор", true, 4.0, true)
    );

    // ------------------------------------------------------------------
    // Точка входа

    /** Полный расчёт по конкурсному набору: до 3 вариантов + ранжирование §9. */
    public static Map<String, Object> runPipeline(Path inputPath, Path resultPath,
                                                  RefData refdata) {
        long started = System.currentTimeMillis();
        RefData ref = refdata != null ? refdata : new RefData();

        Model.ContestData data = Loader.loadContestGeojson(inputPath, ref);
        ExistingNetwork net = new ExistingNetwork(data.segments, data.chambers, data.sources);

        // Сетка ограничений общая для всех вариантов (временные блокировки
        // снимаются — состояние между вариантами чистое).
        ConstraintGrid grid = new ConstraintGrid(data.bounds, ref);
        grid.applyConstraints(data.constraints);

        List<Variant> variants = new ArrayList<>();
        Set<List<List<Object>>> seenSignatures = new HashSet<>();
        List<List<Coordinate>> prevPaths = new ArrayList<>();
        for (Strategy strategy : STRATEGIES) {
            List<Object[]> changed = new ArrayList<>();
            if (strategy.avoidPrevious && !prevPaths.isEmpty()) {
                changed = grid.penalizeCorridor(prevPaths,
                        ref.rule("corridor_avoid_radius_m"),
                        ref.rule("corridor_avoid_factor"));
            }
            Variant variant;
            try {
                variant = computeVariant(data, net, grid, ref, strategy);
            } finally {
                grid.restoreMult(changed);
            }
            List<List<Object>> signature = variantSignature(variant);
            if (!variants.isEmpty() && seenSignatures.contains(signature)) {
                continue; // содержательно не отличается — не плодим дубликаты
            }
            seenSignatures.add(signature);
            variants.add(variant);
            for (NewSegment s : variant.newSegments) {
                prevPaths.add(s.coords);
            }
            if (variants.size() >= 3) {
                break;
            }
        }

        Costs.rankVariants(variants, ref);

        Variant best = !variants.isEmpty() ? variants.get(0) : emptyVariant();
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("engine", ENGINE_VERSION);
        summary.put("job_elapsed_ms", System.currentTimeMillis() - started);
        summary.put("buildings_total", data.buildings.size());
        summary.put("buildings_connected", data.buildings.size() - best.unconnectedIds().size());
        summary.put("unconnected_ids", best.unconnectedIds());
        Map<String, Object> costsPub = new LinkedHashMap<>(best.costs);
        costsPub.put("total", best.costs.getOrDefault("calculated_cost", 0.0));
        summary.put("costs_rub", costsPub);
        summary.put("length_total_m", best.lengths.getOrDefault("length", 0.0));
        List<String> allWarnings = new ArrayList<>(data.warnings);
        allWarnings.addAll(best.warnings);
        summary.put("warnings", allWarnings);
        List<Map<String, Object>> variantsPub = new ArrayList<>();
        for (Variant v : variants) {
            variantsPub.add(variantPublic(v));
        }
        summary.put("variants", variantsPub);

        Exporter.writeResult(resultPath, data, variants, summary);
        return summary;
    }

    // ------------------------------------------------------------------
    // Один вариант

    private static Variant computeVariant(Model.ContestData data, ExistingNetwork net,
                                          ConstraintGrid grid, RefData ref,
                                          Strategy strategy) {
        int maxDirs = (int) ref.rule("max_new_directions_per_chamber");
        boolean depthMode = "1".equals(System.getenv("ENGINE_DEPTH_MODE"));

        List<List<Model.Building>> groups;
        if (strategy.cluster) {
            groups = Clustering.clusterBuildings(data.buildings, ref.rule("cluster_radius_m"));
        } else {
            groups = new ArrayList<>();
            for (Model.Building b : data.buildings.values()) {
                groups.add(List.of(b));
            }
        }

        Variant v = new Variant();
        v.label = strategy.label;
        Map<String, Integer> chamberLoad = new HashMap<>();
        Map<String, Integer> seq = new HashMap<>(Map.of(
                "seg", 0, "chamber", 0, "tech", 0, "tie", 0));

        for (List<Model.Building> group : groups) {
            for (List<Model.Building> pack : chunk(group, maxDirs)) {
                processPack(pack, net, grid, ref, strategy, chamberLoad, seq, v);
            }
        }

        // §3: предельные длины непрерывных цепочек одного Ду
        Hydraulics.enforceMaxLengthChains(v.newSegments, ref, v.warnings);

        // Раздел 7 + §8.2: реконструкция сети и камер
        v.recon = Reconstruction.computeReconstruction(net, v.taps, ref, v.warnings);

        // §8.2/§10.4: диаметр и стоимость новых камер — по итоговым примыканиям
        finalizeChambers(v, net, ref);

        // Раздел 6 (доп. задача): вертикальный профиль — только в режиме глубины
        if (depthMode) {
            List<NewSegment> deep = new ArrayList<>();
            for (NewSegment seg : v.newSegments) {
                deep.addAll(Depth.applyDepth(seg, ref, seq, v.techNodes, grid.specialZones, null));
            }
            v.newSegments = deep;
        }

        v.costs = Costs.variantCosts(v, ref);
        v.lengths = Costs.variantLengthsM(v);
        return v;
    }

    private static Variant emptyVariant() {
        Variant v = new Variant();
        v.recon = new Reconstruction.Result(new ArrayList<>(), new ArrayList<>());
        v.costs.put("calculated_cost", 0.0);
        v.lengths.put("length", 0.0);
        v.lengths.put("new_network_length", 0.0);
        v.lengths.put("reconstruction_length", 0.0);
        return v;
    }

    /** Сигнатура для отсева дубликатов: набор врезок + набор трасс. */
    private static List<List<Object>> variantSignature(Variant variant) {
        List<List<Object>> sig = new ArrayList<>();
        for (Tapping.Tap t : variant.taps) {
            sig.add(new ArrayList<>(List.of(t.kind,
                    (double) Math.rint(t.point.getX()), (double) Math.rint(t.point.getY()))));
        }
        for (NewSegment s : variant.newSegments) {
            sig.add(new ArrayList<>(List.of(s.role,
                    (double) Math.rint(s.lengthM), s.diameterMm)));
        }
        sig.sort((a, b) -> {
            int c = ((String) a.get(0)).compareTo((String) b.get(0));
            if (c != 0) {
                return c;
            }
            c = Double.compare((Double) a.get(1), (Double) b.get(1));
            if (c != 0) {
                return c;
            }
            return Double.compare((Double) a.get(2), (Double) b.get(2));
        });
        return sig;
    }

    /** Публичная сводка варианта (для служебного summary движка). */
    private static Map<String, Object> variantPublic(Variant v) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("rank", v.rank);
        out.put("label", v.label);
        out.put("score", v.score);
        out.put("is_recommended", v.recommended);
        out.put("status", v.unconnected.isEmpty() ? "done" : "partial");
        Map<String, Object> costs = new LinkedHashMap<>(v.costs);
        costs.put("total", v.costs.getOrDefault("calculated_cost", 0.0));
        out.put("costs_rub", costs);
        out.put("length_total_m", v.lengths.getOrDefault("length", 0.0));
        out.put("unconnected_ids", v.unconnectedIds());
        Map<String, Object> counts = new LinkedHashMap<>();
        counts.put("new_segments", v.newSegments.size());
        counts.put("new_chambers", v.newChambers.size());
        counts.put("technical_nodes", v.techNodes.size());
        counts.put("reconstruction_segments", v.recon.segments.size());
        counts.put("reconstruction_chambers", v.recon.chambers.size());
        out.put("counts", counts);
        return out;
    }

    // ------------------------------------------------------------------
    // Пачка ОКС внутри варианта

    private static void processPack(List<Model.Building> pack0, ExistingNetwork net,
                                    ConstraintGrid grid, RefData ref, Strategy strategy,
                                    Map<String, Integer> chamberLoad, Map<String, Integer> seq,
                                    Variant v) {
        // §2.9: ОКС с точкой подключения в запретной зоне — сразу в unconnected
        List<Model.Building> pack = new ArrayList<>();
        for (Model.Building b : pack0) {
            double dnB = RefData.num(ref.diameterForFlow(b.flowTph).get("dn_mm"));
            String zoneId = grid.forbiddenReason(b.anchor(), dnB);
            if (zoneId != null) {
                v.unconnected.add(new Unconnected(b.objectId, b.anchor(), b.flowTph,
                        "точка подключения в запретной зоне " + zoneId));
            } else {
                pack.add(b);
            }
        }
        if (pack.isEmpty()) {
            return;
        }
        double flowTotal = 0.0;
        double cx = 0.0, cy = 0.0;
        for (Model.Building b : pack) {
            flowTotal += b.flowTph;
            cx += b.anchor().getX();
            cy += b.anchor().getY();
        }
        cx /= pack.size();
        cy /= pack.size();
        Point clusterCenter = GF.createPoint(new Coordinate(cx, cy));

        Tapping.Tap tap = Tapping.chooseTapStrict(clusterCenter, flowTotal, net, ref, chamberLoad);
        if (tap == null) {
            for (Model.Building b : pack) {
                v.unconnected.add(new Unconnected(b.objectId, b.anchor(), b.flowTph,
                        "нет доступных точек врезки в радиусе поиска"));
            }
            return;
        }
        seq.merge("tie", 1, Integer::sum);
        tap.nodeId = "tie-" + seq.get("tie");
        v.taps.add(tap);
        // Контрольные точки для отката (маршрут не найден / нерентабельно)
        int tapsBefore = v.taps.size() - 1;
        int chambersBefore = v.newChambers.size();
        int techBefore = v.techNodes.size();
        String loadChamberId = null;

        String tapNode;
        if ("existing_chamber".equals(tap.kind)) {
            chamberLoad.merge(tap.chamberId, 1, Integer::sum);
            loadChamberId = tap.chamberId;
            tapNode = tap.chamberId;
        } else {
            seq.merge("chamber", 1, Integer::sum);
            tapNode = "ch-" + seq.get("chamber");
            v.newChambers.add(new NewChamber(tapNode, "tapping_on_segment",
                    tap.point, tap.segmentId, tap.requiredDn));
        }

        // Целевые контуры ОКС блокируем, чтобы трасса их не пересекала
        List<int[]> blockedCells = new ArrayList<>();
        int segsBefore = v.newSegments.size();
        for (Model.Building b : pack) {
            String gt = b.geom.getGeometryType();
            if ("Polygon".equals(gt) || "MultiPolygon".equals(gt)) {
                blockedCells.addAll(grid.blockPolygon(b.geom));
            }
        }

        final String loadChamberIdF = loadChamberId;
        Runnable rollback = () -> {
            sublistClear(v.newSegments, segsBefore);
            sublistClear(v.taps, tapsBefore);
            sublistClear(v.newChambers, chambersBefore);
            sublistClear(v.techNodes, techBefore);
            if (loadChamberIdF != null) {
                chamberLoad.merge(loadChamberIdF, 0,
                        (cur, z) -> Math.max(0, cur - 1));
            }
        };

        try {
            double turnPenalty = ref.rule("turn_penalty_m") * strategy.turnPenaltyMult;
            double packDn = RefData.num(ref.diameterForFlow(flowTotal).get("dn_mm"));
            if (pack.size() == 1) {
                Model.Building b = pack.get(0);
                List<Coordinate> coords = route(grid, tap.point, b.anchor(), turnPenalty, packDn);
                if (coords == null) {
                    v.unconnected.add(new Unconnected(b.objectId, b.anchor(), b.flowTph,
                            "A* не нашёл маршрут до точки подключения"));
                    rollback.run();
                    return;
                }
                appendSegment(coords, flowTotal, "branch", tapNode, endNode(b),
                        grid, ref, seq, v, b.objectId);
            } else {
                Point branchPt = gridSnapFree(grid, clusterCenter);
                List<Coordinate> trunk = route(grid, tap.point, branchPt, turnPenalty, packDn);
                if (trunk == null) {
                    for (Model.Building b : pack) {
                        v.unconnected.add(new Unconnected(b.objectId, b.anchor(), b.flowTph,
                                "A* не нашёл маршрут ствола"));
                    }
                    rollback.run();
                    return;
                }
                seq.merge("chamber", 1, Integer::sum);
                String branchNode = "ch-" + seq.get("chamber");
                v.newChambers.add(new NewChamber(branchNode, "branching",
                        branchPt, null, 0.0));
                StringBuilder owner = new StringBuilder();
                for (int i = 0; i < pack.size(); i++) {
                    if (i > 0) {
                        owner.append("+");
                    }
                    owner.append(pack.get(i).objectId);
                }
                appendSegment(trunk, flowTotal, "trunk", tapNode, branchNode,
                        grid, ref, seq, v, owner.toString());
                for (Model.Building b : pack) {
                    double dnB = RefData.num(ref.diameterForFlow(b.flowTph).get("dn_mm"));
                    List<Coordinate> coords = route(grid, branchPt, b.anchor(), turnPenalty, dnB);
                    if (coords == null) {
                        v.unconnected.add(new Unconnected(b.objectId, b.anchor(), b.flowTph,
                                "A* не нашёл маршрут ветви"));
                        continue;
                    }
                    appendSegment(coords, b.flowTph, "branch", branchNode, endNode(b),
                            grid, ref, seq, v, b.objectId);
                }
            }
            assertTree(v.newSegments.subList(segsBefore, v.newSegments.size()), v.warnings);

            // Протокол 16.09.2026 п.9: если прямые затраты на подключение пачки
            // превышают суммарный штраф §8.3 — отказ от подключения (откат).
            double packCost = packDirectCost(v.newSegments.subList(segsBefore, v.newSegments.size()),
                    v.newChambers.subList(chambersBefore, v.newChambers.size()),
                    v.taps.subList(tapsBefore, v.taps.size()), net, ref);
            double penalty = 0.0;
            for (Model.Building b : pack) {
                penalty += ref.unconnectedPenalty(b.flowTph);
            }
            if (packCost > penalty) {
                v.warnings.add(String.format(Locale.ROOT,
                        "пачка %s: подключение %.1f млн ₽ дороже штрафа %.1f млн ₽ — отказ (протокол п.9)",
                        packIds(pack), packCost / 1e6, penalty / 1e6));
                for (Model.Building b : pack) {
                    v.unconnected.add(new Unconnected(b.objectId, b.anchor(), b.flowTph,
                            "подключение нерентабельно: трасса дороже штрафа §8.3"));
                }
                rollback.run();
            }
        } finally {
            grid.unblock(blockedCells);
        }
    }

    private static String packIds(List<Model.Building> pack) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < pack.size(); i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(pack.get(i).objectId);
        }
        return sb.append("]").toString();
    }

    private static void sublistClear(List<?> list, int from) {
        if (from < list.size()) {
            list.subList(from, list.size()).clear();
        }
    }

    /**
     * Прямые затраты на подключение пачки ОКС (протокол п.9).
     * Сравниваются со штрафом §8.3: новые участки + врезки + новые камеры +
     * реконструкция камеры-врезки (п.8). Реконструкция существующих линейных
     * участков — общая инфраструктура варианта, в сравнение не входит.
     */
    static double packDirectCost(List<NewSegment> packSegments, List<NewChamber> packChambers,
                                 List<Tapping.Tap> packTaps, ExistingNetwork net, RefData ref) {
        double total = 0.0;
        for (NewSegment s : packSegments) {
            total += s.costRub;
        }
        for (Tapping.Tap t : packTaps) {
            total += t.tapCostRub;
        }
        for (NewChamber ch : packChambers) {
            List<Double> dns = new ArrayList<>();
            for (NewSegment s : packSegments) {
                if (ch.objectId.equals(s.startNodeId) || ch.objectId.equals(s.endNodeId)) {
                    dns.add(s.diameterMm);
                }
            }
            if (ch.tapRequiredDn > 0) {
                dns.add(ch.tapRequiredDn);
            }
            if (ch.segmentId != null && net != null) {
                Model.Segment seg0 = net.segments.get(ch.segmentId);
                if (seg0 != null) {
                    dns.add(seg0.diameterOrZero());
                }
            }
            double maxDn = !dns.isEmpty()
                    ? dns.stream().mapToDouble(Double::doubleValue).max().orElse(0.0)
                    : RefData.num(ref.diameters.get(0).get("dn_mm"));
            total += ref.chamberCost(maxDn);
        }
        for (Tapping.Tap t : packTaps) {
            if ("existing_chamber".equals(t.kind) && t.chamberId != null && net != null) {
                Model.Chamber ch = net.chambers.get(t.chamberId);
                double existingDn = ch != null && ch.diameterMm != null ? ch.diameterMm : 0.0;
                if (t.requiredDn > existingDn) {
                    total += ref.chamberCost(t.requiredDn);
                }
            }
        }
        return total;
    }

    /** Конечный узел ветви: точка подключения ОКС (§10.1). */
    private static String endNode(Model.Building b) {
        return b.connectionPointId != null ? b.connectionPointId : "oks-" + b.objectId;
    }

    /** Постобработка, границы спецучастков (таблица 5.1), диаметр, узлы. */
    @SuppressWarnings("unchecked")
    private static void appendSegment(List<Coordinate> coords, double flow, String role,
                                      String startNodeId, String endNodeId,
                                      ConstraintGrid grid, RefData ref, Map<String, Integer> seq,
                                      Variant v, String ownerId) {
        List<Coordinate> pts = Postprocess.simplifyPath(coords, grid.cell * 0.75);
        if (!Postprocess.checkSelfIntersection(pts)) {
            v.warnings.add(ownerId + ": самопересечение трассы после упрощения — оставлено как есть");
        }

        LineString line = GF.createLineString(pts.toArray(new Coordinate[0]));
        double length = line.getLength();
        double minSpecial = ref.rule("special_passage_min_len_m");
        List<ConstraintGrid.SpecialInterval> intervals = new ArrayList<>();
        for (ConstraintGrid.SpecialInterval iv : grid.specialIntervals(line)) {
            if (iv.b - iv.a >= minSpecial) {
                intervals.add(iv);
            }
        }

        // точки деления: границы спецучастков
        Set<Double> cutsSet = new HashSet<>();
        cutsSet.add(0.0);
        cutsSet.add(length);
        for (ConstraintGrid.SpecialInterval iv : intervals) {
            cutsSet.add(iv.a);
            cutsSet.add(iv.b);
        }
        List<Double> cuts = new ArrayList<>(cutsSet);
        cuts.sort(Double::compareTo);

        List<double[]> parts = new ArrayList<>();
        for (int i = 0; i < cuts.size() - 1; i++) {
            if (cuts.get(i + 1) - cuts.get(i) > 0.01) {
                parts.add(new double[]{cuts.get(i), cuts.get(i + 1)});
            }
        }

        // параметры отводов (протокол п.9) — из справочника
        double[] stdAngles = {45.0, 90.0};
        Object stdCfg = ref.rules.get("bend_standard_angles_deg");
        if (stdCfg instanceof List) {
            List<Object> l = (List<Object>) stdCfg;
            stdAngles = new double[l.size()];
            for (int i = 0; i < l.size(); i++) {
                stdAngles[i] = RefData.num(l.get(i));
            }
        }
        double bendTol = RefData.num(ref.rules.getOrDefault("bend_angle_tolerance_deg", 5.0));
        double bendFactorCfg = RefData.num(ref.rules.getOrDefault("bend_nonstandard_cost_factor", 1.5));

        String curStart = startNodeId;
        for (int idx = 0; idx < parts.size(); idx++) {
            double a = parts.get(idx)[0], b = parts.get(idx)[1];
            // method(a, b)
            double mid = (a + b) / 2.0;
            String method = "base";
            Double kSpecial = null;
            for (ConstraintGrid.SpecialInterval iv : intervals) {
                if (iv.a <= mid && mid <= iv.b) {
                    method = "special";
                    kSpecial = iv.k;
                    break;
                }
            }
            LineString piece = Hydraulics.subline(line, a, b);
            boolean isLast = idx == parts.size() - 1;
            String endNode;
            if (isLast) {
                endNode = endNodeId;
            } else {
                seq.merge("tech", 1, Integer::sum);
                endNode = "node-" + seq.get("tech");
                org.locationtech.jts.linearref.LengthIndexedLine lil =
                        new org.locationtech.jts.linearref.LengthIndexedLine(line);
                Coordinate pc = lil.extractPoint(b);
                v.techNodes.add(new TechnicalNode(endNode, GF.createPoint(pc),
                        "граница специального участка (таблица 5.1)"));
            }
            seq.merge("seg", 1, Integer::sum);
            NewSegment seg = new NewSegment(
                    "seg-" + seq.get("seg"),
                    new ArrayList<>(List.of(piece.getCoordinates())),
                    flow, role, method, kSpecial, curStart, endNode);
            // Протокол п.9: нештатный угол отвода (не 45°/90°) → ×1,5 к стоимости
            if (Hydraulics.nonstandardBend(seg.coords, stdAngles, bendTol)) {
                seg.bendFactor = bendFactorCfg;
                v.warnings.add(String.format(Locale.ROOT,
                        "%s: %s — нештатный угол отвода, ×%s к стоимости (протокол п.9)",
                        ownerId, seg.objectId, formatG(bendFactorCfg)));
            }
            Hydraulics.sizeSegment(seg, ref);
            v.newSegments.add(seg);
            curStart = endNode;
        }

        Postprocess.checkCrossingAngles(line, grid.specialZones, v.warnings, ownerId);
    }

    private static String formatG(double x) {
        if (x == Math.floor(x) && !Double.isInfinite(x)) {
            return String.format(Locale.ROOT, "%d", (long) x);
        }
        return String.format(Locale.ROOT, "%s", x);
    }

    /** A* с временными отступами запретных зон под диаметр трассы (§5.1). */
    private static List<Coordinate> route(ConstraintGrid grid, Point a, Point b,
                                          Double turnPenaltyM, double dnMm) {
        List<int[]> blocked = grid.clearanceBlock(dnMm);
        try {
            return grid.astar(a.getX(), a.getY(), b.getX(), b.getY(), turnPenaltyM);
        } finally {
            grid.clearanceUnblock(blocked);
        }
    }

    /** Ближайшая свободная ячейка к точке — как Point. */
    private static Point gridSnapFree(ConstraintGrid grid, Point pt) {
        int[] cell = grid.nearestFree(grid.toCell(pt.getX(), pt.getY()));
        if (cell == null) {
            return pt;
        }
        double[] c = grid.cellCenter(cell[0], cell[1]);
        return GF.createPoint(new Coordinate(c[0], c[1]));
    }

    /** §8.2/§10.4: диаметр новой камеры — максимум Ду примыкающих участков. */
    private static void finalizeChambers(Variant v, ExistingNetwork net, RefData ref) {
        // требуемый Ду существующих участков после реконструкции
        Map<String, Double> reconRequired = new HashMap<>();
        for (Reconstruction.ReconSegment rs : v.recon.segments) {
            reconRequired.merge(rs.existingObjectId, rs.requiredDn, Math::max);
        }

        for (NewChamber ch : v.newChambers) {
            List<Double> dns = new ArrayList<>();
            for (NewSegment s : v.newSegments) {
                if (ch.objectId.equals(s.startNodeId) || ch.objectId.equals(s.endNodeId)) {
                    dns.add(s.diameterMm);
                }
            }
            if (ch.tapRequiredDn > 0) {
                dns.add(ch.tapRequiredDn);
            }
            if (ch.segmentId != null) {
                Model.Segment seg0 = net.segments.get(ch.segmentId);
                if (seg0 != null) {
                    dns.add(reconRequired.getOrDefault(ch.segmentId, seg0.diameterOrZero()));
                }
            }
            double maxDn = !dns.isEmpty()
                    ? dns.stream().mapToDouble(Double::doubleValue).max().orElse(0.0)
                    : RefData.num(ref.diameters.get(0).get("dn_mm"));
            ch.diameterMm = maxDn;
            ch.costRub = ref.chamberCost(maxDn);
        }
    }

    private static List<List<Model.Building>> chunk(List<Model.Building> items, int n) {
        List<List<Model.Building>> out = new ArrayList<>();
        for (int i = 0; i < items.size(); i += n) {
            out.add(items.subList(i, Math.min(i + n, items.size())));
        }
        return out;
    }

    /**
     * Проверка «один путь до ОКС»: компоненты новых сегментов — деревья.
     * Для компоненты из E рёбер и V вершин должно выполняться E = V - 1.
     */
    private static void assertTree(List<NewSegment> segments, List<String> warnings) {
        Map<String, String> parent = new HashMap<>();
        for (NewSegment seg : segments) {
            if (seg.startNodeId == null || seg.endNodeId == null) {
                continue;
            }
            String ra = findRoot(parent, seg.startNodeId);
            String rb = findRoot(parent, seg.endNodeId);
            if (ra.equals(rb)) {
                warnings.add(seg.objectId + ": обнаружено кольцо в новой сети");
            } else {
                parent.put(ra, rb);
            }
        }
    }

    private static String findRoot(Map<String, String> parent, String x) {
        parent.putIfAbsent(x, x);
        while (!parent.get(x).equals(x)) {
            parent.put(x, parent.get(parent.get(x)));
            x = parent.get(x);
        }
        return x;
    }
}
