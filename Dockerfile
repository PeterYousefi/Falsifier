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
#     -e WATSONX_APIKEY=... \
#     -e WATSONX_URL=... \
#     -e WATSONX_PROJECT_ID=... \
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

# --- Verify critical imports at build time -----------------------------
# If any of these cannot load (missing native deps, broken wheels) the
# build fails here rather than at the first user request.
RUN python -c "\
import xgboost; print('xgboost OK:', xgboost.__version__); \
import lightkurve; print('lightkurve OK:', lightkurve.__version__); \
import transitleastsquares; print('transitleastsquares OK'); \
import wotan; print('wotan OK'); \
"

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

# Single worker only — the in-process job store (_job_store in
# falsifier/api/queue.py) is held in memory.  Multiple workers would each
# hold a disjoint copy of the store, causing GET /jobs/{id} to 404
# intermittently on workers that did not create the job.
#
# Shell form (not exec form) so that ${PORT:-8000} expands at runtime.
# Fly.io injects PORT into the container environment; falling back to 8000
# keeps local docker run and Code Engine both working without the variable.
CMD uvicorn falsifier.api.app:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 1
