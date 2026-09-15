# Внутренний вычислительный движок (geo-engine).
# Порт не публикуется наружу — см. docker-compose.yml.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY requirements.txt .
# wheelhouse/ — локальные wheel-пакеты (не коммитятся, см. .gitignore).
# Если каталог заполнен — ставим офлайн; иначе — из сети (с запасными зеркалами).
COPY wheelhouse/ /wheels/
RUN if ls /wheels/*.whl >/dev/null 2>&1; then \
        pip install --no-index --find-links=/wheels -r requirements.txt; \
    else \
        pip install --default-timeout=180 --retries=10 -r requirements.txt \
        || pip install --default-timeout=180 --retries=10 \
           -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt \
        || pip install --default-timeout=180 --retries=10 \
           -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt; \
    fi
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
