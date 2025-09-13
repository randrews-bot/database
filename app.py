import os
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from typing import Optional, List

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware

from settings import Settings, get_settings

app = FastAPI(title="Superior Property API", version="1.2.5")

# --- CORS: your domains only ---
ALLOWED_ORIGINS = [
        "https://api.superiorllc.org",
    "https://superior-property-api.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Helpers (DSN sanitizer / SSL enforcer / API key gate) ----------
async def fetch_rental_comps(address: str | None = None,
                             lat: float | None = None,
                             lng: float | None = None,
                             limit: int = 6) -> dict:
    if not RENTCAST_API_KEY:
        raise HTTPException(status_code=500, detail="RENTCAST_API_KEY not set")

    # Prefer address if you have it; otherwise require lat/lng
    params = {}
    if address:
        params["address"] = address
    elif lat is not None and lng is not None:
        params["latitude"] = lat
        params["longitude"] = lng
    else:
        raise HTTPException(status_code=400, detail="Provide address or latitude+longitude")

    # The AVM rent endpoint returns estimate + comps
    url = "https://api.rentcast.io/v1/avm/rent/long-term"
    headers = {"X-Api-Key": RENTCAST_API_KEY, "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=headers, params=params)

    if r.status_code == 404:
        # No comps/estimate available for the given location
        return {"estimate": None, "comps": [], "reason": "no results"}

    r.raise_for_status()
    data = r.json()
    # The docs show this endpoint returns the estimate and comparable listings
    # Pull the comps array field if present; otherwise default to empty.
    comps = data.get("comps") or data.get("comparableProperties") or []
    return {"estimate": data, "comps": comps}



def _sanitize_dsn(raw: str) -> str:
    """
    Accept common misconfigurations:
    - 'DATABASE_URL=postgresql://...' (strip leading 'DATABASE_URL=')
    - 'postgres://' -> normalize to 'postgresql://'
    """
    if not raw:
        return raw
    s = raw.strip().strip("\n").strip()
    low = s.lower()
    if low.startswith("database_url="):
        s = s.split("=", 1)[1].strip().strip("'").strip('"')
        low = s.lower()
    if low.startswith("postgres://"):
        s = "postgresql://" + s[len("postgres://"):]
    return s

def _ensure_ssl_in_query(url: str, sslmode_default: str = "require") -> str:
    try:
        u = urlparse(url)
        q = dict(parse_qsl(u.query, keep_blank_values=True))
        if not q.get("sslmode"):
            q["sslmode"] = sslmode_default
        return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), u.fragment))
    except Exception:
        # If not a URL (unlikely here), return original; we also pass sslmode kwarg in connect()
        return url

def require_api_key(
    settings: Settings = Depends(get_settings),
    x_api_key: Optional[str] = Header(default=None)
):
    if settings.API_KEY:
        if not x_api_key or x_api_key != settings.API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True

def get_conn(settings: Settings):
    """
    Prefer env DATABASE_URL; if missing, use the baked-in fallback (leave empty if you don't want a fallback).
    Always enforce SSL for hosted PostgreSQL.
    """
    fallback = "postgresql://superior_llc871_user:JYXMZRi7imWeH0Uz8X2pnA3ykyCz9CD5@dpg-d2oetb7fte5s7387rhcg-a.virginia-postgres.render.com/superior_llc871"
    dsn = _sanitize_dsn(settings.DATABASE_URL) or fallback
    dsn = _ensure_ssl_in_query(dsn, sslmode_default=(settings.PGSSLMODE or "require"))
    return psycopg2.connect(dsn, sslmode=(settings.PGSSLMODE or "require"))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS public.addresses (
  address_id SERIAL PRIMARY KEY,
  street1 TEXT,
  city TEXT,
  state_code CHAR(2),
  zip TEXT,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS public.properties (
  property_id SERIAL PRIMARY KEY,
  address_id INTEGER REFERENCES public.addresses(address_id) ON DELETE SET NULL,
  property_type TEXT,
  bedrooms NUMERIC,
  bathrooms NUMERIC,
  sqft_interior NUMERIC,
  zoning_code TEXT
);
CREATE TABLE IF NOT EXISTS public.images (
  image_id SERIAL PRIMARY KEY,
  property_id INTEGER REFERENCES public.properties(property_id) ON DELETE CASCADE,
  url TEXT,
  is_primary BOOLEAN DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS public.listings (
  listing_id SERIAL PRIMARY KEY,
  property_id INTEGER REFERENCES public.properties(property_id) ON DELETE CASCADE,
  price NUMERIC,
  tenure TEXT,
  status TEXT DEFAULT 'active',
  bedrooms NUMERIC,
  bathrooms NUMERIC,
  sqft_interior NUMERIC,
  url TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_status ON public.listings(status);
CREATE INDEX IF NOT EXISTS idx_properties_type ON public.properties(property_type);
CREATE INDEX IF NOT EXISTS idx_addresses_city ON public.addresses(city);
"""

@app.post("/admin/init", dependencies=[Depends(require_api_key)])
def admin_init(settings: Settings = Depends(get_settings)):
    try:
        with get_conn(settings) as conn, conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        return {"ok": True, "initialized": True}
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}



# ---------- DEFINE SQL CONSTANTS *BEFORE* routes/functions that use them ----------
LISTING_SELECT_DIRECT = """
SELECT
  l.listing_id AS id,
  l.property_id,
  p.property_type AS type,
  a.street1, a.city, a.state_code, a.zip,
  l.price, l.tenure,
  COALESCE(l.bedrooms, p.bedrooms) AS bedrooms,
  COALESCE(l.bathrooms, p.bathrooms) AS bathrooms,
  COALESCE(l.sqft_interior, p.sqft_interior) AS sqft,
  a.latitude AS lat, a.longitude AS lon,
  p.zoning_code,
  NULL::numeric AS crime_rate_per_1k,
  img.url AS image,
  l.url
FROM listings l
JOIN properties p ON p.property_id = l.property_id
LEFT JOIN addresses a ON a.address_id = p.address_id
LEFT JOIN LATERAL (
  SELECT i.url FROM images i WHERE i.property_id = p.property_id
  ORDER BY is_primary DESC NULLS LAST, image_id ASC LIMIT 1
) img ON true
WHERE l.status = 'active'
"""

# ---------- Filters helper ----------
def build_filters(
    q: Optional[str], prop_type: Optional[str], city: Optional[str],
    min_price: Optional[float], max_price: Optional[float],
    beds: Optional[float], baths: Optional[float]
):
    where: List[str] = []
    params: List = []
    if prop_type:
        where.append("p.property_type = %s"); params.append(prop_type)
    if city:
        where.append("a.city = %s"); params.append(city)
    if min_price is not None:
        where.append("l.price >= %s"); params.append(min_price)
    if max_price is not None:
        where.append("l.price <= %s"); params.append(max_price)
    if beds is not None:
        where.append("COALESCE(l.bedrooms, p.bedrooms) >= %s"); params.append(beds)
    if baths is not None:
        where.append("COALESCE(l.bathrooms, p.bathrooms) >= %s"); params.append(baths)
    if q:
        where.append("(COALESCE(a.street1,'') || ' ' || COALESCE(a.city,'') || ' ' || COALESCE(p.zoning_code,'') ILIKE %s)")
        params.append(f"%{q}%")
    return where, params

# ---------- Startup debug ----------
@app.on_event("startup")
def log_env_state():
    raw = os.getenv("DATABASE_URL", "")
    sanitized = _sanitize_dsn(raw) if raw else ""
    host = ""
    if sanitized and "://" in sanitized:
        try:
            host = urlparse(sanitized).hostname or ""
        except Exception:
            host = ""
    print("=== Startup Env Debug ===")
    print("DATABASE_URL present:", bool(raw))
    print("DATABASE_URL sanitized host:", host)
    print("PGHOST:", os.getenv("PGHOST"))
    print("PGDATABASE:", os.getenv("PGDATABASE"))
    print("PGUSER:", os.getenv("PGUSER"))
    print("PGSSLMODE:", os.getenv("PGSSLMODE"))
    print("=========================")

# ---------- Routes ----------
@app.get("/health")
def health():
    return {"ok": True, "version": "1.2.5", "origins": ALLOWED_ORIGINS}

@app.get("/diag", dependencies=[Depends(require_api_key)])
def diag(settings: Settings = Depends(get_settings)):
    out = {"origins": ALLOWED_ORIGINS, "using_env_database_url": bool(settings.DATABASE_URL)}
    try:
        with get_conn(settings) as conn, conn.cursor() as cur:
            cur.execute("SELECT version();")
            out["db_version"] = cur.fetchone()[0]
            cur.execute("""
                SELECT
                  to_regclass('public.listings') as listings,
                  to_regclass('public.properties') as properties,
                  to_regclass('public.addresses') as addresses
            """)
            r = cur.fetchone()
            out["objects"] = {"listings": r[0], "properties": r[1], "addresses": r[2]}
            for t in ["listings", "properties", "addresses"]:
                if out["objects"][t]:
                    cur.execute(f"SELECT count(*) FROM {t};")
                    out[f"count_{t}"] = cur.fetchone()[0]
    except Exception as e:
        import traceback
        out["error"] = str(e)
        out["trace"] = traceback.format_exc()
    return out

@app.get("/listings", dependencies=[Depends(require_api_key)])
def list_listings(
    q: Optional[str] = Query(default=None),
    prop_type: Optional[str] = Query(default=None, alias="type"),
    city: Optional[str] = Query(default=None),
    min_price: Optional[float] = Query(default=None),
    max_price: Optional[float] = Query(default=None),
    beds: Optional[float] = Query(default=None),
    baths: Optional[float] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings),
):
    where, params = build_filters(q, prop_type, city, min_price, max_price, beds, baths)
    sql = LISTING_SELECT_DIRECT + (" AND " + " AND ".join(where) if where else "") \
        + " ORDER BY l.price NULLS LAST, l.listing_id ASC LIMIT %s OFFSET %s"
    params = params + [limit, offset]
    try:
        with get_conn(settings) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception:
        raise HTTPException(status_code=500, detail="Query failed; check server logs or /diag")

    out = []
    for r in rows:
        title = ", ".join(filter(None, [r.pop("street1", None), r.get("city"), r.get("state_code"), r.get("zip")]))
        r["title"] = title
        r["beds"] = float(r.pop("bedrooms")) if r.get("bedrooms") is not None else None
        r["baths"] = float(r.pop("bathrooms")) if r.get("bathrooms") is not None else None
        out.append(r)
    return {"items": out, "count": len(out), "limit": limit, "offset": offset}

@app.get("/listings/{listing_id}", dependencies=[Depends(require_api_key)])
def get_listing(listing_id: int, settings: Settings = Depends(get_settings)):
    sql = LISTING_SELECT_DIRECT + " AND l.listing_id = %s LIMIT 1"
    try:
        with get_conn(settings) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (listing_id,))
            r = cur.fetchone()
    except Exception:
        raise HTTPException(status_code=500, detail="Query failed; check server logs or /diag")

    if not r:
        raise HTTPException(status_code=404, detail="Listing not found")

    title = ", ".join(filter(None, [r.pop("street1", None), r.get("city"), r.get("state_code"), r.get("zip")]))
    r["title"] = title
    r["beds"] = float(r.pop("bedrooms")) if r.get("bedrooms") is not None else None
    r["baths"] = float(r.pop("bathrooms")) if r.get("bathrooms") is not None else None
    return r
