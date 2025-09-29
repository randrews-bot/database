
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from webhook_stripe import router as stripe_webhook


app = FastAPI(title="safe-keeping-api")
app = FastAPI(title="Superior API")

origins = [o.strip() for o in os.getenv("CORS_ORIGINS","https://reports.superiorllc.org,https://superiorllc.org").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"ok": True, "message": "API is running"}
    
CORS_ORIGINS = ["https://superiorllc.org", "https://app.superiorllc.org"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stripe_webhook)


import os
import uuid
import time
import threading
from typing import Optional, Dict, Any

import stripe
import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel

# ---- Stripe init ----
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# ---- In-memory stores (replace with Redis in prod) ----
JOBS: Dict[str, Dict[str, Any]] = {}
REPORTS: Dict[str, Dict[str, Any]] = {}

class CreateSessionPayload(BaseModel):
    address: Optional[str] = None
    email: Optional[str] = None
    success_url: str
    cancel_url: str

class ConfirmPayload(BaseModel):
    session_id: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None

def enqueue_generate_report(address: Optional[str], email: Optional[str]) -> str:
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"state": "queued", "address": address, "email": email}
    th = threading.Thread(target=_run_report_job, args=(job_id,), daemon=True)
    th.start()
    return job_id

def _run_report_job(job_id: str):
    job = JOBS.get(job_id)
    if not job: 
        return
    job["state"] = "running"
    address = job.get("address")
    email = job.get("email")
    time.sleep(2)  # simulate work
    try:
        report = build_report(address=address, email=email)
        report_id = str(uuid.uuid4())
        REPORTS[report_id] = report
        job["state"] = "done"
        job["report_id"] = report_id
    except Exception as e:
        job["state"] = "error"
        job["error"] = str(e)

def build_report(address: Optional[str], email: Optional[str]) -> Dict[str, Any]:
    base = {"address": address or "Unknown", "email": email, "generated_at": int(time.time())}
    key = os.getenv("RENTCAST_API_KEY", "")
    if not key:
        base["source"] = "mock"
        base["rentcast"] = {"estimate": 1450, "confidence": 0.82}
        return base
    headers = {"X-Api-Key": key}
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get("https://api.rentcast.io/v1/properties", params={"address": address}, headers=headers)
            r.raise_for_status()
            prop = r.json()
    except Exception as e:
        base["source"] = "fallback-mock"
        base["rentcast"] = {"estimate": 1450, "error": str(e)}
        return base
    base["source"] = "rentcast"
    base["rentcast"] = prop
    return base

# ---- Routes (mounted on existing app) ----
@app.post("/checkout/sessions")
def checkout_sessions(payload: CreateSessionPayload):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured (STRIPE_SECRET_KEY)")
    try:
        price_id = os.getenv("STRIPE_PRICE_ID")
        if not price_id:
            raise HTTPException(status_code=500, detail="Missing STRIPE_PRICE_ID")
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
            metadata={"address": payload.address or "", "email": payload.email or ""},
            customer_email=payload.email,
            allow_promotion_codes=True,
        )
        return {"id": session.id, "url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/checkout/confirm")
def checkout_confirm(payload: ConfirmPayload):
    try:
        address = payload.address
        email = payload.email
        if payload.session_id:
            session = stripe.checkout.Session.retrieve(payload.session_id, expand=["payment_intent", "line_items"])
            if session.payment_status != "paid":
                raise HTTPException(status_code=400, detail="Payment not completed")
            md = session.get("metadata") or {}
            address = address or md.get("address")
            email = email or (session.get("customer_details") or {}).get("email")
        job_id = enqueue_generate_report(address=address, email=email)
        return {"status": "processing", "job_id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/reports/status")
def report_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"state": job["state"], "report_id": job.get("report_id"), "error": job.get("error")}

@app.get("/reports/{report_id}")
def report_get(report_id: str):
    rep = REPORTS.get(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Report not found")
    return rep

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        return {"ok": True, "skipped": "no webhook secret configured"}
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig, secret=secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook signature verification failed: {e}")
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        md = session.get("metadata") or {}
        address = md.get("address")
        email = (session.get("customer_details") or {}).get("email")
        enqueue_generate_report(address=address, email=email)
    return {"ok": True}



