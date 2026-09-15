package ru.heatnet.dit.api;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Collections;
import java.util.Map;

@RestController
@Tag(name = "Health", description = "Служебные проверки")
public class HealthController {

    @Operation(summary = "Проверка живости сервиса")
    @GetMapping("/api/health")
    public Map<String, String> health() {
        return Collections.singletonMap("status", "ok");
    }
}
