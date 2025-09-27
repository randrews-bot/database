
# API Repairs — Stripe Checkout + Report Generation

Changes made:
- Added **/checkout/sessions**, **/checkout/confirm**, **/reports/status**, **/reports/{report_id}**, and **/webhooks/stripe** endpoints.
- Ensured **CORS** allows `https://reports.superiorllc.org, https://superiorllc.org` via `CORS_ORIGINS` env.
- Updated `requirements.txt` to include `fastapi`, `uvicorn[standard]`, `stripe`, and `httpx`.
- Included `.env.example` with required keys.

## Start
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Notes
- The job & report stores are **in-memory**; swap for Redis in production.
- Keep **Stripe** and **RentCast** keys **server-side** only.
