package ru.heatnet.dit.engine.core;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Мульти-ОКС: кластеризация под общий ствол (§2.11 ТЗ).
 *
 * Перспективные ОКС, чьи точки подключения ближе cluster_radius_m,
 * рассматриваются как кандидаты на СОВМЕСТНОЕ подключение: один ствол
 * от точки врезки до камеры разветвления, от неё — ветви к каждому ОКС.
 */
public final class Clustering {

    private Clustering() {
    }

    /** Жадная кластеризация по близости точек подключения (union-find). */
    public static List<List<Model.Building>> clusterBuildings(
            Map<String, Model.Building> buildings, double radiusM) {
        List<Model.Building> items = new ArrayList<>(buildings.values());
        int n = items.size();
        int[] parent = new int[n];
        for (int i = 0; i < n; i++) {
            parent[i] = i;
        }
        for (int i = 0; i < n; i++) {
            for (int j = i + 1; j < n; j++) {
                if (items.get(i).anchor().distance(items.get(j).anchor()) <= radiusM) {
                    union(parent, i, j);
                }
            }
        }
        Map<Integer, List<Model.Building>> clusters = new LinkedHashMap<>();
        for (int i = 0; i < n; i++) {
            clusters.computeIfAbsent(find(parent, i), k -> new ArrayList<>()).add(items.get(i));
        }
        // Крупные кластеры в начало — им важнее хорошая точка врезки
        List<List<Model.Building>> out = new ArrayList<>(clusters.values());
        out.sort((a, b) -> Integer.compare(b.size(), a.size()));
        return out;
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
