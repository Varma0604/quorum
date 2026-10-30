import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./quorum.db")
JWT_SECRET = os.getenv("JWT_SECRET", "local-development-only-change-me")
JWT_ISSUER = os.getenv("JWT_ISSUER", "quorum-local")
REDIS_URL = os.getenv("REDIS_URL")
