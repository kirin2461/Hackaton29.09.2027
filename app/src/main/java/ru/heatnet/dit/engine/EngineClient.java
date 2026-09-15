package ru.heatnet.dit.engine;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Клиент внутреннего вычислительного движка (geo-engine).
 * Движок живёт только во внутренней сети docker-compose, наружу не публикуется.
 */
@Component
public class EngineClient {

    private static final Logger log = LoggerFactory.getLogger(EngineClient.class);

    private final RestTemplate rest;
    private final String engineUrl;

    public EngineClient(@Value("${app.engine-url}") String engineUrl) {
        this.engineUrl = engineUrl;
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(10_000);
        // Расчёт тяжёлый — читаем ответ до 30 минут
        factory.setReadTimeout(30 * 60 * 1000);
        this.rest = new RestTemplate(factory);
    }

    /**
     * Запустить обработку задания движком.
     * Движок читает inputPath из общего volume и пишет результат в resultPath.
     */
    public void process(UUID jobId, String inputPath, String resultPath) {
        Map<String, String> body = new HashMap<>();
        body.put("job_id", jobId.toString());
        body.put("input_path", inputPath);
        body.put("result_path", resultPath);

        log.info("job {}: вызов geo-engine {}/engine/process", jobId, engineUrl);
        ResponseEntity<String> resp = rest.postForEntity(engineUrl + "/engine/process", body, String.class);
        if (!resp.getStatusCode().is2xxSuccessful()) {
            throw new IllegalStateException("geo-engine вернул " + resp.getStatusCode() + ": " + resp.getBody());
        }
        log.info("job {}: geo-engine завершил обработку", jobId);
    }
}
