# Многостадийная сборка: Maven на хосте не нужен (собираем в контейнере).
# ТЗ: Java 11; базовый образ — Ubuntu 22.04 (jammy).
FROM maven:3.8.6-eclipse-temurin-11 AS build
WORKDIR /build
# В buildkit-сети IPv6 может зависать — принудительно IPv4;
# зеркало Aliyun — запасной канал до артефактов Central.
ENV MAVEN_OPTS="-Djava.net.preferIPv4Stack=true"
COPY .m2-settings.xml /root/.m2/settings.xml
COPY pom.xml .
RUN mvn -B dependency:go-offline
COPY src ./src
RUN mvn -B package -DskipTests -o || mvn -B package -DskipTests

FROM eclipse-temurin:11-jre-jammy
WORKDIR /app
COPY --from=build /build/target/app.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
