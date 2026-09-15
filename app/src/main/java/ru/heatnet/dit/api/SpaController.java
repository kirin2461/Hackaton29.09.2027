package ru.heatnet.dit.api;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * SPA-фолбэк: маршруты фронтенда обслуживаются index.html.
 * Статика фронтенда лежит в classpath:/static (собирается Vite при сборке образа).
 */
@Controller
public class SpaController {

    @GetMapping("/dit")
    public String dit() {
        return "forward:/index.html";
    }
}
