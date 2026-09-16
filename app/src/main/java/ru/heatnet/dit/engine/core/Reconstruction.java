package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.LineString;
import org.locationtech.jts.linearref.LengthIndexedLine;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;

/**
 * Реконструкция существующей сети (раздел 7) и камер (§8.2).
 *
 * Раздел 7: дополнительный расход от каждой точки врезки поднимается по
 * цепочке upstream_object_id до источника и СУММИРУЕТСЯ на общих частях;
 * врезка в середину участка → реконструируется только ЧАСТЬ участка от
 * точки врезки к источнику; стоимость = длина части × ставка РЕКОНСТРУКЦИИ
 * требуемого Ду; Kспец и Kгл НЕ применяются.
 *
 * Раздел 8.2 (камеры) с уточнением протокола 16.09.2026 (п.8):
 * реконструкция тарифицируется ТОЛЬКО для камер-точек врезки; транзитные
 * камеры (через которые лишь вырос расход upstream) НЕ реконструируются
 * и в стоимость не входят.
 */
public final class Reconstruction {

    private Reconstruction() {
    }

    public static class ReconSegment {
        public final String objectId;            // recon-N
        public final String existingObjectId;    // id исходного участка (§10.3)
        public final double existingDn;
        public final double requiredDn;
        public final double existingFlow;
        public final double addedFlow;
        public final double calculatedFlow;
        public final double lengthM;
        public final double costRub;
        public final LineString geom;            // реконструируемая ЧАСТЬ участка

        ReconSegment(String objectId, String existingObjectId, double existingDn,
                     double requiredDn, double existingFlow, double addedFlow,
                     double calculatedFlow, double lengthM, double costRub, LineString geom) {
            this.objectId = objectId;
            this.existingObjectId = existingObjectId;
            this.existingDn = existingDn;
            this.requiredDn = requiredDn;
            this.existingFlow = existingFlow;
            this.addedFlow = addedFlow;
            this.calculatedFlow = calculatedFlow;
            this.lengthM = lengthM;
            this.costRub = costRub;
            this.geom = geom;
        }
    }

    public static class ReconChamber {
        public final String objectId;            // recon-ch-N
        public final String existingObjectId;    // id исходной камеры
        public final double existingDn;
        public final double requiredDn;
        public final double costRub;

        ReconChamber(String objectId, String existingObjectId,
                     double existingDn, double requiredDn, double costRub) {
            this.objectId = objectId;
            this.existingObjectId = existingObjectId;
            this.existingDn = existingDn;
            this.requiredDn = requiredDn;
            this.costRub = costRub;
        }
    }

    public static class Result {
        public final List<ReconSegment> segments;
        public final List<ReconChamber> chambers;

        Result(List<ReconSegment> segments, List<ReconChamber> chambers) {
            this.segments = segments;
            this.chambers = chambers;
        }

        public double segmentsCostRub() {
            return segments.stream().mapToDouble(s -> s.costRub).sum();
        }

        public double chambersCostRub() {
            return chambers.stream().mapToDouble(c -> c.costRub).sum();
        }
    }

    /** Отметка (0 или L) конца участка, БЛИЖАЙШЕГО к следующему объекту цепочки. */
    private static double sourceEndPos(ExistingNetwork net, Model.Segment seg) {
        Object nxt = seg.nextObjectId != null ? net.get(seg.nextObjectId) : null;
        double len = seg.geom.getLength();
        Geometry g = null;
        if (nxt instanceof Model.Segment) {
            g = ((Model.Segment) nxt).geom;
        } else if (nxt instanceof Model.Chamber) {
            g = ((Model.Chamber) nxt).geom;
        } else if (nxt instanceof Model.Source) {
            g = ((Model.Source) nxt).geom;
        }
        if (g == null) {
            return len; // обрыв цепочки = источник за дальним концом
        }
        LengthIndexedLine lil = new LengthIndexedLine(seg.geom);
        Coordinate p0 = lil.extractPoint(0.0);
        Coordinate p1 = lil.extractPoint(len);
        return g.distance(seg.geom.getFactory().createPoint(p0))
                <= g.distance(seg.geom.getFactory().createPoint(p1)) ? 0.0 : len;
    }

    /** Полный расчёт реконструкции по всем точкам врезки. */
    public static Result computeReconstruction(ExistingNetwork net, List<Tapping.Tap> taps,
                                               RefData refdata, List<String> warnings) {
        // --- накопление интервалов добавленного расхода по участкам ---
        // segmentId -> [(start_m, end_m, flow)]
        Map<String, List<double[]>> intervals = new LinkedHashMap<>();

        for (Tapping.Tap tap : taps) {
            if (tap.chainStartId == null) {
                continue;
            }
            double flow = tap.flowTph;
            String startFrom;
            if ("new_chamber_on_segment".equals(tap.kind) && tap.segmentId != null) {
                // врезка в середину участка: часть от врезки к источнику
                Model.Segment seg = net.segments.get(tap.segmentId);
                double len = seg.geom.getLength();
                double srcPos = sourceEndPos(net, seg);
                addInterval(intervals, tap.segmentId, tap.alongM, srcPos, flow);
                startFrom = seg.nextObjectId;
            } else {
                // врезка в камеру: цепочка начинается со следующего объекта
                Model.Chamber ch = net.chambers.get(tap.chainStartId);
                startFrom = ch != null ? ch.nextObjectId : null;
            }
            if (startFrom != null) {
                for (String oid : net.chainToSource(startFrom)) {
                    Model.Segment seg = net.segments.get(oid);
                    if (seg != null) {
                        addInterval(intervals, oid, 0.0, seg.geom.getLength(), flow);
                    }
                }
            }
        }

        // --- режем участки на элементарные части, считаем требуемый Ду ---
        List<ReconSegment> reconSegments = new ArrayList<>();
        int seq = 0;
        for (Map.Entry<String, List<double[]>> e : new TreeMap<>(intervals).entrySet()) {
            String sid = e.getKey();
            List<double[]> ivs = e.getValue();
            Model.Segment seg = net.segments.get(sid);
            double len = seg.geom.getLength();
            double existingDn = seg.diameterOrZero();
            List<Double> cutsList = new ArrayList<>();
            cutsList.add(0.0);
            cutsList.add(len);
            for (double[] iv : ivs) {
                cutsList.add(iv[0]);
                cutsList.add(iv[1]);
            }
            double[] cuts = cutsList.stream().distinct().sorted().mapToDouble(Double::doubleValue).toArray();
            for (int ci = 0; ci < cuts.length - 1; ci++) {
                double a = cuts[ci], b = cuts[ci + 1];
                if (b - a < 0.01) {
                    continue;
                }
                double mid = (a + b) / 2.0;
                double added = 0.0;
                for (double[] iv : ivs) {
                    if (iv[0] <= mid && mid <= iv[1]) {
                        added += iv[2];
                    }
                }
                if (added <= 0) {
                    continue;
                }
                double calculated = seg.flowTph + added;
                Map<String, Object> required = refdata.diameterForFlow(calculated);
                double requiredDn = RefData.num(required.get("dn_mm"));
                if (requiredDn <= existingDn) {
                    continue; // пропускной способности хватает
                }
                if (RefData.num(required.get("max_flow_tph")) < calculated) {
                    warnings.add(String.format(Locale.ROOT,
                            "%s: расход %.1f т/ч превышает максимум справочника %.1f т/ч",
                            sid, calculated, RefData.num(required.get("max_flow_tph"))));
                }
                LineString piece = Hydraulics.subline(seg.geom, a, b);
                seq++;
                double lengthM = Math.rint(piece.getLength() * 10.0) / 10.0;
                reconSegments.add(new ReconSegment(
                        "recon-" + seq,
                        sid,
                        existingDn,
                        requiredDn,
                        Math.rint(seg.flowTph * 1000.0) / 1000.0,
                        Math.rint(added * 1000.0) / 1000.0,
                        Math.rint(calculated * 1000.0) / 1000.0,
                        lengthM,
                        Math.rint(lengthM * refdata.reconTariff(requiredDn) * 100.0) / 100.0,
                        piece));
            }
        }

        // --- реконструкция камер (§8.2, протокол п.8): только камеры-врезки ---
        Map<String, Double> segRequired = new LinkedHashMap<>();
        for (ReconSegment rs : reconSegments) {
            segRequired.merge(rs.existingObjectId, rs.requiredDn, Math::max);
        }
        Map<String, Double> tapRequired = new LinkedHashMap<>();
        for (Tapping.Tap tap : taps) {
            if ("existing_chamber".equals(tap.kind) && tap.chamberId != null) {
                tapRequired.merge(tap.chamberId, tap.requiredDn, Math::max);
            }
        }

        List<ReconChamber> reconChambers = new ArrayList<>();
        int cseq = 0;
        // Протокол 16.09.2026 п.8: реконструируются ТОЛЬКО камеры-точки врезки;
        // транзитные камеры в стоимость не входят.
        for (String cid : new java.util.TreeSet<>(tapRequired.keySet())) {
            Model.Chamber ch = net.chambers.get(cid);
            if (ch == null) {
                continue;
            }
            List<String> adjIds = net.chamberAdjacentSegmentIds(cid);
            double required = 0.0;
            for (String sid : adjIds) {
                Model.Segment s = net.segments.get(sid);
                required = Math.max(required, segRequired.getOrDefault(sid, s.diameterOrZero()));
            }
            required = Math.max(required, tapRequired.getOrDefault(cid, 0.0));
            double existing = ch.diameterMm != null ? ch.diameterMm : 0.0;
            if (existing == 0.0 && !adjIds.isEmpty()) {
                for (String sid : adjIds) {
                    existing = Math.max(existing, net.segments.get(sid).diameterOrZero());
                }
            }
            if (required > existing) {
                cseq++;
                reconChambers.add(new ReconChamber(
                        "recon-ch-" + cseq, cid, existing, required,
                        refdata.chamberCost(required)));
            }
        }

        return new Result(reconSegments, reconChambers);
    }

    private static void addInterval(Map<String, List<double[]>> intervals,
                                    String sid, double a, double b, double flow) {
        double lo = Math.min(a, b), hi = Math.max(a, b);
        if (hi - lo > 0.01) {
            intervals.computeIfAbsent(sid, k -> new ArrayList<>()).add(new double[]{lo, hi, flow});
        }
    }
}
