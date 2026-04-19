from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


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

    @staticmethod
    def _csv_to_list(v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            # Split on commas/newlines; trim; drop empties.
            parts = []
            for chunk in s.replace("\n", ",").split(","):
                t = chunk.strip()
                if t:
                    parts.append(t)
            return parts
        return [str(v).strip()] if str(v).strip() else []

    @field_validator(
        "SERVICE_KEYWORDS",
        "SERVICE_BRAND_TOKENS",
        "SERVICE_SENDER_DOMAIN_ALLOWLIST",
        "SERVICE_SENDER_DOMAIN_BLOCKLIST",
        mode="before",
    )
    @classmethod
    def _coerce_csv_lists(cls, v: Any) -> list[str]:
        return cls._csv_to_list(v)

    def gmail_scopes(self) -> list[str]:
        # Keep in sync with Google OAuth consent.
        # If scopes change after a token is issued, token exchange can fail with:
        # "Scope has changed from ... to ..."
        return [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.modify",
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

