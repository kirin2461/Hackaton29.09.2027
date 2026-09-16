package ru.heatnet.dit.engine.core;

import org.locationtech.jts.geom.Point;

/** Технический узел (граница спецучастка / пересечение отметки 3,0 м). */
public class TechnicalNode {

    public final String objectId;
    public final Point point;
    public final String reason;

    public TechnicalNode(String objectId, Point point, String reason) {
        this.objectId = objectId;
        this.point = point;
        this.reason = reason;
    }
}
