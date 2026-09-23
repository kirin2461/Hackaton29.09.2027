package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.Point;
import org.locationtech.jts.geom.prep.PreparedGeometry;
import org.locationtech.jts.geom.prep.PreparedGeometryFactory;

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
 * Соответствие актуальному техприложению ЛЦТ-2026:
 *   §1   — входная схема: source / heat_network / heat_chamber /
 *          oks_connection_point (flow_tph на точке) / restriction (Loader);
 *   §2.1 — топология: дерево без колец, камеры ≤4 примыканий (подсчёт
 *          геометрический), повороты до 90° без удорожания;
 *   §2.2 — подход к целевому полигону ОКС: один финальный прямой участок,
 *          отступ к своему полигону не применяется;
 *   §2.3 — ДУ: минимальный по расходу и предельной длине каждого пути,
 *          монотонность к месту присоединения (Hydraulics);
 *   §2.4 — присоединение: камера ≤10 м со свободными примыканиями, иначе
 *          новая камера на участке; реконструкция ОТМЕНЕНА (разъяснение №14);
 *   §2.5 — неподключение только при отсутствии допустимого маршрута
 *          (разъяснение №15: отказ по рентабельности запрещён);
 *   §3.2 — камеры по шкале ДУ, врезка в существующую камеру 5 млн ₽
 *          за каждый новый участок (Costs);
 *   §4   — ограничения таблицы 2: отступы 5/7/9 м по ДУ (oks), 1,0 м
 *          (park/social_area/prohibited_site/water/railway), спецпроходы
 *          с Kспец, пересечение существующей сети без врезки K=1,05;
 *   §5   — дополнительный режим с глубиной (Depth, ENGINE_DEPTH_MODE=1);
 *   §6   — стоимость варианта и S = 0,7·C/25 млн + 0,3·L/100 (Costs);
 *   §7   — выходной GeoJSON: heat_network / heat_chamber / technical_node /
 *          variant_summary (Exporter).
 */
public final class Pipeline {

    public static final String ENGINE_VERSION = "dit-lct2026.2-java";

    private static final GeometryFactory GF = new GeometryFactory();

    private Pipeline() {
    }

    // ------------------------------------------------------------------
    // Типы конвейера

    /** Неподключённая точка ОКС (§2.5 + штраф §6). */
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

    /** Новая камера (§2.4/§3.2). */
    public static class NewChamber {
        public final String objectId;
        public final String kind;            // tapping_on_segment | branching
        public final Point point;
        public final String segmentId;       // для камеры на существующем участке
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
        final boolean cluster;               // совместное подключение кластеров точек
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

    /** Полный расчёт по конкурсному набору: до 3 вариантов + ранжирование §6. */
    public static Map<String, Object> runPipeline(Path inputPath, Path resultPath,
                                                  RefData refdata) {
        long started = System.currentTimeMillis();
        RefData ref = refdata != null ? refdata : new RefData();

        Model.ContestData data = Loader.loadContestGeojson(inputPath, ref);
        ExistingNetwork net = new ExistingNetwork(data.segments, data.chambers, data.sources);

        // Таблица 2 + разъяснение №10: пересечение СУЩЕСТВУЮЩЕЙ сети без врезки —
        // специальный проход с Kспец = 1,05. Зоны генерируются из геометрии
        // входных heat_network (отдельных restriction-объектов нет в схеме §1).
        List<Model.ConstraintZone> allZones = new ArrayList<>(data.constraints);
        for (Model.Segment seg : data.segments.values()) {
            Map<String, Object> params = new LinkedHashMap<>();
            if (seg.diameterMm != null) {
                params.put("diameter", seg.diameterMm);
            }
            allZones.add(new Model.ConstraintZone(
                    seg.objectId, seg.geom, "special_passage", params, "heat_network"));
        }
        Map<String, Model.ConstraintZone> zoneById = new LinkedHashMap<>();
        for (Model.ConstraintZone z : data.constraints) {
            zoneById.put(z.objectId, z);
        }

        // Сетка ограничений общая для всех вариантов (временные блокировки
        // снимаются — состояние между вариантами чистое).
        ConstraintGrid grid = new ConstraintGrid(data.bounds, ref);
        grid.applyConstraints(allZones);

        List<Variant> variants = new ArrayList<>();
        Set<List<List<Object>>> seenSignatures = new HashSet<>();
        List<List<Coordinate>> prevPaths = new ArrayList<>();
        for (Strategy strategy : STRATEGIES) {
            grid.clearTapExclusions();
            List<Object[]> changed = new ArrayList<>();
            if (strategy.avoidPrevious && !prevPaths.isEmpty()) {
                changed = grid.penalizeCorridor(prevPaths,
                        ref.rule("corridor_avoid_radius_m"),
                        ref.rule("corridor_avoid_factor"));
            }
            Variant variant;
            try {
                variant = computeVariant(data, net, grid, ref, strategy, zoneById);
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

        Variant best = !variants.isEmpty() ? variants.get(0) : emptyVariant(ref);
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("engine", ENGINE_VERSION);
        summary.put("job_elapsed_ms", System.currentTimeMillis() - started);
        summary.put("buildings_total", data.targets.size());
        summary.put("buildings_connected", data.targets.size() - best.unconnectedIds().size());
        summary.put("unconnected_ids", best.unconnectedIds());
        Map<String, Object> costsPub = new LinkedHashMap<>(best.costs);
        costsPub.put("total", best.costs.getOrDefault("calculated_cost", 0.0));
        summary.put("costs_rub", costsPub);
        summary.put("length_total_m", best.lengths.getOrDefault("new_network_length", 0.0));
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
                                          Strategy strategy,
                                          Map<String, Model.ConstraintZone> zoneById) {
        int maxDirs = (int) ref.rule("max_new_directions_per_chamber");
        boolean depthMode = "1".equals(System.getenv("ENGINE_DEPTH_MODE"));

        List<List<Model.ConnectionTarget>> groups;
        if (strategy.cluster) {
            groups = Clustering.clusterTargets(data.targets, ref.rule("cluster_radius_m"));
        } else {
            groups = new ArrayList<>();
            for (Model.ConnectionTarget t : data.targets.values()) {
                groups.add(List.of(t));
            }
        }

        Variant v = new Variant();
        v.label = strategy.label;
        Map<String, Integer> chamberLoad = new HashMap<>();
        Map<String, Integer> seq = new HashMap<>(Map.of("seg", 0, "chamber", 0, "tech", 0));

        for (List<Model.ConnectionTarget> group : groups) {
            for (List<Model.ConnectionTarget> pack : chunk(group, maxDirs)) {
                processPack(pack, net, grid, ref, strategy, chamberLoad, seq, zoneById, v);
            }
        }

        // §2.3: ДУ по расходу и предельной длине каждого пути + монотонность
        Hydraulics.enforceDiameterRules(v.newSegments, ref, v.warnings);

        // §3.2: диаметр и стоимость новых камер — по итоговым примыканиям
        finalizeChambers(v, net, ref);

        // §5 (дополнительный режим): вертикальный профиль — только в режиме глубины
        if (depthMode) {
            List<NewSegment> deep = new ArrayList<>();
            for (NewSegment seg : v.newSegments) {
                deep.addAll(Depth.applyDepth(seg, ref, seq, v.techNodes, grid.specialZones, null, grid));
            }
            v.newSegments = deep;
        }

        v.costs = Costs.variantCosts(v, net, ref);
        v.lengths = Costs.variantLengthsM(v);
        return v;
    }

    private static Variant emptyVariant(RefData ref) {
        Variant v = new Variant();
        v.costs.put("construction_cost", 0.0);
        v.costs.put("chamber_construction_cost", 0.0);
        v.costs.put("existing_chamber_tie_in_count", 0.0);
        v.costs.put("existing_chamber_tie_in_cost", 0.0);
        v.costs.put("unconnected_penalty", 0.0);
        v.costs.put("calculated_cost", 0.0);
        v.lengths.put("new_network_length", 0.0);
        v.lengths.put("length", 0.0);
        return v;
    }

    /** Сигнатура для отсева дубликатов: набор присоединений + набор трасс. */
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
        out.put("length_total_m", v.lengths.getOrDefault("new_network_length", 0.0));
        out.put("unconnected_ids", v.unconnectedIds());
        Map<String, Object> counts = new LinkedHashMap<>();
        counts.put("new_segments", v.newSegments.size());
        counts.put("new_chambers", v.newChambers.size());
        counts.put("technical_nodes", v.techNodes.size());
        out.put("counts", counts);
        return out;
    }

    // ------------------------------------------------------------------
    // Пачка точек подключения внутри варианта

    private static void processPack(List<Model.ConnectionTarget> pack0, ExistingNetwork net,
                                    ConstraintGrid grid, RefData ref, Strategy strategy,
                                    Map<String, Integer> chamberLoad, Map<String, Integer> seq,
                                    Map<String, Model.ConstraintZone> zoneById, Variant v) {
        // Точка подключения в ЧУЖОЙ запретной зоне — допустимого маршрута нет (§2.5).
        // Свой полигон ОКС (§2.2) при проверке пропускается.
        List<Model.ConnectionTarget> pack = new ArrayList<>();
        for (Model.ConnectionTarget t : pack0) {
            double dnT = RefData.num(ref.diameterForFlow(t.flowTph).get("dn_mm"));
            Set<String> skip = t.oksZoneId != null ? Set.of(t.oksZoneId) : Set.of();
            String zoneId = grid.forbiddenReason(t.point, dnT, skip);
            if (zoneId != null) {
                v.unconnected.add(new Unconnected(t.objectId, t.point, t.flowTph,
                        "точка подключения в запретной зоне " + zoneId));
            } else {
                pack.add(t);
            }
        }
        if (pack.isEmpty()) {
            return;
        }
        double flowTotal = 0.0;
        double cx = 0.0, cy = 0.0;
        for (Model.ConnectionTarget t : pack) {
            flowTotal += t.flowTph;
            cx += t.anchor().getX();
            cy += t.anchor().getY();
        }
        cx /= pack.size();
        cy /= pack.size();
        Point clusterCenter = GF.createPoint(new Coordinate(cx, cy));

        Tapping.Tap tap = Tapping.chooseTapStrict(clusterCenter, flowTotal, net, ref, chamberLoad);
        if (tap == null) {
            for (Model.ConnectionTarget t : pack) {
                v.unconnected.add(new Unconnected(t.objectId, t.anchor(), t.flowTph,
                        "нет доступных точек присоединения в радиусе поиска"));
            }
            return;
        }
        v.taps.add(tap);
        // Разъяснение №10: место присоединения — не пересечение, спецпроход
        // вокруг него не оформляется.
        for (Map.Entry<String, Double> e : net.segmentsNear(tap.point, 5.0)) {
            grid.addTapExclusion(e.getKey(), tap.point);
        }
        // Контрольные точки для отката (маршрут не найден)
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

        int segsBefore = v.newSegments.size();
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

        double turnPenalty = ref.rule("turn_penalty_m") * strategy.turnPenaltyMult;
        double packDn = RefData.num(ref.diameterForFlow(flowTotal).get("dn_mm"));
        if (pack.size() == 1) {
            Model.ConnectionTarget t = pack.get(0);
            List<Coordinate> coords = routeToTarget(grid, tap.point, t, turnPenalty, packDn, zoneById, v);
            if (coords == null) {
                v.unconnected.add(new Unconnected(t.objectId, t.anchor(), t.flowTph,
                        "A* не нашёл маршрут до точки подключения"));
                rollback.run();
                return;
            }
            snapEnds(coords, tap.point.getCoordinate(), t.point.getCoordinate());
            appendSegment(coords, flowTotal, "branch", tapNode, t.objectId,
                    grid, ref, seq, v, t.objectId);
        } else {
            Point branchPt = gridSnapFree(grid, clusterCenter);
            List<Coordinate> trunk = route(grid, tap.point, branchPt, turnPenalty, packDn);
            if (trunk == null) {
                for (Model.ConnectionTarget t : pack) {
                    v.unconnected.add(new Unconnected(t.objectId, t.anchor(), t.flowTph,
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
            snapEnds(trunk, tap.point.getCoordinate(), branchPt.getCoordinate());
            appendSegment(trunk, flowTotal, "trunk", tapNode, branchNode,
                    grid, ref, seq, v, owner.toString());
            for (Model.ConnectionTarget t : pack) {
                double dnT = RefData.num(ref.diameterForFlow(t.flowTph).get("dn_mm"));
                List<Coordinate> coords = routeToTarget(grid, branchPt, t, turnPenalty, dnT, zoneById, v);
                if (coords == null) {
                    v.unconnected.add(new Unconnected(t.objectId, t.anchor(), t.flowTph,
                            "A* не нашёл маршрут ветви"));
                    continue;
                }
                snapEnds(coords, branchPt.getCoordinate(), t.point.getCoordinate());
                appendSegment(coords, t.flowTph, "branch", branchNode, t.objectId,
                        grid, ref, seq, v, t.objectId);
            }
        }
        assertTree(v.newSegments.subList(segsBefore, v.newSegments.size()), v.warnings);
    }

    private static void sublistClear(List<?> list, int from) {
        if (from < list.size()) {
            list.subList(from, list.size()).clear();
        }
    }

    // ------------------------------------------------------------------
    // Маршрут до целевой точки (§2.2: свой полигон ОКС)

    /**
     * Маршрут до точки подключения. Для точки внутри полигона ОКС
     * (restriction_type = oks) полигон временно проходим: §2.2 допускает
     * один финальный прямой участок от границы собственного полигона
     * до точки, отступ к своему полигону на него не распространяется.
     * Остальные ограничения продолжают действовать.
     */
    private static List<Coordinate> routeToTarget(ConstraintGrid grid, Point from,
                                                  Model.ConnectionTarget t,
                                                  double turnPenalty, double dnMm,
                                                  Map<String, Model.ConstraintZone> zoneById,
                                                  Variant v) {
        Model.ConstraintZone own = t.oksZoneId != null ? zoneById.get(t.oksZoneId) : null;
        if (own == null) {
            return route(grid, from, t.point, turnPenalty, dnMm);
        }
        List<int[]> freed = grid.freeCells(own.geom);
        List<int[]> blocked = null;
        List<Coordinate> path;
        try {
            blocked = grid.clearanceBlock(dnMm, Set.of(t.oksZoneId));
            path = grid.astar(from.getX(), from.getY(), t.point.getX(), t.point.getY(), turnPenalty);
        } finally {
            if (blocked != null) {
                grid.clearanceUnblock(blocked);
            }
            grid.blockCells(freed);
        }
        if (path == null) {
            return null;
        }
        return cutFinalApproach(path, own, t, grid, v);
    }

    /**
     * Обрезка маршрута по §2.2: с места входа в собственный полигон —
     * один прямой участок до точки. Если прямой хвост пересекает ЧУЖУЮ
     * запретную зону, оставляем исходный маршрут A* (остальные ограничения
     * продолжают действовать).
     */
    private static List<Coordinate> cutFinalApproach(List<Coordinate> path,
                                                     Model.ConstraintZone own,
                                                     Model.ConnectionTarget t,
                                                     ConstraintGrid grid, Variant v) {
        PreparedGeometry prep = PreparedGeometryFactory.prepare(own.geom);
        int firstInside = -1;
        for (int i = 0; i < path.size(); i++) {
            if (prep.covers(GF.createPoint(path.get(i)))) {
                firstInside = i;
                break;
            }
        }
        if (firstInside < 0) {
            return path; // маршрут не зашёл в полигон (точка снаружи/на границе)
        }
        Coordinate entry;
        if (firstInside == 0) {
            entry = path.get(0);
        } else {
            LineString edge = GF.createLineString(
                    new Coordinate[]{path.get(firstInside - 1), path.get(firstInside)});
            entry = nearestCoordinate(edge.intersection(own.geom.getBoundary()),
                    path.get(firstInside - 1));
            if (entry == null) {
                entry = path.get(firstInside);
            }
        }
        Coordinate targetC = t.point.getCoordinate();
        LineString tail = GF.createLineString(new Coordinate[]{entry, targetC});
        String hitId = grid.forbiddenLineHit(tail, Set.of(own.objectId));
        if (hitId != null) {
            v.warnings.add(t.objectId + ": прямой финальный участок пересекает запретную зону "
                    + hitId + " — оставлен маршрут A* (§2.2: остальные ограничения действуют)");
            return path;
        }
        List<Coordinate> out = new ArrayList<>(path.subList(0, firstInside));
        if (out.isEmpty() || out.get(out.size() - 1).distance(entry) > 0.01) {
            out.add(entry);
        } else {
            out.set(out.size() - 1, entry);
        }
        if (entry.distance(targetC) > 0.01) {
            out.add(targetC);
        }
        return out;
    }

    /** Ближайшая к from координата геометрии (null — геометрия пуста). */
    private static Coordinate nearestCoordinate(Geometry geom, Coordinate from) {
        Coordinate best = null;
        double bestDist = Double.POSITIVE_INFINITY;
        for (Coordinate c : geom.getCoordinates()) {
            double d = c.distance(from);
            if (d < bestDist) {
                bestDist = d;
                best = c;
            }
        }
        return best;
    }

    /**
     * Привязка концов маршрута к точным координатам узлов (§7.2: концы
     * LineString совпадают с узлами start_node_id / end_node_id).
     */
    private static void snapEnds(List<Coordinate> coords, Coordinate first, Coordinate last) {
        if (coords.isEmpty()) {
            coords.add(first);
            coords.add(last);
            return;
        }
        coords.set(0, first);
        if (coords.size() > 1) {
            coords.set(coords.size() - 1, last);
        } else {
            // LineString требует ≥2 точек: точка подключения может совпасть
            // с местом присоединения — участок нулевой длины всё равно нужен.
            coords.add(last.copy());
        }
    }

    /** Постобработка, границы спецучастков (таблица 2), диаметр, узлы. */
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

        if (parts.isEmpty()) {
            // Вырожденный случай: точка подключения совпадает с местом
            // присоединения (§2.4) — оформляем участок нулевой длины,
            // иначе точка молча выпала бы из выхода (§2.5).
            seq.merge("seg", 1, Integer::sum);
            List<Coordinate> zc = new ArrayList<>();
            for (Coordinate c : line.getCoordinates()) {
                zc.add(c.copy());
            }
            while (zc.size() < 2) {
                zc.add(zc.get(0).copy());
            }
            NewSegment zseg = new NewSegment(
                    "seg-" + seq.get("seg"), zc,
                    flow, role, "base", null, startNodeId, endNodeId);
            Hydraulics.sizeSegment(zseg, ref);
            v.newSegments.add(zseg);
            v.warnings.add(ownerId + ": точка подключения совпадает с местом "
                    + "присоединения — оформлен участок нулевой длины");
            return;
        }

        String curStart = startNodeId;
        for (int idx = 0; idx < parts.size(); idx++) {
            double a = parts.get(idx)[0], b = parts.get(idx)[1];
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
                        "граница специального участка (таблица 2)"));
            }
            seq.merge("seg", 1, Integer::sum);
            NewSegment seg = new NewSegment(
                    "seg-" + seq.get("seg"),
                    new ArrayList<>(List.of(piece.getCoordinates())),
                    flow, role, method, kSpecial, curStart, endNode);
            Hydraulics.sizeSegment(seg, ref);
            v.newSegments.add(seg);
            curStart = endNode;
        }

        Postprocess.checkCrossingAngles(line, grid.specialZones, v.warnings, ownerId);
    }

    /** A* с временными отступами запретных зон под диаметр трассы (таблица 2). */
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

    /** §3.2: диаметр новой камеры — максимум ДУ ВСЕХ примыкающих участков. */
    private static void finalizeChambers(Variant v, ExistingNetwork net, RefData ref) {
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
                // камера на существующем участке: линия через камеру —
                // два примыкания существующего ДУ (§2.1, разъяснение №12)
                Model.Segment seg0 = net.segments.get(ch.segmentId);
                if (seg0 != null) {
                    dns.add(seg0.diameterOrZero());
                }
            }
            double maxDn = !dns.isEmpty()
                    ? dns.stream().mapToDouble(Double::doubleValue).max().orElse(0.0)
                    : RefData.num(ref.diameters.get(0).get("dn_mm"));
            ch.diameterMm = maxDn;
            ch.costRub = ref.chamberCost(maxDn);
        }
    }

    private static List<List<Model.ConnectionTarget>> chunk(List<Model.ConnectionTarget> items, int n) {
        List<List<Model.ConnectionTarget>> out = new ArrayList<>();
        for (int i = 0; i < items.size(); i += n) {
            out.add(items.subList(i, Math.min(i + n, items.size())));
        }
        return out;
    }

    /**
     * Проверка «один путь до точки» (§2.1): компоненты новых сегментов —
     * деревья. Для компоненты из E рёбер и V вершин должно выполняться E = V - 1.
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
