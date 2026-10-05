# Image anomaly — Sentinel-X (arm64 : Raspberry Pi 5 et Pi 4 de repli ; amd64 : postes)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN mkdir -p /models && chown 10001 /models
# Utilisateur non root
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001

CMD ["python", "-m", "app.main"]
