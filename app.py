import os
from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import psycopg2, traceback
from psycopg2.extras import RealDictCursor
from settings import Settings, get_settings

app = FastAPI(title='Superior Property API', version='1.2.3')

def _sanitize_dsn(raw: str) -> str:
    s = (raw or "").strip()
    low = s.lower()
    # Strip a leading "DATABASE_URL=" if someone pasted "DATABASE_URL=postgresql://..."
    if low.startswith("database_url="):
        s = s.split("=", 1)[1].strip().strip("'").strip('"')
        low = s.lower()
    # Normalize postgres -> postgresql scheme
    if low.startswith("postgres://"):
        s = "postgresql://" + s[len("postgres://"):]
    return s

ALLOWED_ORIGINS = [
    'https://www.superiorllc.org',
    'https://superiorllc.org',
    'https://api.superiorllc.org',
    'https://superior-property-api.onrender.com',
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

@app.on_event('startup')
def log_env_state():
    print('=== Startup Env Debug ===')
    print('DATABASE_URL present:', bool(os.getenv('DATABASE_URL')))
    print('PGHOST:', os.getenv('PGHOST'))
    print('PGDATABASE:', os.getenv('PGDATABASE'))
    print('PGUSER:', os.getenv('PGUSER'))
    print('PGSSLMODE:', os.getenv('PGSSLMODE'))
    print('=========================')

def get_conn(settings: Settings):
    dsn = settings.DATABASE_URL or 'postgresql://superior_llc871_user:JYXMZRi7imWeH0Uz8X2pnA3ykyCz9CD5@dpg-d2oetb7fte5s7387rhcg-a.virginia-postgres.render.com/superior_llc871'
    sslmode = settings.PGSSLMODE or 'require'
    return psycopg2.connect(dsn, sslmode=sslmode)

def require_api_key(settings: Settings = Depends(get_settings), x_api_key: Optional[str] = Header(default=None)):
    if settings.API_KEY:
        if not x_api_key or x_api_key != settings.API_KEY:
            raise HTTPException(status_code=401, detail='Invalid or missing API key')
    return True

@app.get('/health')
def health():
    return {'ok': True, 'version': '1.2.3', 'origins': ALLOWED_ORIGINS}

@app.get('/diag', dependencies=[Depends(require_api_key)])
def diag(settings: Settings = Depends(get_settings)):
    out = {'origins': ALLOWED_ORIGINS, 'using_env_database_url': bool(settings.DATABASE_URL)}
    try:
        with get_conn(settings) as conn, conn.cursor() as cur:
            cur.execute('SELECT version();')
            out['db_version'] = cur.fetchone()[0]
            cur.execute("""
                SELECT
                  to_regclass('public.listings') as listings,
                  to_regclass('public.properties') as properties,
                  to_regclass('public.addresses') as addresses
            """)
            r = cur.fetchone()
            out['objects'] = {'listings': r[0], 'properties': r[1], 'addresses': r[2]}
            for t in ['listings','properties','addresses']:
                if out['objects'][t]:
                    cur.execute(f'SELECT count(*) FROM {t};')
                    out[f'count_{t}'] = cur.fetchone()[0]
    except Exception as e:
        out['error'] = str(e)
        out['trace'] = traceback.format_exc()
    return out

LISTING_SELECT_DIRECT = '''SELECT\n  l.listing_id AS id,\n  l.property_id,\n  p.property_type AS type,\n  a.street1, a.city, a.state_code, a.zip,\n  l.price, l.tenure,\n  COALESCE(l.bedrooms, p.bedrooms) AS bedrooms,\n  COALESCE(l.bathrooms, p.bathrooms) AS bathrooms,\n  COALESCE(l.sqft_interior, p.sqft_interior) AS sqft,\n  a.latitude AS lat, a.longitude AS lon,\n  p.zoning_code,\n  NULL::numeric AS crime_rate_per_1k,\n  img.url AS image,\n  l.url\nFROM listings l\nJOIN properties p ON p.property_id = l.property_id\nLEFT JOIN addresses a ON a.address_id = p.address_id\nLEFT JOIN LATERAL (\n  SELECT i.url FROM images i WHERE i.property_id = p.property_id\n  ORDER BY is_primary DESC NULLS LAST, image_id ASC LIMIT 1\n) img ON true\nWHERE l.status = 'active''''

def build_filters(q: Optional[str], typ: Optional[str], city: Optional[str],
                  min_price: Optional[float], max_price: Optional[float],
                  beds: Optional[float], baths: Optional[float]):
    where = []
    params: List = []
    if typ:
        where.append('p.property_type = %s'); params.append(typ)
    if city:
        where.append('a.city = %s'); params.append(city)
    if min_price is not None:
        where.append('l.price >= %s'); params.append(min_price)
    if max_price is not None:
        where.append('l.price <= %s'); params.append(max_price)
    if beds is not None:
        where.append('COALESCE(l.bedrooms, p.bedrooms) >= %s'); params.append(beds)
    if baths is not None:
        where.append('COALESCE(l.bathrooms, p.bathrooms) >= %s'); params.append(baths)
    if q:
        where.append("(COALESCE(a.street1,'') || ' ' || COALESCE(a.city,'') || ' ' || COALESCE(p.zoning_code,'') ILIKE %s)")
        params.append(f'%{q}%')
    return where, params

@app.get('/listings', dependencies=[Depends(require_api_key)])
def list_listings(
    q: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
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
    sql = LISTING_SELECT_DIRECT + (' AND ' + ' AND '.join(where) if where else '') + ' ORDER BY l.price NULLS LAST, l.listing_id ASC LIMIT %s OFFSET %s'
    params = params + [limit, offset]
    try:
        with get_conn(settings) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception as e:
        print('ERROR /listings:', e); traceback.print_exc()
        raise HTTPException(status_code=500, detail='Query failed; check server logs or /diag')

    out = []
    for r in rows:
        title = ', '.join(filter(None, [r.pop('street1', None), r.get('city'), r.get('state_code'), r.get('zip')]))
        r['title'] = title
        r['beds'] = float(r.pop('bedrooms')) if r.get('bedrooms') is not None else None
        r['baths'] = float(r.pop('bathrooms')) if r.get('bathrooms') is not None else None
        out.append(r)
    return {'items': out, 'count': len(out), 'limit': limit, 'offset': offset}

@app.get('/listings/{listing_id}', dependencies=[Depends(require_api_key)])
def get_listing(listing_id: int, settings: Settings = Depends(get_settings)):
    sql = LISTING_SELECT_DIRECT + ' AND l.listing_id = %s LIMIT 1'
    try:
        with get_conn(settings) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (listing_id,))
            r = cur.fetchone()
    except Exception as e:
        print('ERROR /listings/{listing_id}:', e); traceback.print_exc()
        raise HTTPException(status_code=500, detail='Query failed; check server logs or /diag')
    if not r:
        raise HTTPException(status_code=404, detail='Listing not found')
    title = ', '.join(filter(None, [r.pop('street1', None), r.get('city'), r.get('state_code'), r.get('zip')]))
    r['title'] = title
    r['beds'] = float(r.pop('bedrooms')) if r.get('bedrooms') is not None else None
    r['baths'] = float(r.pop('bathrooms')) if r.get('bathrooms') is not None else None
    return r
