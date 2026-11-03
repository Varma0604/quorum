import os


def _database_url() -> str:
    """Normalize managed-Postgres URLs for SQLAlchemy's installed psycopg driver."""
    value = os.getenv("DATABASE_URL", "sqlite:///./quorum.db")
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    return value


DATABASE_URL = _database_url()
JWT_SECRET = os.getenv("JWT_SECRET", "local-development-only-change-me")
JWT_ISSUER = os.getenv("JWT_ISSUER", "quorum-local")
REDIS_URL = os.getenv("REDIS_URL")

