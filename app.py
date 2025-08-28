from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from settings import Settings, get_settings

app = FastAPI(title="Superior Property API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_conn(settings: Settings):
    return psycopg2.connect(
        host=settings.PGHOST,
        port=settings.PGPORT,
        dbname=settings.PGDATABASE,
        user=settings.PGUSER,
        password=settings.PGPASSWORD,
    )

def require_api_key(settings: Settings = Depends(get_settings), x_api_key: Optional[str] = Header(default=None)):
    if settings.API_KEY:
        if not x_api_key or x_api_key != settings.API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/meta", dependencies=[Depends(require_api_key)])
def meta(settings: Settings = Depends(get_settings)):
    return {
        "name": "Superior Property API",
        "version": "1.0.0",
        "notes": "Listings with crime rate, zoning, primary image, and ≤1-mile park/school flags.",
        "proximity_radius_m": 1609.34,
    }

LISTING_SELECT = """
SELECT
  l.listing_id AS id,
  l.property_id,
  p.property_type AS type,
  a.street1, a.city, a.state_code, a.zip,
  l.price, l.tenure, l.bedrooms, l.bathrooms, l.sqft_interior AS sqft,
  a.latitude AS lat, a.longitude AS lon,
  p.zoning_code,
  c.rate_per_1k AS crime_rate_per_1k,
  img.url AS image,
  l.url,
  park.min_dist_m AS nearest_park_m,
  school.min_dist_m AS nearest_school_m,
  (park.min_dist_m IS NOT NULL AND park.min_dist_m <= 1609.34) AS has_park_within_1_mile,
  (school.min_dist_m IS NOT NULL AND school.min_dist_m <= 1609.34) AS has_school_within_1_mile
FROM mv_active_listings l
JOIN properties p ON p.property_id = l.property_id
LEFT JOIN addresses a ON a.address_id = p.address_id
LEFT JOIN v_place_latest_crime c ON c.place_id = (
  SELECT place_id FROM places WHERE name = a.city AND state_code = a.state_code LIMIT 1
)
LEFT JOIN LATERAL (
  SELECT i.url FROM images i WHERE i.property_id = p.property_id
  ORDER BY is_primary DESC NULLS LAST, image_id ASC LIMIT 1
) img ON true
LEFT JOIN LATERAL (
  SELECT MIN(ST_Distance(a.geom, amenities.geom))::double precision AS min_dist_m
  FROM amenities
  WHERE amenities.type = 'park' AND a.geom IS NOT NULL AND amenities.geom IS NOT NULL
) park ON true
LEFT JOIN LATERAL (
  SELECT MIN(ST_Distance(a.geom, schools.geom))::double precision AS min_dist_m
  FROM schools
  WHERE a.geom IS NOT NULL AND schools.geom IS NOT NULL
) school ON true
"""

def build_filters(q: Optional[str], typ: Optional[str], city: Optional[str],
                  min_price: Optional[float], max_price: Optional[float],
                  beds: Optional[float], baths: Optional[float]):
    where = ["l.status = 'active'"]
    params = []
    if typ:
        where.append("p.property_type = %s")
        params.append(typ)
    if city:
        where.append("a.city = %s")
        params.append(city)
    if min_price is not None:
        where.append("l.price >= %s")
        params.append(min_price)
    if max_price is not None:
        where.append("l.price <= %s")
        params.append(max_price)
    if beds is not None:
        where.append("l.bedrooms >= %s")
        params.append(beds)
    if baths is not None:
        where.append("l.bathrooms >= %s")
        params.append(baths)
    if q:
        where.append("(COALESCE(a.street1,'') || ' ' || COALESCE(a.city,'') || ' ' || COALESCE(p.zoning_code,'') ILIKE %s)")
        params.append(f"%{q}%")
    return where, params

@app.get("/listings", dependencies=[Depends(require_api_key)])
def list_listings(
    q: Optional[str] = Query(default=None, description="Keyword search across street/city/zoning"),
    type: Optional[str] = Query(default=None, description="property type: residential, commercial, rental, etc."),
    city: Optional[str] = Query(default=None),
    min_price: Optional[float] = Query(default=None),
    max_price: Optional[float] = Query(default=None),
    beds: Optional[float] = Query(default=None),
    baths: Optional[float] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings)
):
    where, params = build_filters(q, type, city, min_price, max_price, beds, baths)
    sql = LISTING_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY l.price NULLS LAST, l.listing_id ASC LIMIT %s OFFSET %s"
    params += [limit, offset]

    with get_conn(settings) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out = []
    for r in rows:
        title = ", ".join(filter(None, [r.pop("street1"), r.get("city"), r.get("state_code"), r.get("zip")]))
        r["title"] = title
        out.append(r)
    return {"items": out, "count": len(out), "limit": limit, "offset": offset}

@app.get("/listings/{listing_id}", dependencies=[Depends(require_api_key)])
def get_listing(listing_id: int, settings: Settings = Depends(get_settings)):
    sql = LISTING_SELECT + " WHERE l.listing_id = %s"
    with get_conn(settings) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (listing_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Listing not found")
        title = ", ".join(filter(None, [r.pop('street1'), r.get('city'), r.get('state_code'), r.get('zip')]))
        r["title"] = title
        return r

@app.get("/map/bounds", dependencies=[Depends(require_api_key)])
def listings_in_bounds(
    min_lat: float, min_lon: float, max_lat: float, max_lon: float,
    limit: int = Query(default=200, ge=1, le=500),
    settings: Settings = Depends(get_settings)
):
    bbox_sql = LISTING_SELECT + """
    WHERE l.status = 'active'
      AND a.geom IS NOT NULL
      AND ST_Intersects(a.geom::geometry, ST_SetSRID(ST_MakeEnvelope(%s,%s,%s,%s),4326))
    ORDER BY l.price NULLS LAST, l.listing_id ASC
    LIMIT %s
    """
    params = [min_lon, min_lat, max_lon, max_lat, limit]
    with get_conn(settings) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(bbox_sql, params)
        rows = cur.fetchall()
    out = []
    for r in rows:
        title = ", ".join(filter(None, [r.pop('street1'), r.get('city'), r.get('state_code'), r.get('zip')]))
        r["title"] = title
        out.append(r)
    return {"items": out, "count": len(out)}
