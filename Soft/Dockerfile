# ── Backend Dockerfile ────────────────────────────────────────────────────────
# Multi-stage build: builder installs deps, final image is slim.
#
# Build:   docker build -t smarthospital-backend .
# Run:     docker run -p 5000:5000 --env-file .env smarthospital-backend

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# Create necessary directories
RUN mkdir -p uploads/reports face_store

# Pre-download FaceNet weights at build time (avoids first-request latency)
RUN python -c "from facenet_pytorch import InceptionResnetV1; InceptionResnetV1(pretrained='vggface2')" \
    || echo "FaceNet weights will be downloaded on first use"

ENV FLASK_ENV=production
ENV PORT=5000

EXPOSE 5000

CMD ["python", "run.py"]
