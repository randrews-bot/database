Render-ready FastAPI (v1.2.0)
1) Set env vars on Render (Service → Settings → Environment):
   - DATABASE_URL=postgres://USER:PASS@HOST:5432/DB?sslmode=require
     (or PGHOST/PGDATABASE/PGUSER/PGPASSWORD/PGSSLMODE=require)
   - API_KEY=<optional>
2) Redeploy.
3) Test:
   - /health
   - /diag (requires X-API-Key if API_KEY set)
   - /listings?limit=1
CORS allowed origins:
  https://www.superiorllc.org, https://superiorllc.org, https://superior-property-api.onrender.com
