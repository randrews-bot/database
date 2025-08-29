Superior Property API — FINAL bundle (v1.2.3)
Service URLs
- Render: https://superior-property-api.onrender.com
- Custom: https://api.superiorllc.org

What’s included
- Startup env debug in logs (confirms env vars).
- Uses env DATABASE_URL; else falls back to baked-in DSN provided by you.
- Forces sslmode=require for hosted PG.
- CORS: api.superiorllc.org, superiorllc.org, and Render URL.
- Minimal queries (no PostGIS/views required).

Render environment (optional but recommended)
- Set DATABASE_URL to override baked-in URL:
  postgresql://USER:PASS@HOST:5432/DB?sslmode=require
- Optional: API_KEY (if set, client must send X-API-Key)

Endpoints
- GET /health
- GET /diag
- GET /listings
- GET /listings/{id}

Wix fetch example
-----------------
<script>
const API_URL = 'https://api.superiorllc.org/listings?limit=200';
const API_KEY = ''; // set if you configured API_KEY on the API
async function load() {
  const headers = API_KEY ? { 'X-API-Key': API_KEY } : {};
  const r = await fetch(API_URL, { headers });
  const data = await r.json();
  console.log('API items:', data.items);
}
load();
</script>