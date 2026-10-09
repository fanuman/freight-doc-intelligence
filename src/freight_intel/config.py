from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_db: str
    app_db_user: str
    app_db_password: str
    db_host: str = "localhost"
    db_port: int = 5433
    jwt_secret: str  # signs login tokens; generate with: openssl rand -hex 32
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    @property
    def owner_url(self) -> URL:
        """Used only by migrations and test seeding. Bypasses RLS."""
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.db_host,
            port=self.db_port,
            database=self.postgres_db,
        )

    @property
    def app_url(self) -> URL:
        """Used by the API. Subject to RLS."""
        return URL.create(
            "postgresql+psycopg",
            username=self.app_db_user,
            password=self.app_db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()