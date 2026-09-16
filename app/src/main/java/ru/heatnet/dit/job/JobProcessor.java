package ru.heatnet.dit.job;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import ru.heatnet.dit.engine.EngineRunner;

import javax.annotation.PreDestroy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Асинхронный исполнитель заданий: принимает файл, гоняет движок,
 * обновляет статус в PostgreSQL. Спринт 1 — простой пул потоков;
 * при необходимости заменяется на полноценную очередь без смены API.
 */
@Component
public class JobProcessor {

    private static final Logger log = LoggerFactory.getLogger(JobProcessor.class);

    private final JobRepository repo;
    private final EngineRunner engine;
    private final Path exchangeDir;
    private final ExecutorService pool = Executors.newFixedThreadPool(2);

    public JobProcessor(JobRepository repo,
                        EngineRunner engine,
                        @Value("${app.exchange-dir}") String exchangeDir) {
        this.repo = repo;
        this.engine = engine;
        this.exchangeDir = Paths.get(exchangeDir);
    }

    public void submit(UUID jobId) {
        pool.submit(() -> run(jobId));
    }

    private void run(UUID jobId) {
        JobEntity job = repo.findById(jobId).orElse(null);
        if (job == null) {
            log.warn("job {}: не найден в БД, пропуск", jobId);
            return;
        }
        try {
            job.setStatus(JobStatus.PROCESSING);
            job.setUpdatedAt(Instant.now());
            repo.save(job);

            Path outDir = exchangeDir.resolve("out");
            Files.createDirectories(outDir);
            Path result = outDir.resolve(jobId + ".geojson");

            engine.process(jobId, job.getInputPath(), result.toString());

            job.setStatus(JobStatus.DONE);
            job.setResultPath(result.toString());
        } catch (Exception e) {
            log.error("job {}: ошибка обработки", jobId, e);
            job.setStatus(JobStatus.FAILED);
            job.setErrorMessage(String.valueOf(e.getMessage()));
        }
        job.setUpdatedAt(Instant.now());
        repo.save(job);
    }

    @PreDestroy
    public void shutdown() {
        pool.shutdown();
    }
}
