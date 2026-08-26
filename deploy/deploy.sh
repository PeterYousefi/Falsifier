#!/usr/bin/env bash
# deploy/deploy.sh
# Complete IBM Cloud Code Engine deploy script for the Falsifier backend.
#
# References used:
#   ibmcloud ce application create / update / get
#   https://cloud.ibm.com/docs/codeengine?topic=codeengine-cli#cli-application-create
#   ibmcloud ce persistentvolumeclaim create
#   https://cloud.ibm.com/docs/codeengine?topic=codeengine-cli#cli-persistentvolumeclaim-create
#
# Non-negotiable constraints encoded below:
#   --min-scale 1 --max-scale 1   (_job_store is per-process in-memory)
#   --request-timeout 600         (MAST fetch + TLS search < 10 min)
#   --memory 4G                   (TLS on long Kepler LC peaks ~3 GB)
#
# Usage:
#   1. Fill in the required variables at the top of this file.
#   2. Run: bash deploy/deploy.sh

set -euo pipefail

# ── Required: fill these in ──────────────────────────────────────────────
REGISTRY="private.icr.io"          # IBM Container Registry domain
NAMESPACE="your-namespace"          # ICR namespace you have push access to
IMAGE_TAG="latest"                  # Image tag
CE_PROJECT="your-project-name"      # Code Engine project to deploy into
CE_REGION="us-south"                # IBM Cloud region (e.g. us-south, eu-de)
# ────────────────────────────────────────────────────────────────────────

IMAGE="${REGISTRY}/${NAMESPACE}/falsifier-backend:${IMAGE_TAG}"
APP_NAME="falsifier-backend"
PVC_NAME="falsifier-cache-pvc"

echo "=== Falsifier backend deploy ==="
echo "  Image   : ${IMAGE}"
echo "  Project : ${CE_PROJECT}"
echo "  Region  : ${CE_REGION}"
echo ""

# ── 0. Ensure plugin is installed ───────────────────────────────────────
if ! ibmcloud ce version &>/dev/null; then
  echo "[1/7] Installing ibmcloud code-engine plugin..."
  ibmcloud plugin install code-engine -f
else
  echo "[1/7] code-engine plugin already installed."
fi

# ── 1. Login + select region ─────────────────────────────────────────────
echo "[2/7] Logging in to IBM Cloud (region: ${CE_REGION})..."
ibmcloud login --no-region -r "${CE_REGION}"

# ── 2. Select Code Engine project ────────────────────────────────────────
echo "[3/7] Selecting project ${CE_PROJECT}..."
ibmcloud ce project select --name "${CE_PROJECT}"

# ── 3. Build and push the Docker image ────────────────────────────────────
echo "[4/7] Building and pushing Docker image to ${IMAGE}..."
# Log in to ICR
ibmcloud cr login
# Build from repo root (Dockerfile is at the root)
docker build -t "${IMAGE}" "$(git rev-parse --show-toplevel)"
# Verify xgboost imports successfully before pushing
echo "  Verifying xgboost import inside built image..."
docker run --rm "${IMAGE}" python -c "import xgboost; print('xgboost OK:', xgboost.__version__)"
# Push
docker push "${IMAGE}"

# ── 4. Provision persistent volume claim for the ingest cache ────────────
echo "[5/7] Provisioning PVC ${PVC_NAME} (10 Gi)..."
if ibmcloud ce persistentvolumeclaim get --name "${PVC_NAME}" &>/dev/null; then
  echo "  PVC ${PVC_NAME} already exists — skipping."
else
  ibmcloud ce persistentvolumeclaim create \
    --name "${PVC_NAME}" \
    --request-storage 10Gi
fi

# ── 5. Create or update the application ──────────────────────────────────
echo "[6/7] Deploying application ${APP_NAME}..."

# Flags explained:
#   --min-scale 1        Keep exactly one instance alive (no cold starts;
#                        _job_store is per-process in-memory).
#   --max-scale 1        Prevent a second instance from being spawned
#                        (which would lose all queued jobs on routing).
#   --request-timeout 600  Allow SSE stream to stay open through a full run
#                        (MAST fetch 30–120 s + TLS search ≤ 5 min).
#   --memory 4G          TLS on a 4-year Kepler long-cadence LC peaks ~3 GB.
#   --cpu 2              Match resource limit in code-engine.yaml.
#   --env ALLOWED_ORIGINS  Restrict CORS to the Vercel frontend only.
#   --env FALSIFIER_CACHE_ROOT  Point ingest cache at the mounted volume.
#   --mount-configmap / --mount-secret  Not used here; see secrets section.
#   --volume ...         Mount the PVC at /data/cache.

DEPLOY_FLAGS=(
  --name "${APP_NAME}"
  --image "${IMAGE}"
  --min-scale 1
  --max-scale 1
  --request-timeout 600
  --memory 4G
  --cpu 2
  --port 8000
  --env PYTHONUNBUFFERED=1
  --env "ALLOWED_ORIGINS=https://falsifier.vercel.app"
  --env "FALSIFIER_CACHE_ROOT=/data/cache/ingest"
  --volume "${PVC_NAME}:/data/cache:ReadWriteMany"
)

if ibmcloud ce application get --name "${APP_NAME}" &>/dev/null; then
  echo "  Application exists — updating..."
  ibmcloud ce application update "${DEPLOY_FLAGS[@]}"
else
  echo "  Application does not exist — creating..."
  ibmcloud ce application create "${DEPLOY_FLAGS[@]}"
fi

# ── 6. Print endpoint and next steps ─────────────────────────────────────
echo "[7/7] Retrieving application URL..."
APP_URL=$(ibmcloud ce application get --name "${APP_NAME}" --output json \
  | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['status']['url'])" 2>/dev/null || echo "")

if [[ -n "${APP_URL}" ]]; then
  echo ""
  echo "=== Deploy complete ==="
  echo "  Backend URL : ${APP_URL}"
  echo ""
  echo "Next steps:"
  echo "  1. In your Vercel project settings, add the environment variable:"
  echo "       VITE_API_BASE_URL=${APP_URL}"
  echo "     Then redeploy the frontend."
  echo ""
  echo "  2. Inject watsonx.ai credentials as a Code Engine secret:"
  echo "       ibmcloud ce secret create --name falsifier-secrets \\"
  echo "         --from-literal WATSONX_APIKEY=... \\"
  echo "         --from-literal WATSONX_URL=https://us-south.ml.cloud.ibm.com \\"
  echo "         --from-literal WATSONX_PROJECT_ID=..."
  echo "     Then update the app to reference it:"
  echo "       ibmcloud ce application update \\"
  echo "         --name ${APP_NAME} \\"
  echo "         --env-from-secret falsifier-secrets"
  echo ""
  echo "  3. Smoke test:"
  echo "       curl ${APP_URL}/health"
else
  echo ""
  echo "=== Deploy complete (URL not retrieved automatically) ==="
  echo "  Run: ibmcloud ce application get --name ${APP_NAME}"
fi
