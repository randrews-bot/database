main.py import os from fastapi import FastAPI, HTTPException from fastapi.middleware.cors import CORSMiddleware from pydantic import BaseModel, EmailStr

PORT = int(os.getenv("PORT", "10000")) CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "https://superiorllc.org,https://app.superiorllc.org").split(",")]

app = FastAPI(title="safe-keeping-api")

app.add_middleware( CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=[""], allow_headers=[""], )

class GenerateReportRequest(BaseModel): address: str email: EmailStr

@app.get("/health") async def health(): return {"ok": True, "app": "safe-keeping-api"}

@app.post("/api/generate-report") async def generate_report(payload: GenerateReportRequest): # Stub for wiring Zapier; next step we add geocode + data fetch + PDF + email return { "ok": True, "message": "Stub OK — backend reachable. Next step: geocode + data fetch.", "address": payload.address, "email": payload.email }

Add the imports and env reads near the top: import httpx GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY") RENTCAST_API_KEY = os.getenv("RENTCAST_API_KEY")

Add these helpers below your models: async def geocode(address: str): if not GOOGLE_MAPS_API_KEY: raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY not set") url = "https://maps.googleapis.com/maps/api/geocode/json" params = {"address": address, "key": GOOGLE_MAPS_API_KEY} async with httpx.AsyncClient(timeout=10) as client: r = await client.get(url, params=params) data = r.json() result = (data.get("results") or [None])[0] if not result: raise HTTPException(status_code=404, detail="Address not found") loc = result["geometry"]["location"] return {"lat": loc["lat"], "lng": loc["lng"], "formattedAddress": result.get("formatted_address")}

async def fetch_property(address: str): if not RENTCAST_API_KEY: raise HTTPException(status_code=500, detail="RENTCAST_API_KEY not set") url = "https://api.rentcast.io/v1/properties" headers = {"X-Api-Key": RENTCAST_API_KEY, "Accept": "application/json"} params = {"address": address} async with httpx.AsyncClient(timeout=15) as client: r = await client.get(url, headers=headers, params=params) if r.status_code >= 400: raise HTTPException(status_code=502, detail=f"Rentcast error {r.status_code}") return r.json()

Update the /api/generate-report endpoint body: @app.post("/api/generate-report") async def generate_report(payload: GenerateReportRequest): geo = await geocode(payload.address) prop = await fetch_property(payload.address) return { "ok": True, "step": "geocode+property", "address": payload.address, "email": payload.email, "geo": geo, "property": prop }