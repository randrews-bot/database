# server/webhook_stripe.py
import os, json, stripe, hmac, hashlib
from fastapi import APIRouter, Request, HTTPException
from starlette.responses import JSONResponse

router = APIRouter()
stripe.api_key = os.environ["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
"]
WEBHOOK_SECRET = os.environ["whsec_sjkwNny2EQ8vGHKCY65opNuZJIenDJnG"]  # from Stripe dashboard

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=sig_header, secret=whsec_sjkwNny2EQ8vGHKCY65opNuZJIenDJnG

        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {e}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = (session.get("customer_details") or {}).get("email") or session.get("customer_email")
        meta = session.get("metadata") or {}
        address = meta.get("address")
        report_kind = meta.get("report_kind", "full")

        # 1) Create a report record (PENDING)
        # You likely have a DB function for this:
        # report_id = create_report_record(email=email, address=address, kind=report_kind)
        report_id = await start_report_job(email=email, address=address, kind=report_kind)  # implement
        # 2) Optional: email confirmation “we’re generating your report”
        # send_email(email, f"Report started for {address}", ...)

        # 3) Attach report_id back to session in your DB if needed
        # save_session_report_map(session["id"], report_id)

    return JSONResponse({"ok": True})
