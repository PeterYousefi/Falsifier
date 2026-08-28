# Release Checklist

This document lists every action required before final submission.
Check each item off in order.

---

## Demo video URL

The demo video URL is defined in **exactly one place**. Change it there and it
propagates automatically to all three references.

**Single source of truth:**

```
File : README.md
Line : 19
Token: __DEMO_VIDEO_URL__
```

To update:
1. Open `README.md`, line 19.
2. Replace `__DEMO_VIDEO_URL__` with the real URL (e.g. `https://youtu.be/...`).
3. Run `grep -rn "__DEMO_VIDEO_URL__"` — it should show the one definition in
   README.md plus references in:
   - `frontend/src/screens/JudgePage.tsx`
   - `frontend/src/screens/SystemScreen.tsx`
4. Run `npm run build` in `frontend/` to rebuild with the final URL baked in.
5. Deploy.

---

## Vercel project settings

The Vercel project must be configured with **Root Directory = `.` (repo root)** — this is
the default when the project is created from the GitHub repo directly.  A root-level
`vercel.json` handles the rest:

- `buildCommand`/`installCommand` — run `npm ci` and `npm run build` inside `frontend/`
- `outputDirectory` — `frontend/dist`
- `functions` — scopes the Python runtime to `frontend/api/chat.py` only
- `rewrites` — routes `/api/chat` to the function; SPA catch-all for all other paths
- `.vercelignore` — excludes `pyproject.toml` from the Vercel upload so the Python
  framework scanner doesn't try to deploy the FastAPI backend as a serverless function
  (the FastAPI backend runs on Fly.io/Docker, not Vercel)

**Do not** set Root Directory to `frontend/` — that would break the `/api/chat` function
path (it would be at `frontend/api/chat.py` relative to repo root, which maps to the
correct URL `/api/chat` only via the `rewrites` rule in the root `vercel.json`).

---

## Vercel Deployment Protection

⚠️ **Action required before judging:**

Verify that Vercel Deployment Protection is **disabled** (or set to allow unauthenticated
access) for the `falsifier.vercel.app` project:

1. Open [vercel.com/dashboard](https://vercel.com/dashboard) → Falsifier project → Settings → Deployment Protection.
2. Confirm "Vercel Authentication" is **off** — or that the production deployment is
   publicly accessible without sign-in.
3. If it is **on**, judges will receive HTTP 403 when opening `https://falsifier.vercel.app`.
   The CI `smoke-check` job will also fail.

*If you cannot verify this (no Vercel access at release time), flag the risk explicitly
in the submission README and provide a local fallback (`npm run dev` instructions).*

---

## Backend health

Confirm the IBM Cloud Code Engine backend is live:

```bash
curl -I https://<BACKEND_URL>/health
# Expected: HTTP/2 200
```

Replace `<BACKEND_URL>` with the value set in `VITE_API_BASE_URL` in Vercel project env vars.

---

## CI smoke check

The `smoke-check` CI job (`.github/workflows/ci.yml`) curls both:
- `https://falsifier.vercel.app` — the production frontend
- `https://<backend>/health` — the backend liveness probe

It fails on any non-200 response. Confirm it is green in GitHub Actions before submission.

---

## verify_readme.py

Run locally and confirm exit 0:

```bash
python3 scripts/verify_readme.py --strict
```

All 25 claim blocks must be OK.

---

## reproduce.sh

Run locally and confirm exit 0:

```bash
bash scripts/reproduce.sh --strict
```

---

## Judge path sanity check

1. Open `https://falsifier.vercel.app`.
2. Confirm the **Investigate** tab loads with the target input visible.
3. Enter `KIC 11904151` and click **Investigate →** (or the fixture button).
4. Confirm the four pipeline stages stream and a disposition is shown.
5. Click the **Judge** tab and confirm the walkthrough renders.
6. Click the **Gates** tab and confirm the defect log and mutation log render.
7. Click the **Try to break it** panel (reachable from the landing screen or Judge tab).
8. Confirm `/verify` endpoint returns JSON with per-claim status.
