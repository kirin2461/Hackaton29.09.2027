package ru.heatnet.dit.engine.core;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Калькулятор стоимости варианта и ранжирование (разделы 8–9).
 *
 * Калькуляция — строго по статьям §10.7; показатель ранжирования (§9):
 *   S = 0,3·C/25 000 000 + 0,7·L/100,  L = новая сеть + реконструкция;
 *   меньший S — лучший вариант (rank 1).
 */
public final class Costs {

    private Costs() {
    }

    /** Развёрнутая калькуляция одного варианта (статьи §10.7). */
    public static Map<String, Double> variantCosts(Pipeline.Variant v, RefData ref) {
        double construction = 0.0;
        for (NewSegment s : v.newSegments) {
            construction += s.costRub;
        }
        double chamberConstruction = 0.0;
        for (Pipeline.NewChamber c : v.newChambers) {
            chamberConstruction += c.costRub;
        }
        // §8.2: каждая врезка — 5 млн ₽, вне зависимости от вида
        double tieIn = 0.0;
        for (Tapping.Tap t : v.taps) {
            tieIn += t.tapCostRub;
        }
        double reconstruction = v.recon.segmentsCostRub();
        double chamberReconstruction = v.recon.chambersCostRub();
        double penalty = 0.0;
        for (Pipeline.Unconnected u : v.unconnected) {
            penalty += ref.unconnectedPenalty(u.flowTph);
        }
        double total = construction + chamberConstruction + tieIn
                + reconstruction + chamberReconstruction + penalty;

        Map<String, Double> costs = new LinkedHashMap<>();
        costs.put("construction_cost", r2(construction));
        costs.put("chamber_construction_cost", r2(chamberConstruction));
        costs.put("tie_in_cost", r2(tieIn));
        costs.put("reconstruction_cost", r2(reconstruction));
        costs.put("chamber_reconstruction_cost", r2(chamberReconstruction));
        costs.put("unconnected_penalty", r2(penalty));
        costs.put("calculated_cost", r2(total));
        return costs;
    }

    /** Длины варианта (§10.7): новая сеть, реконструкция, сумма. */
    public static Map<String, Double> variantLengthsM(Pipeline.Variant v) {
        double newLen = 0.0;
        for (NewSegment s : v.newSegments) {
            newLen += s.lengthM;
        }
        newLen = r1(newLen);
        double reconLen = 0.0;
        for (Reconstruction.ReconSegment s : v.recon.segments) {
            reconLen += s.lengthM;
        }
        reconLen = r1(reconLen);
        Map<String, Double> lengths = new LinkedHashMap<>();
        lengths.put("new_network_length", newLen);
        lengths.put("reconstruction_length", reconLen);
        lengths.put("length", r1(newLen + reconLen));
        return lengths;
    }

    /** Ранжирование по разделу 9 (меньший S — лучший). */
    public static void rankVariants(List<Pipeline.Variant> variants, RefData ref) {
        if (variants.isEmpty()) {
            return;
        }
        for (Pipeline.Variant v : variants) {
            v.score = Math.rint(ref.score(v.costs.get("calculated_cost"),
                    v.lengths.get("length")) * 1e6) / 1e6;
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
