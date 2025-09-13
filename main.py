# main.py
import os
import datetime as dt
from typing import Optional, List, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

# ------------------------------------------------------------------------------
# Environment
# ------------------------------------------------------------------------------
ACS_YEAR = os.getenv("ACS_YEAR", "2022")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
RENTCAST_API_KEY = os.getenv("RENTCAST_API_KEY")

PORT = int(os.getenv("PORT", "10000"))
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS",
    "https://superiorllc.org,https://app.superiorllc.org"
).split(",")]

# ------------------------------------------------------------------------------
# App
# ------------------------------------------------------------------------------
app = FastAPI(title="safe-keeping-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------
class GenerateReportRequest(BaseModel): address: str email: EmailStr
  @app.post("/api/generate-report") async def generate_report(payload:
GenerateReportRequest): return {"ok": True, "echo": {"address": payload.address,
"email": payload.email}}
                                                              
# ------------------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------------------
def _date_str(d: dt.date) -> str:
    return d.strftime("%Y-%m-%d")

async def geocode(address: str) -> Dict[str, Any]:
    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY not set")
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": GOOGLE_MAPS_API_KEY}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
    data = r.json()
    result = (data.get("results") or [None])[0]
    if not result:
        raise HTTPException(status_code=404, detail="Address not found")
    loc = result["geometry"]["location"]
    return {
        "lat": loc["lat"],
        "lng": loc["lng"],
        "formattedAddress": result.get("formatted_address")
    }

async def fetch_property(address: str) -> Any:
    if not RENTCAST_API_KEY:
        raise HTTPException(status_code=500, detail="RENTCAST_API_KEY not set")
    url = "https://api.rentcast.io/v1/properties"
    headers = {"X-Api-Key": RENTCAST_API_KEY, "Accept": "application/json"}
    params = {"address": address}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=headers, params=params)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Rentcast error {r.status_code}")
    return r.json()

async def fetch_fbi_agencies(lat: float, lng: float) -> List[Dict[str, Any]]:
    # Try alternative param names used by the FBI SAPI
    urls = [
        ("https://api.usa.gov/crime/fbi/sapi/api/agencies/bylocation", {"lat": lat, "long": lng}),
        ("https://api.usa.gov/crime/fbi/sapi/api/agencies/bylocation", {"latitude": lat, "longitude": lng}),
    ]
    async with httpx.AsyncClient(timeout=12) as client:
        for base, params in urls:
            try:
                r = await client.get(base, params=params)
                if r.status_code < 400:
                    data = r.json()
                    items = data.get("agencies") if isinstance(data, dict) else data
                    agencies = [
                        {
                            "ori": a.get("ori"),
                            "agencyName": a.get("agency_name") or a.get("agencyName"),
                            "agencyType": a.get("agency_type") or a.get("agencyType"),
                            "city": a.get("city"),
                            "state": a.get("state_abbr") or a.get("stateAbbr"),
                        }
                        for a in (items or [])
                        if a and a.get("ori")
                    ]
                    seen, uniq = set(), []
                    for a in agencies:
                        if a["ori"] in seen:
                            continue
                        seen.add(a["ori"])
                        uniq.append(a)
                    return uniq[:15]
            except Exception:
                continue
    return []

async def fetch_crime(lat: float, lng: float, radius_miles: float = 3.0, days: int = 30) -> Dict[str, Any]:
    # Placeholder structure for now
    today = dt.date.today()
    start_30 = today - dt.timedelta(days=days)
    start_12m = (today.replace(day=1) - dt.timedelta(days=365)).replace(day=1)
    agencies = await fetch_fbi_agencies(lat, lng)
    return {
        "filters": {
            "center": {"lat": lat, "lng": lng},
            "radiusMiles": radius_miles,
            "last30d": {"from": _date_str(start_30), "to": _date_str(today)},
            "last12m": {"from": _date_str(start_12m), "to": _date_str(today)},
        },
        "summary": {
            "last30dTotal": 0,
            "trend12m": [],
            "byType": {},
        },
        "incidents": [],
        "fbiAgencies": agencies,
    }

async def get_fips_from_latlng(lat: float, lng: float) -> Dict[str, str]:
    url = "https://geo.fcc.gov/api/census/block/find"
    params = {"latitude": lat, "longitude": lng, "format": "json"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail="FCC FIPS lookup failed")
    data = r.json()
    blk = data.get("Block", {})
    fips = blk.get("FIPS")
    if not fips or len(fips) < 11:
        raise HTTPException(status_code=404, detail="FIPS not found")
    state = fips[0:2]
    county = fips[2:5]
    tract = fips[5:11]  # 6-digit tract code
    return {"state": state, "county": county, "tract": tract}

async def fetch_acs_demographics(state: str, county: str, tract: str) -> Dict[str, Any]:
    base = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
    vars_ = ["NAME", "B19013_001E", "B25003_001E", "B25003_002E", "B25003_003E"]
    params = {
        "get": ",".join(vars_),
        "for": f"tract:{tract}",
        "in": f"state:{state} county:{county}",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(base, params=params)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"ACS error {r.status_code}")
    rows = r.json()
    if not rows or len(rows) < 2:
        raise HTTPException(status_code=404, detail="ACS data not found")
    hdr, val = rows[0], rows[1]
    rec = {hdr[i]: val[i] for i in range(len(hdr))}

    def num(x):
        try:
            return float(x)
        except Exception:
            return None

    median_income = num(rec.get("B19013_001E"))
    occ_total = num(rec.get("B25003_001E")) or 0
    owner = num(rec.get("B25003_002E")) or 0
    renter = num(rec.get("B25003_003E")) or 0
    owner_pct = (owner / occ_total) if occ_total else None
    renter_pct = (renter / occ_total) if occ_total else None

    return {
        "name": rec.get("NAME"),
        "medianHouseholdIncome": median_income,
        "tenure": {"ownerPct": owner_pct, "renterPct": renter_pct},
        "fips": {
            "state": rec.get("state"),
            "county": rec.get("county"),
            "tract": rec.get("tract"),
        },
        "acsYear": ACS_YEAR,
    }

# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def root():
    # Nice landing so "/" isn't 404
    return JSONResponse({"ok": True, "service": "superior API", "docs": "/docs"})

@app.get("/health", include_in_schema=False)
async def health():
    return {"ok": True, "app": "safe-keeping-api"}

@app.post("/api/generate-report")
async def generate_report(payload: GenerateReportRequest):
    # 1) Geocode
    geo = await geocode(payload.address)
    # 2) Property basics
    prop = await fetch_property(payload.address)
    # 3) Census geo → ACS
    fips = await get_fips_from_latlng(geo["lat"], geo["lng"])
    demo = await fetch_acs_demographics(fips["state"], fips["county"], fips["tract"])
    # 4) (Optional) Crime scaffold
    crime = await fetch_crime(geo["lat"], geo["lng"])

    return {
        "ok": True,
        "step": "geocode+property+demographics+crime",
        "address": payload.address,
        "email": payload.email,
        "geo": geo,
        "property": prop,
        "demographics": demo,
        "crime": crime,
    }
from pydantic import BaseModel, EmailStr
class GenerateReportV2(BaseModel): address: str email: EmailStr
@app.post("/api/v2/generate-report") async def generate_report_v2(payload:
GenerateReportV2): return {"ok": True, "v": 2, "echo": {"address": payload.address,
"email": payload.email}}
import os ALLOWED = set(e.strip().lower() for e in os.getenv("ALLOW_EMAILS","").split(",") if e.strip())

