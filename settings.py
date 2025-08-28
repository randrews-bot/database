from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PGHOST: str = "localhost"
    PGPORT: int = 5432
    PGDATABASE: str = "superior_property_db"
    PGUSER: str = "postgres"
    PGPASSWORD: str = "postgres"
    API_KEY: str = ""  # optional; set to require X-API-Key

    class Config:
        env_file = ".env"

def get_settings() -> "Settings":
    return Settings()
