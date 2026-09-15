package ru.heatnet.dit;

import io.swagger.v3.oas.annotations.OpenAPIDefinition;
import io.swagger.v3.oas.annotations.info.Info;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Публичная точка входа сервиса моделирования трасс (кейс ДИТ).
 * Java 11 / Spring Boot 2.6.3 / springdoc-openapi-ui 1.7.0.
 */
@OpenAPIDefinition(info = @Info(
        title = "HeatNet DIT API",
        version = "0.1.0",
        description = "Сервис моделирования трасс подключения к тепловым сетям. "
                + "Внешний REST API: загрузка совмещённого GeoJSON (до 3 ГБ, стриминг на диск), "
                + "статусы заданий, выгрузка результата (стриминг до 500 МБ)."))
@SpringBootApplication
public class DitApplication {

    public static void main(String[] args) {
        SpringApplication.run(DitApplication.class, args);
    }
}
