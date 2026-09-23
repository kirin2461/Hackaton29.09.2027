package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Coordinate;

import java.util.ArrayList;
import java.util.List;

/** Новый участок сети (ствол, ветвь, спецпроходный кусок). */
public class NewSegment {

    public final String objectId;
    public final List<Coordinate> coords;
    public final double flowTph;
    public final String role;             // trunk | branch
    public final String method;           // base | special (§10.1 laying_method)
    public final Double kSpecial;         // Kспец зоны спецпрохода
    public double diameterMm;
    public double lengthM;
    public double costRub;
    public List<String> warnings = new ArrayList<>();
    public String startNodeId;            // §7.2
    public String endNodeId;              // §7.2
    public Double depthStart;             // §7.2 (null в базовом 2D-режиме)
    public Double depthEnd;
    public List<double[]> coords3d;       // служебный профиль (режим глубины, не выгружается)
    public double tariffRubM;             // ставка ₽/м на момент расчёта

    public NewSegment(String objectId, List<Coordinate> coords, double flowTph,
                      String role, String method, Double kSpecial,
                      String startNodeId, String endNodeId) {
        this.objectId = objectId;
        this.coords = coords;
        this.flowTph = flowTph;
        this.role = role;
        this.method = method;
        this.kSpecial = kSpecial;
        this.startNodeId = startNodeId;
        this.endNodeId = endNodeId;
        this.lengthM = pathLength(coords);
    }

    static double pathLength(List<Coordinate> coords) {
        double sum = 0.0;
        for (int i = 1; i < coords.size(); i++) {
            sum += Math.hypot(coords.get(i).x - coords.get(i - 1).x,
                    coords.get(i).y - coords.get(i - 1).y);
        }
        return sum;
    }
}
