package ru.heatnet.dit.engine.core;

import java.util.Locale;

/**
 * Преобразование СК: EPSG:4326 (WGS84) ↔ EPSG:326xx (UTM, зона 01–60).
 *
 * Реализация поперечной проекции Меркатора по стандартным рядам Снайдера
 * (та же математика, что у PROJ/pyproj, точность в пределах зоны ~0,1 мм).
 * Геодезический датум везде WGS84 — пересчёт датумов не требуется.
 *
 * По техприложению вход строго EPSG:4326, рабочая СК — EPSG:32637
 * (UTM зона 37N для Москвы); код поддерживает любую зону EPSG:326xx.
 */
public final class Crs {

    private static final double A = 6378137.0;                 // большая полуось WGS84
    private static final double F = 1.0 / 298.257223563;       // сжатие WGS84
    private static final double K0 = 0.9996;                   // масштаб на осевом меридиане
    private static final double FALSE_E = 500000.0;

    private static final double E2 = F * (2.0 - F);            // первый эксцентриситет²
    private static final double EP2 = E2 / (1.0 - E2);         // второй эксцентриситет²

    private Crs() {
    }

    /** Зона UTM из кода EPSG:326xx; иной код — IllegalArgumentException. */
    public static int zoneOf(String epsg) {
        String s = epsg == null ? "" : epsg.toUpperCase(Locale.ROOT).replace("EPSG:", "").trim();
        int code = Integer.parseInt(s);
        if (code == 4326) {
            return 0; // признак широты/долготы
        }
        if (code >= 32601 && code <= 32660) {
            return code - 32600;
        }
        throw new IllegalArgumentException("поддерживаются только EPSG:4326 и EPSG:32601..32660, получено: " + epsg);
    }

    public static boolean isLonLat(String epsg) {
        return zoneOf(epsg) == 0;
    }

    /** Прямое преобразование: (lon, lat) градусы → (x, y) метры UTM зоны. */
    public static double[] forward(double lonDeg, double latDeg, int zone) {
        double lon0 = Math.toRadians(zone * 6.0 - 183.0);
        double phi = Math.toRadians(latDeg);
        double lam = Math.toRadians(lonDeg);

        double sin = Math.sin(phi), cos = Math.cos(phi), tan = Math.tan(phi);
        double n = A / Math.sqrt(1.0 - E2 * sin * sin);
        double t = tan * tan;
        double c = EP2 * cos * cos;
        double a = (lam - lon0) * cos;

        double m = A * ((1 - E2 / 4 - 3 * E2 * E2 / 64 - 5 * E2 * E2 * E2 / 256) * phi
                - (3 * E2 / 8 + 3 * E2 * E2 / 32 + 45 * E2 * E2 * E2 / 1024) * Math.sin(2 * phi)
                + (15 * E2 * E2 / 256 + 45 * E2 * E2 * E2 / 1024) * Math.sin(4 * phi)
                - (35 * E2 * E2 * E2 / 3072) * Math.sin(6 * phi));

        double x = FALSE_E + K0 * n * (a + (1 - t + c) * a * a * a / 6
                + (5 - 18 * t + t * t + 72 * c - 58 * EP2) * Math.pow(a, 5) / 120);
        double y = K0 * (m + n * tan * (a * a / 2
                + (5 - t + 9 * c + 4 * c * c) * Math.pow(a, 4) / 24
                + (61 - 58 * t + t * t + 600 * c - 330 * EP2) * Math.pow(a, 6) / 720));
        return new double[]{x, y};
    }

    /** Обратное преобразование: (x, y) метры UTM зоны → (lon, lat) градусы. */
    public static double[] inverse(double x, double y, int zone) {
        double lon0 = Math.toRadians(zone * 6.0 - 183.0);
        double m = y / K0;
        double mu = m / (A * (1 - E2 / 4 - 3 * E2 * E2 / 64 - 5 * E2 * E2 * E2 / 256));

        double e1 = (1 - Math.sqrt(1 - E2)) / (1 + Math.sqrt(1 - E2));
        double phi1 = mu
                + (3 * e1 / 2 - 27 * Math.pow(e1, 3) / 32) * Math.sin(2 * mu)
                + (21 * e1 * e1 / 16 - 55 * Math.pow(e1, 4) / 32) * Math.sin(4 * mu)
                + (151 * Math.pow(e1, 3) / 96) * Math.sin(6 * mu)
                + (1097 * Math.pow(e1, 4) / 512) * Math.sin(8 * mu);

        double sin1 = Math.sin(phi1), cos1 = Math.cos(phi1), tan1 = Math.tan(phi1);
        double c1 = EP2 * cos1 * cos1;
        double t1 = tan1 * tan1;
        double n1 = A / Math.sqrt(1 - E2 * sin1 * sin1);
        double r1 = A * (1 - E2) / Math.pow(1 - E2 * sin1 * sin1, 1.5);
        double d = (x - FALSE_E) / (n1 * K0);

        double lat = phi1 - (n1 * tan1 / r1) * (d * d / 2
                - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * Math.pow(d, 4) / 24
                + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * Math.pow(d, 6) / 720);
        double lon = lon0 + (d - (1 + 2 * t1 + c1) * Math.pow(d, 3) / 6
                + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * Math.pow(d, 5) / 120) / cos1;

        return new double[]{Math.toDegrees(lon), Math.toDegrees(lat)};
    }
}
