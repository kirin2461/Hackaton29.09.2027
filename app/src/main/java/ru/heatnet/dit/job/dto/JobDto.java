package ru.heatnet.dit.job.dto;

import ru.heatnet.dit.job.JobEntity;

import java.time.Instant;
import java.util.UUID;

/** Публичное представление задания (JSON). */
public class JobDto {

    public UUID id;
    public String filename;
    public long sizeBytes;
    public String status;
    public String errorMessage;
    public Instant createdAt;
    public Instant updatedAt;
    public boolean resultReady;

    public static JobDto from(JobEntity e) {
        JobDto dto = new JobDto();
        dto.id = e.getId();
        dto.filename = e.getFilename();
        dto.sizeBytes = e.getSizeBytes();
        dto.status = e.getStatus().name();
        dto.errorMessage = e.getErrorMessage();
        dto.createdAt = e.getCreatedAt();
        dto.updatedAt = e.getUpdatedAt();
        dto.resultReady = e.getResultPath() != null;
        return dto;
    }
}
