package ru.heatnet.dit.job;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;
import ru.heatnet.dit.job.dto.JobDto;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.util.UUID;

@Service
public class JobService {

    private final JobRepository repo;
    private final JobProcessor processor;
    private final Path exchangeDir;

    public JobService(JobRepository repo,
                      JobProcessor processor,
                      @Value("${app.exchange-dir}") String exchangeDir) {
        this.repo = repo;
        this.processor = processor;
        this.exchangeDir = Paths.get(exchangeDir);
    }

    /**
     * Принять GeoJSON и создать задание.
     * Файл копируется потоково на диск (в общий volume), в память не поднимается.
     */
    @Transactional
    public JobDto createJob(MultipartFile file) throws IOException {
        UUID id = UUID.randomUUID();
        Path inDir = exchangeDir.resolve("in");
        Files.createDirectories(inDir);
        Path input = inDir.resolve(id + ".geojson");

        try (InputStream src = file.getInputStream()) {
            Files.copy(src, input, StandardCopyOption.REPLACE_EXISTING);
        }

        Instant now = Instant.now();
        JobEntity job = new JobEntity();
        job.setId(id);
        job.setFilename(file.getOriginalFilename() != null ? file.getOriginalFilename() : "input.geojson");
        job.setSizeBytes(Files.size(input));
        job.setStatus(JobStatus.QUEUED);
        job.setInputPath(input.toString());
        job.setCreatedAt(now);
        job.setUpdatedAt(now);
        repo.save(job);

        processor.submit(id);
        return JobDto.from(job);
    }

    @Transactional(readOnly = true)
    public JobEntity get(UUID id) {
        return repo.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "задание не найдено: " + id));
    }

    /** Путь к файлу результата для стриминговой отдачи. */
    @Transactional(readOnly = true)
    public Path resultFile(UUID id) {
        JobEntity job = get(id);
        if (job.getStatus() == JobStatus.FAILED) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "задание завершилось ошибкой: " + job.getErrorMessage());
        }
        if (job.getResultPath() == null) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "результат ещё не готов, статус: " + job.getStatus());
        }
        Path path = Paths.get(job.getResultPath());
        if (!Files.exists(path)) {
            throw new ResponseStatusException(HttpStatus.GONE, "файл результата удалён из временного хранилища");
        }
        return path;
    }
}
