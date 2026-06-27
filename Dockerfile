FROM python:3-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    LOG_LEVEL=info

WORKDIR /app

RUN addgroup --system bridge && adduser --system --ingroup bridge bridge

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir . && rm -rf /root/.cache

USER bridge
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8080\")}/health', timeout=3).read()"

CMD ["python", "-m", "zabbix_websocket_bridge.main"]
