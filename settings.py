from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Prefer DATABASE_URL if provided (e.g., from Render)
    DATABASE_URL: https://superior-property-api.onrender.com/ | None = None

    # Or individual params:
    PGHOST: str | None = None
    PGPORT: int = 5432
    PGDATABASE: str | None = None
    PGUSER: str | None = None
    PGPASSWORD: str | None = None

    # Many managed DBs require SSL
    PGSSLMODE: str = "require"  # "disable" for local dev

    API_KEY: str = ""  # optional

    class Config:
        env_file = ".env"

def get_settings() -> "Settings":
    return Settings()
