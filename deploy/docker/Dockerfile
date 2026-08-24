FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_LEROBOT_HOME=/data

WORKDIR /opt/lekiwi
COPY . .
RUN python -m pip install --no-cache-dir ".[lekiwi]"

RUN useradd --create-home --uid 10001 lekiwi && mkdir -p /data && chown -R lekiwi:lekiwi /data /opt/lekiwi
USER lekiwi

EXPOSE 8090
ENTRYPOINT ["lerobot-lekiwi-diagnostics"]
CMD ["--host", "0.0.0.0", "--http-port", "8090", "--no-open"]
