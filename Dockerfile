# Falsifier — backend container
# Builds a production-ready image of the FastAPI pipeline server.
#
# System deps:
#   libomp-dev  — required by the XGBoost prebuilt wheel on Linux
#                 (libgomp1 from gcc-runtime is usually present on ubuntu
#                  but we pin libomp-dev explicitly to avoid silent breakage
#                  on future base images).
#
# Usage (local):
#   docker build -t falsifier-backend .
#   docker run -p 8000:8000 \
#     -e OPENAI_API_KEY=sk-... \
#     falsifier-backend
#
# IBM Code Engine deploy:
#   See deploy/code-engine.yaml for the Service manifest.

FROM python:3.11-slim

# --- system deps -------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    libomp-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# --- working directory -------------------------------------------------
WORKDIR /app

# --- Python deps (install before copying source so layer is cached) ----
COPY pyproject.toml ./
# Install all runtime + dev deps (dev includes fastapi, lightkurve, etc.)
RUN pip install --no-cache-dir -e ".[dev]"

# --- application source ------------------------------------------------
COPY . .

# --- non-root user -----------------------------------------------------
RUN useradd -m -u 1001 falsifier
USER falsifier

# --- runtime -----------------------------------------------------------
EXPOSE 8000

# CORS: the frontend origin is read from ALLOWED_ORIGINS at startup.
# Set it to your Vercel deployment URL, e.g.:
#   ALLOWED_ORIGINS=https://falsifier.vercel.app
# Defaults to "*" if unset (see falsifier/api/app.py).
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "falsifier.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
