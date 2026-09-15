# Многостадийная сборка: Node (фронтенд) → Maven (Java) → JRE.
# Контекст сборки — КОРНЕНЬ репозитория (нужен доступ к frontend/).
# На хосте ничего не нужно: всё собирается в контейнерах.
# ТЗ: Java 11; базовый образ — Ubuntu 22.04 (jammy).

# --- стадия 1: сборка фронтенда (React/Three.js + страница /dit) ---
FROM node:20-bookworm-slim AS front
WORKDIR /front
COPY frontend/ ./
# Если frontend/dist уже собран (npm на сервере нестабилен) — используем его;
# иначе собираем в контейнере через зеркало npmmirror.
RUN if [ -f dist/index.html ]; then \
      echo "frontend/dist уже собран — пропускаю npm"; \
    else \
      npm config set registry https://registry.npmmirror.com && \
      (npm ci --no-audit --no-fund || npm ci --no-audit --no-fund) && \
      npm run build; \
    fi

# --- стадия 2: сборка Java-приложения со статикой фронтенда в jar ---
FROM maven:3.8.6-eclipse-temurin-11 AS build
WORKDIR /build
# В buildkit-сети IPv6 может зависать — принудительно IPv4;
# зеркало Aliyun — запасной канал до артефактов Central;
# wagon rto=45s — «зависшие» скачивания быстро падают и повторяются.
ENV MAVEN_OPTS="-Djava.net.preferIPv4Stack=true -Dmaven.wagon.rto=45000 -Dmaven.wagon.http.retryHandler.count=5"
COPY app/.m2-settings.xml /root/.m2/settings.xml
COPY app/pom.xml .
COPY app/src ./src
COPY --from=front /front/dist ./src/main/resources/static
RUN for i in 1 2 3 4 5 6; do \
      timeout 1500 mvn -B package -DskipTests && break || { echo "package retry $i"; sleep 5; }; \
    done && ls -la target/app.jar

# --- стадия 3: рантайм ---
FROM eclipse-temurin:11-jre-jammy
WORKDIR /app
COPY --from=build /build/target/app.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
