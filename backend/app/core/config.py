from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/leads_db"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    ATTORNEY_EMAIL: str = "attorney@company.com"
    UPLOAD_DIR: str = "./uploads"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- Email backend ---
    # "console" (default; logs only), "smtp" (e.g. MailHog for local/demo — real, viewable
    # emails with no external provider), or "resend" (HTTP API for production).
    EMAIL_BACKEND: str = "console"
    EMAIL_FROM: str = "Leads App <leads@example.com>"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    RESEND_API_KEY: str = ""

    # --- Public-intake hardening ---
    # Only trust X-Forwarded-For / X-Real-IP when the app sits behind a known proxy.
    # Left False, the rate limiter keys on the real socket peer and cannot be bypassed
    # by spoofing the header.
    TRUST_PROXY_HEADERS: bool = False
    RATE_LIMIT_MAX: int = 10           # requests per window per client
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_TRACKED_IPS: int = 50_000  # cap limiter memory
    MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024  # 20 MB
    MAX_MESSAGE_CHARS: int = 2000
    EMAIL_MAX_RETRIES: int = 3
    EMAIL_TIMEOUT_SECONDS: float = 10.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
