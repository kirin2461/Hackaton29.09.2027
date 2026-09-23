package ru.heatnet.dit.engine.core;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Кластеризация точек подключения под общий ствол (§2.1: несколько точек
 * могут использовать общий участок сети).
 *
 * Точки oks_connection_point, расположенные ближе cluster_radius_m друг
 * от друга, — кандидаты на СОВМЕСТНОЕ подключение: один ствол от места
 * присоединения до камеры разветвления, от неё — ветви к каждой точке.
 */
public final class Clustering {

    private Clustering() {
    }

    /** Жадная кластеризация по близости точек подключения (union-find). */
    public static List<List<Model.ConnectionTarget>> clusterTargets(
            Map<String, Model.ConnectionTarget> targets, double radiusM) {
        List<Model.ConnectionTarget> items = new ArrayList<>(targets.values());
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
        Map<Integer, List<Model.ConnectionTarget>> clusters = new LinkedHashMap<>();
        for (int i = 0; i < n; i++) {
            clusters.computeIfAbsent(find(parent, i), k -> new ArrayList<>()).add(items.get(i));
        }
        // Крупные кластеры в начало — им важнее хорошая точка присоединения
        List<List<Model.ConnectionTarget>> out = new ArrayList<>(clusters.values());
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
