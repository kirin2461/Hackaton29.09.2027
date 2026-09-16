package ru.heatnet.dit.engine.core;

import java.nio.file.*;
import java.util.*;

/** Паритет-прогон: java ParityMain <input.geojson> <out.json> */
public class ParityMain {
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        Map<String, Object> s = Pipeline.runPipeline(Paths.get(args[0]), Paths.get(args[1]), new RefData());
        System.out.println("engine=" + s.get("engine"));
        System.out.println("unconnected_ids=" + s.get("unconnected_ids"));
        Map<String, Object> costs = (Map<String, Object>) s.get("costs_rub");
        System.out.printf("summary total=%.0f length=%.1f%n",
                ((Number) costs.get("total")).doubleValue(),
                ((Number) s.get("length_total_m")).doubleValue());
        for (Map<String, Object> v : (List<Map<String, Object>>) s.get("variants")) {
            Map<String, Object> vc = (Map<String, Object>) v.get("costs_rub");
            System.out.printf("variant rank=%s score=%.4f total=%.0f length=%.1f recommended=%s unconnected=%s%n",
                    v.get("rank"), ((Number) v.get("score")).doubleValue(),
                    ((Number) vc.get("total")).doubleValue(),
                    ((Number) v.get("length_total_m")).doubleValue(),
                    v.get("is_recommended"), v.get("unconnected_ids"));
        }
    }
}
