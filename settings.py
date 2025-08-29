from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str | None = None
    PGHOST: str | None = None
    PGPORT: int = 5432
    PGDATABASE: str | None = None
    PGUSER: str | None = None
    PGPASSWORD: str | None = None
    PGSSLMODE: str = 'require'
    API_KEY: str = ''

    class Config:
        env_file = '.env'

def get_settings() -> 'Settings':
    return Settings()