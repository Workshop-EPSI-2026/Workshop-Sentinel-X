# Image vision — Sentinel-X (arm64 : Raspberry Pi 5 et Pi 4 de repli ; amd64 : postes)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY torch-cpu.txt requirements.txt ./
# PyTorch en version CPU (pas de paquets NVIDIA sur le Pi), versions figées dans torch-cpu.txt
RUN pip install -r torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt
COPY . .
# Utilisateur non root
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
