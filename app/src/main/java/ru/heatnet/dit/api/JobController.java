package ru.heatnet.dit.api;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import ru.heatnet.dit.job.JobService;
import ru.heatnet.dit.job.dto.JobDto;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

/**
 * Внешний REST API сервиса (ТЗ §3).
 */
@RestController
@RequestMapping("/api/jobs")
@Tag(name = "Jobs", description = "Задания на моделирование трасс подключения")
public class JobController {

    private final JobService jobs;

    public JobController(JobService jobs) {
        this.jobs = jobs;
    }

    @Operation(summary = "Загрузить совмещённый GeoJSON и создать задание",
            description = "Multipart-загрузка до 3 ГБ; файл стримится на диск, в память не поднимается.")
    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<JobDto> create(@RequestPart("file") MultipartFile file) throws IOException {
        return ResponseEntity.accepted().body(jobs.createJob(file));
    }

    @Operation(summary = "Статус задания")
    @GetMapping("/{id}")
    public JobDto get(@PathVariable UUID id) {
        return JobDto.from(jobs.get(id));
    }

    @Operation(summary = "Последние задания (до 50)")
    @GetMapping
    public java.util.List<JobDto> list() {
        return jobs.listRecent().stream().map(JobDto::from)
                .collect(java.util.stream.Collectors.toList());
    }

    @Operation(summary = "Выгрузить результат",
            description = "Стриминговая отдача выходного GeoJSON (до 500 МБ).")
    @GetMapping("/{id}/result")
    public ResponseEntity<Resource> result(@PathVariable UUID id) throws IOException {
        Path path = jobs.resultFile(id);
        InputStreamResource body = new InputStreamResource(Files.newInputStream(path));
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_JSON)
                .contentLength(Files.size(path))
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"result-" + id + ".geojson\"")
                .body(body);
    }
}
