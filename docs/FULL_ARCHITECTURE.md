# Architecture & Deployment

## Live application

**https://falsifier.vercel.app** — no account or API key required.

The Vite/React frontend calls a FastAPI backend deployed on
**IBM Cloud Code Engine** (`POST /jobs`, SSE streaming, `GET /health`).
Entering any valid Kepler or TESS catalogue identifier runs the
ingest → detrend → search → vet pipeline and returns a disposition.

### Architecture

| Layer | Where |
|---|---|
| Frontend | Vercel (static Vite/React build) |
| Backend | IBM Cloud Code Engine (single instance, always warm) |
| Cache | IBM Cloud File Storage volume mounted at `/data/cache/ingest` |
| API base URL | Set via `VITE_API_BASE_URL` in Vercel project env vars |
| Output screening | ibm-granite/granite-guardian-3.1-2b, local HuggingFace cache, `local_files_only=True` |

### Deployment constraints

- `min-scale=1`, `max-scale=1` — one instance always alive
- `request-timeout=600s` — long enough for a first-time MAST fetch plus TLS search
- `memory=4Gi` — TLS on a long Kepler LC peaks near 3 GB
- Concurrent jobs capped at 3; per-IP rate limit of 10 POST /jobs per minute
- CORS restricted to `https://falsifier.vercel.app` only

### Local setup

```bash
# Backend
pip install -e ".[dev]"
ALLOWED_ORIGINS="http://localhost:5173" uvicorn falsifier.api.app:app --reload

# Frontend (separate terminal)
cd frontend
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

---

## Repository layout

```
falsifier/api/
  app.py            FastAPI factory (lifespan, CORS, non-claim header)
  models.py         API-layer Pydantic models (JobRecord, DetectionReport, …)
  queue.py          Async job queue + 5-stage runner + stubs for unwired stages
  sse.py            SSE stream helper
  routes/
    jobs.py         POST /jobs · GET /jobs/{id} · GET /jobs/{id}/stream
    provenance.py   GET /provenance
    verify.py       GET /verify — live claim inventory (for judges)
    chat.py         POST /chat (tool-calling, Guardian-screened)

falsifier/pipeline/
  contracts/        Pydantic I/O models for all 7 stages
  ingest/           MAST · TAP · Gaia sources + content-addressed cache
  classify/         Feature extraction · GroupShuffleSplit · XGBoost training
  stages/
    ingest.py       Full stage body
    detrend.py      Full stage body — wotan biweight
    search.py       Full stage body — TLS limb-darkened profile
    vet.py          Full stage body — 7 independent modules; deterministic truth table
    classify.py     Full stage body (wired to API queue)
    retrieve.py     [EXPLORATORY] petitRADTRANS + dynesty + spot model
    disequilibrium.py  [EXPLORATORY] FastChem + VULCAN + Gibbs + source-flux ratio

data/
  golden/           Committed FITS files + provenance sidecars
  splits/           Committed train/test split indices
  targets/          Curated targets + MUSCLES UV spectra
  artifacts/        Pipeline output artifacts + stage explanations

scripts/
  fetch_golden.py               Fetch golden FITS from MAST (network required)
  injection_recovery.py         Completeness test (synthetic transit injection)
  adversarial_selftest.py       False-alarm rate self-attack
  verify_readme.py              Diff README claims against committed artifacts
  reproduce.sh                  Full reproducibility script
```

---

## API reference

```
POST   /jobs                   Enqueue a detection run; returns job_id
GET    /jobs/{id}              Poll status / fetch DetectionReport
GET    /jobs/{id}/stream       SSE stream of stage events (text/event-stream)
GET    /provenance             Live data versions, module wiring status, non-claims
GET    /verify                 Live claim inventory with per-claim pass/fail status
POST   /chat                   Tool-calling chat over pipeline artifacts (Guardian-screened)
GET    /health                 Liveness probe
```

Every response carries:
```
X-Non-Claim: Not a biosignature detector. No exoplanet biosignature has ever been confirmed.
```

---

## External data sources

All three external data services are publicly accessible without authentication:

| Service | Purpose | Endpoint |
|---|---|---|
| **MAST** (STScI) | Kepler/TESS light curve FITS | `https://mast.stsci.edu/api/v0/invoke` |
| **NASA Exoplanet Archive TAP** | Planet and stellar parameters | `https://exoplanetarchive.ipac.caltech.edu/TAP/sync` |
| **Gaia DR3 TAP+** (ESA) | Stellar RUWE, Teff, radius | `https://gea.esac.esa.int/tap-server/tap` |

The only optional credentials are `WATSONX_APIKEY`, `WATSONX_URL`, and
`WATSONX_PROJECT_ID` for the chat layer (IBM watsonx.ai ModelInference).
If absent, the endpoint degrades gracefully to templated stage explanations.

### DOIs per source

| Source | `source_doi` |
|---|---|
| MAST (Kepler mission) | `10.17909/t9-st5g-3177` |
| NASA Exoplanet Archive | `10.26133/NEA12` |
| Gaia DR3 | `10.1051/0004-6361/202243940` |

---

## Install prerequisites

### macOS
```bash
brew install libomp
pip install -e ".[dev]"
```

### Ubuntu / Debian
```bash
sudo apt-get install libomp-dev
pip install -e ".[dev]"
```

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 (CI: 3.11) |
| Web framework | FastAPI |
| Astronomy | astropy · lightkurve · wotan · transitleastsquares · astroquery |
| ML | xgboost |
| Chat inference | IBM watsonx.ai (`ibm-watsonx-ai`; `WATSONX_APIKEY`) |
| Testing | pytest |
| Frontend | Vite + React + Three.js |
| Retrieval *(exploratory)* | petitRADTRANS · dynesty |
| Chemistry *(exploratory)* | FastChem (pyfastchem) · VULCAN · MUSCLES HST spectra |
