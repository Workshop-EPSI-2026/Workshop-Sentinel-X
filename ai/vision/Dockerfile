# Image vision — Sentinel-X, pour Linux et Raspberry Pi 5 (arm64) uniquement.
# Sous Windows (Docker Desktop), la webcam n'est pas accessible aux conteneurs : la vision tourne sur le PC
# (tools\demarrer.ps1). Activée par infra/docker-compose.linux.yml.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY torch-cpu.txt requirements.txt ./
# PyTorch en version CPU (pas de paquets NVIDIA), versions figées dans torch-cpu.txt
RUN pip install -r torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt
COPY app/ app/
# Utilisateur non root
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001
EXPOSE 8001
CMD ["python", "-m", "app.main"]
