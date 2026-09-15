# Многостадийная сборка: Node (фронтенд) → Maven (Java) → JRE.
# Контекст сборки — КОРЕНЬ репозитория (нужен доступ к frontend/).
# На хосте ничего не нужно: всё собирается в контейнерах.
# ТЗ: Java 11; базовый образ — Ubuntu 22.04 (jammy).

# --- стадия 1: сборка фронтенда (React/Three.js + страница /dit) ---
FROM node:20-bookworm-slim AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- стадия 2: сборка Java-приложения со статикой фронтенда в jar ---
FROM maven:3.8.6-eclipse-temurin-11 AS build
WORKDIR /build
# В buildkit-сети IPv6 может зависать — принудительно IPv4;
# зеркало Aliyun — запасной канал до артефактов Central.
ENV MAVEN_OPTS="-Djava.net.preferIPv4Stack=true"
COPY app/.m2-settings.xml /root/.m2/settings.xml
COPY app/pom.xml .
RUN mvn -B dependency:go-offline
COPY app/src ./src
COPY --from=front /front/dist ./src/main/resources/static
RUN mvn -B package -DskipTests -o || mvn -B package -DskipTests

# --- стадия 3: рантайм ---
FROM eclipse-temurin:11-jre-jammy
WORKDIR /app
COPY --from=build /build/target/app.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
