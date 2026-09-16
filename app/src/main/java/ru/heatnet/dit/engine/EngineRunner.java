package ru.heatnet.dit.engine;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import ru.heatnet.dit.engine.core.Pipeline;
import ru.heatnet.dit.engine.core.PipelineInputException;
import ru.heatnet.dit.engine.core.RefData;

import java.nio.file.Paths;
import java.util.Map;
import java.util.UUID;

/**
 * Вычислительное движок ДИТ — Java 11, in-process (протокол 16.09.2026, п.1:
 * ядро строго на Java, без сторонних языков в Docker).
 *
 * Исторический HTTP-sidecar (Python geo-engine) заменён прямым вызовом
 * {@link Pipeline#runPipeline}. Справочники — classpath:/reference.yaml
 * (переопределяется ENGINE_REFERENCE_PATH, §2.14 ТЗ).
 */
@Component
public class EngineRunner {

    private static final Logger log = LoggerFactory.getLogger(EngineRunner.class);

    private final RefData refData = new RefData();

    /**
     * Обработать задание: прочитать inputPath (конкурсный GeoJSON),
     * записать результат в resultPath (FeatureCollection по §10).
     * Невалидный вход — IllegalStateException с диагностикой (п.9).
     */
    public void process(UUID jobId, String inputPath, String resultPath) {
        log.info("job {}: запуск расчёта (in-process движок {})", jobId, Pipeline.ENGINE_VERSION);
        long t0 = System.currentTimeMillis();
        try {
            Map<String, Object> summary = Pipeline.runPipeline(
                    Paths.get(inputPath), Paths.get(resultPath), refData);
            log.info("job {}: расчёт завершён за {} мс, подключено {}/{} ОКС",
                    jobId, summary.get("job_elapsed_ms"),
                    summary.get("buildings_connected"), summary.get("buildings_total"));
        } catch (PipelineInputException e) {
            throw new IllegalStateException("невалидный входной набор: " + e.getMessage(), e);
        } finally {
            log.debug("job {}: движок занял {} мс", jobId, System.currentTimeMillis() - t0);
        }
    }
}
