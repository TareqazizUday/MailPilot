from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr


class Settings(BaseModel):
    # Core behavior
    REPLY_MODE: str = "draft"
    SEND_TRANSPORT: Literal["gmail_api", "smtp"] = "gmail_api"

    # Gmail OAuth / API
    GMAIL_ADDRESS: str = ""
    GOOGLE_CLIENT_SECRET_FILE: str = ""
    GOOGLE_TOKEN_FILE: str = ""
    OAUTH_REDIRECT_URI: str = ""

    # Worker
    WORKER_ONCE: bool = False
    IMAP_POLL_SECONDS: int = 60

    # Service tuning
    SERVICE_KEYWORDS: list[str] = Field(default_factory=list)
    SERVICE_BRAND_TOKENS: list[str] = Field(default_factory=list)
    SERVICE_SENDER_DOMAIN_ALLOWLIST: list[str] = Field(default_factory=list)
    SERVICE_SENDER_DOMAIN_BLOCKLIST: list[str] = Field(default_factory=list)
    RELEVANCE_THRESHOLD: float = 0.35

    # Vector / KB
    VECTOR_DB_DSN: str = ""
    EMBEDDING_MODEL: str = "stub"
    EMBEDDING_DIM: int = 1536

    # SMTP outbound
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: SecretStr | None = None
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_VERIFY_TLS: bool = True
    SMTP_TLS_SERVERNAME: str = ""
    SMTP_FROM_EMAIL: str = ""

    # IMAP inbound
    IMAP_HOST: str = ""
    IMAP_PORT: int = 993
    IMAP_USERNAME: str = ""
    IMAP_PASSWORD: SecretStr | None = None
    IMAP_MAILBOX: str = "INBOX"
    IMAP_VERIFY_TLS: bool = True
    IMAP_TLS_SERVERNAME: str = ""

    # LLM
    LLM_API_KEY: SecretStr | None = None

    def gmail_scopes(self) -> list[str]:
        # Minimal set for listing threads + sending
        return [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ]

    def outbound_from_email(self) -> str:
        if (self.SMTP_FROM_EMAIL or "").strip():
            return self.SMTP_FROM_EMAIL.strip()
        if (self.GMAIL_ADDRESS or "").strip():
            return self.GMAIL_ADDRESS.strip()
        return ""

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        # Keep compatibility with callers expecting SecretStr to be serializable.
        kwargs.setdefault("mode", "python")
        return super().model_dump(*args, **kwargs)

