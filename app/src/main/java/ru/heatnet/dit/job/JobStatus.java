package ru.heatnet.dit.job;

/** Статусы задания на моделирование. */
public enum JobStatus {
    QUEUED,
    PROCESSING,
    DONE,
    PARTIAL,
    FAILED
}
