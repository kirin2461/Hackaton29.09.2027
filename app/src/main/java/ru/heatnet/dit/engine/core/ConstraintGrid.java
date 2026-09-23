package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.geom.Point;
import org.locationtech.jts.geom.prep.PreparedGeometry;
import org.locationtech.jts.geom.prep.PreparedGeometryFactory;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;
import java.util.Set;

/**
 * Весовая сетка пространственных ограничений + A* (таблица 5.1).
 *
 *   forbidden — пересечение запрещено: геометрия зоны непроходима,
 *               а МИНИМАЛЬНОЕ РАССТОЯНИЕ (для oks — 5/7/9 м по ДУ новой сети,
 *               для park/social_area/prohibited_site/water/railway — 1,0 м)
 *               обеспечивается ВРЕМЕННЫМИ буферными блокировками под
 *               конкретный диаметр прокладываемой трассы. Расстояние
 *               считается между ГРАНЯМИ расчётных габаритов (таблица 1, §3.1).
 *
 *   special_passage — спецпроход: проходимо с множителем Kспец зоны.
 */
public class ConstraintGrid {

    // 8 направлений: (di, dj, длина шага в ячейках)
    private static final double[][] NEIGHBOURS = {
            {1, 0, 1.0}, {-1, 0, 1.0}, {0, 1, 1.0}, {0, -1, 1.0},
            {1, 1, Math.sqrt(2)}, {1, -1, Math.sqrt(2)},
            {-1, 1, Math.sqrt(2)}, {-1, -1, Math.sqrt(2)},
    };

    public final double cell;
    private final double ox, oy;
    public final int nx, ny;

    private final boolean[][] blocked;
    private final float[][] mult;

    private final RefData refdata;
    private final Map<String, Double> zoneK = new HashMap<>();   // Kспец по ID зоны
    public final List<Model.ConstraintZone> specialZones = new ArrayList<>();
    private final List<Model.ConstraintZone> forbiddenZones = new ArrayList<>();
    private final Map<String, Geometry> clearanceCache = new HashMap<>();
    // точки присоединения к существующей сети: пересечение в месте врезки
    // спецпроходом не считается (разъяснение №10 — это не пересечение)
    private final Map<String, List<Point>> tapExclusions = new HashMap<>();

    public ConstraintGrid(double[] bounds, RefData refdata) {
        this.cell = refdata.rule("grid_cell_m");
        double pad = cell * 4; // запас по краям
        this.ox = bounds[0] - pad;
        this.oy = bounds[1] - pad;
        this.nx = (int) Math.ceil((bounds[2] - bounds[0] + 2 * pad) / cell) + 1;
        this.ny = (int) Math.ceil((bounds[3] - bounds[1] + 2 * pad) / cell) + 1;
        this.blocked = new boolean[nx][ny];
        this.mult = new float[nx][ny];
        for (int i = 0; i < nx; i++) {
            for (int j = 0; j < ny; j++) {
                mult[i][j] = 1.0f;
            }
        }
        this.refdata = refdata;
    }

    // ---------- растеризация ----------

    private List<int[]> cellsCoveredBy(Geometry geom) {
        var env = geom.getEnvelopeInternal();
        int i0 = Math.max(0, (int) ((env.getMinX() - ox) / cell) - 1);
        int j0 = Math.max(0, (int) ((env.getMinY() - oy) / cell) - 1);
        int i1 = Math.min(nx - 1, (int) ((env.getMaxX() - ox) / cell) + 2);
        int j1 = Math.min(ny - 1, (int) ((env.getMaxY() - oy) / cell) + 2);
        PreparedGeometry prepared = PreparedGeometryFactory.prepare(geom);
        List<int[]> cells = new ArrayList<>();
        for (int i = i0; i <= i1; i++) {
            for (int j = j0; j <= j1; j++) {
                double[] c = cellCenter(i, j);
                if (prepared.covers(geom.getFactory().createPoint(new Coordinate(c[0], c[1])))) {
                    cells.add(new int[]{i, j});
                }
            }
        }
        return cells;
    }

    /** Растеризовать ограничения: запретные — геометрия, спец — Kспец. */
    @SuppressWarnings("unchecked")
    public void applyConstraints(List<Model.ConstraintZone> zones) {
        for (Model.ConstraintZone z : zones) {
            if ("forbidden".equals(z.kind)) {
                forbiddenZones.add(z);
                for (int[] c : cellsCoveredBy(z.geom)) {
                    blocked[c[0]][c[1]] = true;
                }
            } else if ("special_passage".equals(z.kind)) {
                Map<String, Object> rule = refdata.restrictionRule(z.restrictionType);
                double k = rule != null ? RefData.num(rule.getOrDefault("k_special", 1.5)) : 1.5;
                zoneK.put(z.objectId, k);
                specialZones.add(z);
                for (int[] c : cellsCoveredBy(z.geom)) {
                    if (!blocked[c[0]][c[1]]) {
                        mult[c[0]][c[1]] = (float) Math.max(mult[c[0]][c[1]], (float) k);
                    }
                }
            }
        }
    }

    // ---------- отступы запретных зон под диаметр (таблица 5.1) ----------

    /** Буферная геометрия: отступ + половина ширины габарита (между гранями). */
    private Geometry clearanceBufferGeom(Model.ConstraintZone zone, double dnMm) {
        String key = zone.objectId + ":" + (int) dnMm;
        Geometry cached = clearanceCache.get(key);
        if (cached == null) {
            double dist = refdata.minDistanceM(
                    zone.restrictionType != null ? zone.restrictionType : "", dnMm);
            dist += refdata.envelopeWidthM(dnMm) / 2.0;
            cached = zone.geom.buffer(dist);
            clearanceCache.put(key, cached);
        }
        return cached;
    }

    /** Временно заблокировать отступы запретных зон под диаметр трассы. */
    public List<int[]> clearanceBlock(double dnMm) {
        return clearanceBlock(dnMm, java.util.Collections.emptySet());
    }

    /**
     * Временно заблокировать отступы запретных зон под диаметр трассы.
     * Зоны из skipZoneIds пропускаются — §2.2: отступ к СВОЕМУ полигону ОКС
     * на финальный участок к целевой точке не распространяется.
     */
    public List<int[]> clearanceBlock(double dnMm, Set<String> skipZoneIds) {
        List<int[]> cells = new ArrayList<>();
        for (Model.ConstraintZone z : forbiddenZones) {
            if (skipZoneIds.contains(z.objectId)) {
                continue;
            }
            Geometry buf = clearanceBufferGeom(z, dnMm);
            for (int[] c : cellsCoveredBy(buf)) {
                if (!blocked[c[0]][c[1]]) {
                    blocked[c[0]][c[1]] = true;
                    cells.add(c);
                }
            }
        }
        return cells;
    }

    public void clearanceUnblock(List<int[]> cells) {
        for (int[] c : cells) {
            blocked[c[0]][c[1]] = false;
        }
    }

    /**
     * Освободить ячейки, занятые геометрией (свой полигон ОКС, §2.2).
     * Возвращает ранее заблокированные ячейки для последующего восстановления.
     */
    public List<int[]> freeCells(Geometry geom) {
        List<int[]> freed = new ArrayList<>();
        for (int[] c : cellsCoveredBy(geom)) {
            if (blocked[c[0]][c[1]]) {
                blocked[c[0]][c[1]] = false;
                freed.add(c);
            }
        }
        return freed;
    }

    /** Восстановить блокировку ячеек, освобождённых freeCells. */
    public void blockCells(List<int[]> cells) {
        for (int[] c : cells) {
            blocked[c[0]][c[1]] = true;
        }
    }

    /**
     * ID запретной зоны, если точка внутри неё/её отступа.
     * Проверка по ГЕОМЕТРИИ зон (не по растру); зоны из skipZoneIds
     * пропускаются (свой полигон ОКС целевой точки, §2.2).
     */
    public String forbiddenReason(Point pt, Double dnMm, Set<String> skipZoneIds) {
        for (Model.ConstraintZone z : forbiddenZones) {
            if (skipZoneIds.contains(z.objectId)) {
                continue;
            }
            if (dnMm != null) {
                if (clearanceBufferGeom(z, dnMm).intersects(pt)) {
                    return z.objectId;
                }
            } else if (z.geom.intersects(pt)) {
                return z.objectId;
            }
        }
        return null;
    }

    public String forbiddenReason(Point pt, Double dnMm) {
        return forbiddenReason(pt, dnMm, java.util.Collections.emptySet());
    }

    /**
     * ID запретной зоны, которую пересекает ЛИНИЯ (по геометрии зон).
     * Зоны из skipZoneIds пропускаются. null — пересечений нет.
     */
    public String forbiddenLineHit(LineString line, Set<String> skipZoneIds) {
        for (Model.ConstraintZone z : forbiddenZones) {
            if (skipZoneIds.contains(z.objectId)) {
                continue;
            }
            if (z.geom.intersects(line)) {
                return z.objectId;
            }
        }
        return null;
    }

    // ---------- точки присоединения (исключение из спецпроходов heat_network) ----------

    /** Зарегистрировать точку присоединения на существующем участке (id зоны = id участка). */
    public void addTapExclusion(String zoneId, Point pt) {
        tapExclusions.computeIfAbsent(zoneId, k -> new ArrayList<>()).add(pt);
    }

    /** Сбросить точки присоединения (между вариантами). */
    public void clearTapExclusions() {
        tapExclusions.clear();
    }

    /**
     * Точка присоединения рядом с отрезком [aM, bM] вдоль линии lil?
     * Используется режимом глубины: место врезки — не пересечение
     * (разъяснение №10), вертикальные ограничения там не применяются.
     */
    public boolean tapExclusionNear(String zoneId,
                                    org.locationtech.jts.linearref.LengthIndexedLine lil,
                                    double aM, double bM, double marginM) {
        List<Point> taps = tapExclusions.get(zoneId);
        if (taps == null || taps.isEmpty()) {
            return false;
        }
        for (Point tp : taps) {
            double dTap = lil.indexOf(tp.getCoordinate());
            if (dTap >= aM - marginM && dTap <= bM + marginM) {
                return true;
            }
        }
        return false;
    }

    // ---------- границы спецучастков (таблица 5.1) ----------

    /** Интервал спецпрохода вдоль линии. */
    public static class SpecialInterval {
        public double a, b;
        public String zoneId;
        public double k;

        SpecialInterval(double a, double b, String zoneId, double k) {
            this.a = a;
            this.b = b;
            this.zoneId = zoneId;
            this.k = k;
        }
    }

    /**
     * Интервалы спецпрохода вдоль линии. Полигональные зоны (road,
     * tram_tracks): пересечение с полигоном ± extent_m. Линейные/точечные:
     * ±extent_m от каждой точки пересечения. Наложения объединяются (max K).
     */
    @SuppressWarnings("unchecked")
    public List<SpecialInterval> specialIntervals(LineString line) {
        double length = line.getLength();
        List<SpecialInterval> raw = new ArrayList<>();
        if (length < 1e-6 || specialZones.isEmpty()) {
            return raw;
        }
        org.locationtech.jts.linearref.LengthIndexedLine lil =
                new org.locationtech.jts.linearref.LengthIndexedLine(line);
        for (Model.ConstraintZone z : specialZones) {
            if (!line.intersects(z.geom)) {
                continue;
            }
            Map<String, Object> rule = refdata.restrictionRule(z.restrictionType);
            if (rule == null) {
                rule = new HashMap<>();
            }
            double extent = RefData.num(rule.getOrDefault("extent_m", 0.0));
            double k = zoneK.getOrDefault(z.objectId,
                    RefData.num(rule.getOrDefault("k_special", 1.5)));
            String mode = String.valueOf(rule.getOrDefault("extent_mode", "polygon"));
            String gtype = z.geom.getGeometryType();
            Geometry inter = line.intersection(z.geom);
            List<SpecialInterval> zoneIntervals = new ArrayList<>();
            if ("polygon".equals(mode) || "Polygon".equals(gtype) || "MultiPolygon".equals(gtype)) {
                List<double[]> pts = intervalPoints(inter);
                if (pts.isEmpty()) {
                    continue;
                }
                double a = Double.POSITIVE_INFINITY, b = Double.NEGATIVE_INFINITY;
                for (double[] p : pts) {
                    double d = lil.indexOf(new Coordinate(p[0], p[1]));
                    a = Math.min(a, d);
                    b = Math.max(b, d);
                }
                zoneIntervals.add(new SpecialInterval(Math.max(0.0, a - extent),
                        Math.min(length, b + extent), z.objectId, k));
            } else {
                for (double[] p : intervalPoints(inter)) {
                    double d = lil.indexOf(new Coordinate(p[0], p[1]));
                    zoneIntervals.add(new SpecialInterval(Math.max(0.0, d - extent),
                            Math.min(length, d + extent), z.objectId, k));
                }
            }
            // точка присоединения (врезка) — не пересечение: интервалы вокруг
            // неё не считаются спецпроходом (§2.4 + разъяснение №10)
            List<Point> taps = tapExclusions.get(z.objectId);
            if (taps != null && !taps.isEmpty()) {
                List<SpecialInterval> kept = new ArrayList<>();
                for (SpecialInterval iv : zoneIntervals) {
                    boolean atTap = false;
                    for (Point tp : taps) {
                        double dTap = lil.indexOf(tp.getCoordinate());
                        if (dTap >= iv.a - extent - 1.0 && dTap <= iv.b + extent + 1.0) {
                            atTap = true;
                            break;
                        }
                    }
                    if (!atTap) {
                        kept.add(iv);
                    }
                }
                zoneIntervals = kept;
            }
            raw.addAll(zoneIntervals);
        }
        return mergeIntervals(raw);
    }

    // ---------- вариант «альтернативный коридор» ----------

    /** Временно повысить стоимость ячеек вдоль путей (×factor). */
    public List<Object[]> penalizeCorridor(List<List<Coordinate>> paths, double radiusM, double factor) {
        Set<Long> cells = new LinkedHashSet<>();
        int r = (int) Math.ceil(radiusM / cell);
        for (List<Coordinate> pts : paths) {
            for (Coordinate p : pts) {
                int[] cc = toCell(p.x, p.y);
                for (int i = cc[0] - r; i <= cc[0] + r; i++) {
                    for (int j = cc[1] - r; j <= cc[1] + r; j++) {
                        if (i >= 0 && i < nx && j >= 0 && j < ny) {
                            cells.add((long) i * ny + j);
                        }
                    }
                }
            }
        }
        List<Object[]> changed = new ArrayList<>();
        for (long key : cells) {
            int i = (int) (key / ny), j = (int) (key % ny);
            if (!blocked[i][j]) {
                changed.add(new Object[]{i, j, mult[i][j]});
                mult[i][j] *= (float) factor;
            }
        }
        return changed;
    }

    public void restoreMult(List<Object[]> changed) {
        for (Object[] e : changed) {
            mult[(Integer) e[0]][(Integer) e[1]] = (Float) e[2];
        }
    }

    /** Временная блокировка (например, контур целевого ОКС). */
    public List<int[]> blockPolygon(Geometry geom) {
        List<int[]> cells = new ArrayList<>();
        for (int[] c : cellsCoveredBy(geom)) {
            if (!blocked[c[0]][c[1]]) {
                cells.add(c);
                blocked[c[0]][c[1]] = true;
            }
        }
        return cells;
    }

    public void unblock(List<int[]> cells) {
        for (int[] c : cells) {
            blocked[c[0]][c[1]] = false;
        }
    }

    // ---------- координаты ----------

    public double[] cellCenter(int i, int j) {
        return new double[]{ox + (i + 0.5) * cell, oy + (j + 0.5) * cell};
    }

    public int[] toCell(double x, double y) {
        int i = Math.min(Math.max(0, (int) ((x - ox) / cell)), nx - 1);
        int j = Math.min(Math.max(0, (int) ((y - oy) / cell)), ny - 1);
        return new int[]{i, j};
    }

    public int[] nearestFree(int[] cell0) {
        if (!blocked[cell0[0]][cell0[1]]) {
            return cell0;
        }
        int ci = cell0[0], cj = cell0[1];
        for (int r = 1; r < 40; r++) {
            for (int di = -r; di <= r; di++) {
                for (int dj : new int[]{-r, r}) {
                    int[][] cands = {{ci + di, cj + dj}, {ci + dj, cj + di}};
                    for (int[] cand : cands) {
                        if (cand[0] >= 0 && cand[0] < nx && cand[1] >= 0 && cand[1] < ny
                                && !blocked[cand[0]][cand[1]]) {
                            return cand;
                        }
                    }
                }
            }
        }
        return null;
    }

    // ---------- A* ----------

    private static class Entry {
        final double f, g;
        final int i, j;
        final int pi, pj;      // родитель (-1 — нет)
        final int dirIdx;

        Entry(double f, double g, int i, int j, int pi, int pj, int dirIdx) {
            this.f = f;
            this.g = g;
            this.i = i;
            this.j = j;
            this.pi = pi;
            this.pj = pj;
            this.dirIdx = dirIdx;
        }
    }

    /** Путь между точками (метрическая СК). null — путь не найден. */
    public List<Coordinate> astar(double sx, double sy, double gx, double gy,
                                  Double turnPenaltyM) {
        double tp = turnPenaltyM != null ? turnPenaltyM : refdata.rule("turn_penalty_m");
        int[] start = nearestFree(toCell(sx, sy));
        int[] goal = nearestFree(toCell(gx, gy));
        if (start == null || goal == null) {
            return null;
        }
        double[] gc = cellCenter(goal[0], goal[1]);

        PriorityQueue<Entry> heap = new PriorityQueue<>(Comparator
                .comparingDouble((Entry e) -> e.f)
                .thenComparingDouble(e -> e.g)
                .thenComparingInt(e -> e.i)
                .thenComparingInt(e -> e.j));
        heap.add(new Entry(0.0, 0.0, start[0], start[1], -1, -1, -1));

        Map<Long, int[]> came = new HashMap<>();        // cell -> {pi, pj}
        Map<Long, Double> bestG = new HashMap<>();
        Map<Long, Integer> directions = new HashMap<>();
        long startKey = (long) start[0] * ny + start[1];
        long goalKey = (long) goal[0] * ny + goal[1];
        bestG.put(startKey, 0.0);
        directions.put(startKey, -1);

        while (!heap.isEmpty()) {
            Entry e = heap.poll();
            long curKey = (long) e.i * ny + e.j;
            if (curKey == goalKey) {
                List<int[]> cells = new ArrayList<>();
                cells.add(new int[]{e.i, e.j});
                long ck = curKey;
                while (came.containsKey(ck)) {
                    int[] par = came.get(ck);
                    cells.add(par);
                    ck = (long) par[0] * ny + par[1];
                }
                List<Coordinate> path = new ArrayList<>();
                for (int k = cells.size() - 1; k >= 0; k--) {
                    double[] c = cellCenter(cells.get(k)[0], cells.get(k)[1]);
                    path.add(new Coordinate(c[0], c[1]));
                }
                return path;
            }

            int curDir = directions.getOrDefault(curKey, -1);
            double[] cc = cellCenter(e.i, e.j);
            for (int dirIdx = 0; dirIdx < NEIGHBOURS.length; dirIdx++) {
                int ni = e.i + (int) NEIGHBOURS[dirIdx][0];
                int nj = e.j + (int) NEIGHBOURS[dirIdx][1];
                if (ni < 0 || ni >= nx || nj < 0 || nj >= ny) {
                    continue;
                }
                if (blocked[ni][nj]) {
                    continue;
                }
                double[] nc = cellCenter(ni, nj);
                // (mult[cur] + mult[nb]) — float32-арифметика, как в numpy
                double move = Math.hypot(nc[0] - cc[0], nc[1] - cc[1])
                        * (mult[e.i][e.j] + mult[ni][nj]) / 2.0;
                if (curDir >= 0 && dirIdx != curDir) {
                    move += tp; // штраф за смену направления
                }
                double ng = e.g + move;
                long nKey = (long) ni * ny + nj;
                if (ng < bestG.getOrDefault(nKey, Double.POSITIVE_INFINITY)) {
                    bestG.put(nKey, ng);
                    came.put(nKey, new int[]{e.i, e.j});
                    directions.put(nKey, dirIdx);
                    double h = Math.hypot(nc[0] - gc[0], nc[1] - gc[1]);
                    heap.add(new Entry(ng + h, ng, ni, nj, e.i, e.j, dirIdx));
                }
            }
        }
        return null;
    }

    // ------------------------------------------------------------------
    // утилиты интервалов спецпрохода

    /** Точки геометрии пересечения (для project вдоль линии). */
    static List<double[]> intervalPoints(Geometry geom) {
        List<double[]> pts = new ArrayList<>();
        String t = geom.getGeometryType();
        switch (t) {
            case "Point":
                pts.add(new double[]{geom.getCoordinate().x, geom.getCoordinate().y});
                break;
            case "MultiPoint":
                for (int i = 0; i < geom.getNumGeometries(); i++) {
                    Coordinate c = geom.getGeometryN(i).getCoordinate();
                    pts.add(new double[]{c.x, c.y});
                }
                break;
            case "LineString":
                for (Coordinate c : geom.getCoordinates()) {
                    pts.add(new double[]{c.x, c.y});
                }
                break;
            case "MultiLineString":
            case "GeometryCollection":
                for (int i = 0; i < geom.getNumGeometries(); i++) {
                    pts.addAll(intervalPoints(geom.getGeometryN(i)));
                }
                break;
            case "Polygon":
            case "MultiPolygon":
                Coordinate rp = geom.getInteriorPoint().getCoordinate();
                pts.add(new double[]{rp.x, rp.y});
                break;
            default:
                break;
        }
        return pts;
    }

    /** Объединить пересекающиеся интервалы (Kспец — максимальный). */
    static List<SpecialInterval> mergeIntervals(List<SpecialInterval> raw) {
        if (raw.isEmpty()) {
            return raw;
        }
        raw.sort(Comparator.comparingDouble(iv -> iv.a));
        List<SpecialInterval> merged = new ArrayList<>();
        merged.add(raw.get(0));
        for (int idx = 1; idx < raw.size(); idx++) {
            SpecialInterval iv = raw.get(idx);
            SpecialInterval last = merged.get(merged.size() - 1);
            if (iv.a <= last.b + 1e-6) {
                last.b = Math.max(last.b, iv.b);
                if (iv.k > last.k) {
                    last.zoneId = iv.zoneId;
                    last.k = iv.k;
                }
            } else {
                merged.add(iv);
            }
        }
        return merged;
    }
}
