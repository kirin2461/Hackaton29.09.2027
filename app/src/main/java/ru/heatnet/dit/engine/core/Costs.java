package ru.heatnet.dit.engine.core;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Калькулятор стоимости варианта и ранжирование (§6 техприложения).
 *
 *   construction_cost = новые участки + новые камеры + врезки в существующие
 *                       камеры (5 млн ₽ за каждый новый участок, §3.2);
 *   calculated_cost   = construction_cost + штрафы за неподключённые точки
 *                       (100 млн + 500 тыс. × G за точку);
 *   L                 = new_network_length (только новые участки);
 *   S = 0,7·(C / 25 000 000) + 0,3·(L / 100) — меньше = лучше (rank 1).
 */
public final class Costs {

    private Costs() {
    }

    /** Развёрнутая калькуляция одного варианта (атрибуты variant_summary §7.2). */
    public static Map<String, Double> variantCosts(Pipeline.Variant v,
                                                   ExistingNetwork net, RefData ref) {
        double segmentsCost = 0.0;
        for (NewSegment s : v.newSegments) {
            segmentsCost += s.costRub;
        }
        double chamberConstruction = 0.0;
        for (Pipeline.NewChamber c : v.newChambers) {
            chamberConstruction += c.costRub;
        }
        // §3.2: каждый новый линейный участок, заканчивающийся в существующей
        // камере, — одна врезка стоимостью 5 млн ₽ (любой конец участка:
        // направление записи координат роли не играет, §7.2)
        int tieInCount = 0;
        for (NewSegment s : v.newSegments) {
            if ((s.startNodeId != null && net.chambers.containsKey(s.startNodeId))
                    || (s.endNodeId != null && net.chambers.containsKey(s.endNodeId))) {
                tieInCount++;
            }
        }
        double tieInCost = tieInCount * ref.tieInCost();
        double construction = segmentsCost + chamberConstruction + tieInCost;
        double penalty = 0.0;
        for (Pipeline.Unconnected u : v.unconnected) {
            penalty += ref.unconnectedPenalty(u.flowTph);
        }
        double total = construction + penalty;

        Map<String, Double> costs = new LinkedHashMap<>();
        costs.put("construction_cost", r2(construction));
        costs.put("segments_cost", r2(segmentsCost)); // доп. поле (§7: допускается)
        costs.put("chamber_construction_cost", r2(chamberConstruction));
        costs.put("existing_chamber_tie_in_count", (double) tieInCount);
        costs.put("existing_chamber_tie_in_cost", r2(tieInCost));
        costs.put("unconnected_penalty", r2(penalty));
        costs.put("calculated_cost", r2(total));
        return costs;
    }

    /** Протяжённость варианта (§6): только новые участки сети. */
    public static Map<String, Double> variantLengthsM(Pipeline.Variant v) {
        double newLen = 0.0;
        for (NewSegment s : v.newSegments) {
            newLen += s.lengthM;
        }
        newLen = r1(newLen);
        Map<String, Double> lengths = new LinkedHashMap<>();
        lengths.put("new_network_length", newLen);
        lengths.put("length", newLen); // совместимость служебного summary
        return lengths;
    }

    /** Ранжирование по §6 (меньший S — лучший). */
    public static void rankVariants(List<Pipeline.Variant> variants, RefData ref) {
        if (variants.isEmpty()) {
            return;
        }
        for (Pipeline.Variant v : variants) {
            v.score = Math.rint(ref.score(v.costs.get("calculated_cost"),
                    v.lengths.get("new_network_length")) * 1e6) / 1e6;
        }
        variants.sort(Comparator.comparingDouble(x -> x.score));
        for (int i = 0; i < variants.size(); i++) {
            variants.get(i).rank = i + 1;
            variants.get(i).recommended = i == 0;
        }
    }

    static double r2(double x) {
        return Math.rint(x * 100.0) / 100.0;
    }

    static double r1(double x) {
        return Math.rint(x * 10.0) / 10.0;
    }
}
