# server/stripe_proxy.py
from fastapi import APIRouter, HTTPException, Query
import stripe, os

router = APIRouter()
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

@router.get("/stripe/session")
def get_session(session_id: str = Query(...)):
    try:
        s = stripe.checkout.Session.retrieve(session_id, expand=["customer", "payment_intent"])
        # Return only what the client needs
        return {
            "id": s.id,
            "amount_total": s.amount_total,
            "currency": s.currency,
            "status": s.status,
            "email": (s.get("customer_details") or {}).get("email"),
            "metadata": s.metadata or {},
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
