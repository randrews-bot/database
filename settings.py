from pydantic import BaseSettings

class Settings(BaseSettings):
    PGHOST: str = 'localhost'
    PGPORT: int = 5432
    PGDATABASE: str = 'superior_property_db'
    PGUSER: str = 'postgres'
    PGPASSWORD: str = 'postgres'
    API_KEY: str = ''
    class Config:
        env_file = '.env'

def get_settings() -> 'Settings':
    return Settings()
