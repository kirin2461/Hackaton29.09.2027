package ru.heatnet.dit.engine.core;

import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Загрузка справочников техприложения из YAML-конфига.
 *
 * Все справочники — во внешнем файле reference.yaml, НЕ в коде (§2.14 ТЗ).
 * Источник файла: ENGINE_REFERENCE_PATH, иначе ресурс classpath
 * /reference.yaml (упакован в jar).
 */
public class RefData {

    public static final String DEFAULT_RESOURCE = "/reference.yaml";

    // Таблица 4.1, по возрастанию Ду
    public final List<Map<String, Object>> diameters = new ArrayList<>();
    // Таблица 4.2: габариты по Ду
    public final Map<Integer, Map<String, Object>> envelopes = new LinkedHashMap<>();
    // Таблица 5.1
    public final Map<String, Object> restrictions;
    public final Map<String, Object> tariffs;
    public final Map<String, Object> scoring;
    public final Map<String, Object> rules;
    public final Map<String, Object> depth;

    @SuppressWarnings("unchecked")
    public RefData() {
        Map<String, Object> raw = loadYaml();
        List<Map<String, Object>> ds = (List<Map<String, Object>>) raw.get("diameters");
        ds.sort(Comparator.comparingDouble(d -> num(d.get("dn_mm"))));
        diameters.addAll(ds);
        for (Map<String, Object> e : (List<Map<String, Object>>) raw.get("envelopes")) {
            envelopes.put((int) num(e.get("dn_mm")), e);
        }
        restrictions = (Map<String, Object>) raw.getOrDefault("restrictions", new LinkedHashMap<>());
        tariffs = (Map<String, Object>) raw.get("tariffs_rub");
        scoring = (Map<String, Object>) raw.get("scoring");
        rules = (Map<String, Object>) raw.get("rules");
        depth = (Map<String, Object>) raw.getOrDefault("depth", new LinkedHashMap<>());
    }

    private static Map<String, Object> loadYaml() {
        String override = System.getenv("ENGINE_REFERENCE_PATH");
        try (InputStream in = override != null && !override.isEmpty()
                ? Files.newInputStream(Paths.get(override))
                : RefData.class.getResourceAsStream(DEFAULT_RESOURCE)) {
            if (in == null) {
                throw new IllegalStateException("не найден " + DEFAULT_RESOURCE + " в classpath");
            }
            return new Yaml().load(in);
        } catch (IOException e) {
            throw new IllegalStateException("не удалось прочитать reference.yaml: " + e.getMessage(), e);
        }
    }

    static double num(Object v) {
        return ((Number) v).doubleValue();
    }

    // ---- диаметры / гидравлика (таблица 4.1) ----

    /** Минимальный Ду, пропускная способность которого покрывает расход. */
    public Map<String, Object> diameterForFlow(double flowTph) {
        for (Map<String, Object> d : diameters) {
            if (num(d.get("max_flow_tph")) >= flowTph) {
                return d;
            }
        }
        return diameters.get(diameters.size() - 1); // факт нехватки — в warnings
    }

    public Map<String, Object> diameterEntry(double dnMm) {
        for (Map<String, Object> d : diameters) {
            if (num(d.get("dn_mm")) == dnMm) {
                return d;
            }
        }
        return diameters.get(diameters.size() - 1);
    }

    /** Следующий больший Ду (для повышения при превышении предельной длины). */
    public Map<String, Object> nextDiameter(double dnMm) {
        for (Map<String, Object> d : diameters) {
            if (num(d.get("dn_mm")) > dnMm) {
                return d;
            }
        }
        return diameters.get(diameters.size() - 1);
    }

    public double maxLenFor(double dnMm) {
        return num(diameterEntry(dnMm).get("max_len_m"));
    }

    // ---- габариты (таблица 4.2) ----

    private Map<String, Object> envelope(double dnMm) {
        Map<String, Object> e = envelopes.get((int) dnMm);
        if (e == null) {
            e = envelopes.get(envelopes.keySet().stream().mapToInt(Integer::intValue).max().orElse(0));
        }
        return e;
    }

    public double envelopeWidthM(double dnMm) {
        return num(envelope(dnMm).get("width_m"));
    }

    public double envelopeHeightM(double dnMm) {
        return num(envelope(dnMm).get("height_m"));
    }

    // ---- ограничения (таблица 5.1) ----

    @SuppressWarnings("unchecked")
    public Map<String, Object> restrictionRule(String restrictionType) {
        return (Map<String, Object>) restrictions.get(restrictionType);
    }

    /** Минимальное горизонтальное расстояние; для ОКС — ступенями по Ду. */
    @SuppressWarnings("unchecked")
    public double minDistanceM(String restrictionType, double dnMm) {
        Map<String, Object> rule = restrictionRule(restrictionType);
        if (rule == null) {
            return 1.0;
        }
        Object byDn = rule.get("min_distance_by_dn");
        if (byDn != null) {
            List<Map<String, Object>> steps = (List<Map<String, Object>>) byDn;
            for (Map<String, Object> step : steps) {
                if (dnMm <= num(step.get("max_dn_mm"))) {
                    return num(step.get("distance_m"));
                }
            }
            return num(steps.get(steps.size() - 1).get("distance_m"));
        }
        return num(rule.getOrDefault("min_distance_m", 1.0));
    }

    // ---- тарифы (раздел 8) ----

    /** Ставка нового строительства, ₽/м (таблица 4.1). */
    public double layTariff(double dnMm) {
        return num(diameterEntry(dnMm).get("cost_new_rub_m"));
    }

    /** §3.2: стоимость врезки в существующую камеру (за новый участок). */
    public double tieInCost() {
        return num(tariffs.get("tie_in_existing_chamber"));
    }

    /** §3.2: стоимость камеры по наибольшему ДУ примыкающих участков. */
    @SuppressWarnings("unchecked")
    public double chamberCost(double maxDnMm) {
        List<Map<String, Object>> scale = (List<Map<String, Object>>) tariffs.get("chamber_cost_scale");
        for (Map<String, Object> step : scale) {
            if (maxDnMm <= num(step.get("max_dn_mm"))) {
                return num(step.get("cost_rub"));
            }
        }
        return num(scale.get(scale.size() - 1).get("cost_rub"));
    }

    /** §6: штраф за неподключённую точку = 100 млн + 500 тыс. × G. */
    public double unconnectedPenalty(double flowTph) {
        return num(tariffs.get("unconnected_penalty_base"))
                + num(tariffs.get("unconnected_penalty_per_tph")) * flowTph;
    }

    public double rule(String key) {
        return num(rules.get(key));
    }

    // ---- ранжирование (раздел 9) ----

    /** S = w_c·C/C0 + w_l·L/L0; меньше — лучше. */
    public double score(double calculatedCostRub, double lengthM) {
        return num(scoring.get("weight_cost")) * calculatedCostRub / num(scoring.get("cost_norm_rub"))
                + num(scoring.get("weight_length")) * lengthM / num(scoring.get("length_norm_m"));
    }

    // ---- задание на глубину (раздел 6, доп. задача) ----

    public double depthRule(String key, double defaultValue) {
        Object v = depth.get(key);
        return v == null ? defaultValue : num(v);
    }

    /** Kгл = 1 + rate·(h − free) при h > free, иначе 1 (без скидки за мельче). */
    public double depthK(double depthM) {
        double free = depthRule("free_depth_m", 3.0);
        if (depthM <= free) {
            return 1.0;
        }
        return 1.0 + depthRule("depth_cost_rate", 0.10) * (depthM - free);
    }

    /**
     * §4: условный габарит и глубина существующей коммуникации
     * (глубина до ВЕРХА габарита; габарит heat_network — по таблице 1).
     * null — тип не описан.
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> existingUtility(String restrictionType) {
        Object m = depth.get("existing_utilities");
        if (!(m instanceof Map)) {
            return null;
        }
        return (Map<String, Object>) ((Map<String, Object>) m).get(restrictionType);
    }
}
