# Image Sentinel Brain — Sentinel-X (amd64 : PC sous Docker Desktop ; arm64 : Raspberry Pi 5)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY brain/ brain/
COPY app/ app/
# Utilisateur non root
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001
CMD ["python", "-m", "app.main"]
