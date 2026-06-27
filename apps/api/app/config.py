"""
Vantage API — Configuration
All settings via environment variables. No secrets in code.
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "Vantage API"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl_aso: int = 3600          # 1h cache for ASO
    redis_ttl_session: int = 86400     # 24h for sessions

    # WorkOS
    workos_api_key: str
    workos_client_id: str
    workos_redirect_uri: str

    # Anthropic
    anthropic_api_key: str
    anthropic_model_bulk: str = "claude-haiku-4-5-20251001"
    anthropic_model_quality: str = "claude-sonnet-4-6"

    # Exa (semantic web research — primary)
    exa_api_key: str = ""

    # Perplexity (web research — fallback if Exa not configured)
    perplexity_api_key: str = ""
    perplexity_model: str = "sonar-pro"

    # HubSpot
    hubspot_client_id: str = ""
    hubspot_client_secret: str = ""
    hubspot_redirect_uri: str = ""

    # Microsoft Outlook (Graph API for email send + read)
    outlook_client_id: str = ""       # Azure App Registration client ID
    outlook_client_secret: str = ""   # Azure App Registration client secret
    outlook_tenant_id: str = "common" # Azure AD tenant ID ("common" for multi-tenant, specific ID for single-tenant)

    # Azure
    azure_service_bus_connection_string: str = ""
    azure_service_bus_queue_nightly: str = "nightly-agent-runs"
    azure_service_bus_queue_webhooks: str = "webhook-events"
    azure_service_bus_queue_urgent: str = "urgent-signals"

    # Fireflies (transcript ingestion)
    fireflies_api_key: str = ""                          # GraphQL API key from fireflies.ai/settings
    fireflies_webhook_secret: str = ""                   # HMAC secret for webhook verification

    # Microsoft Teams (signal alerts via incoming webhook)
    teams_webhook_url: str = ""                          # Incoming webhook URL from Teams channel
    teams_alert_urgency_threshold: float = 0.85         # Only alert on critical signals

    # Observability
    sentry_dsn: str = ""
    posthog_api_key: str = ""
    posthog_host: str = "https://us.posthog.com"

    # CORS
    cors_origins: list[str] = []  # If empty, uses default localhost + prod origins

    # Security
    field_encryption_key: str = ""  # Fernet key for at-rest token encryption — generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    workos_cookie_secret: str = ""  # Required in production — must be ≥32 bytes; generate: python -c "import secrets; print(secrets.token_hex(32))"
    api_key_prefix: str = "vnt_live_"
    webhook_signature_tolerance_seconds: int = 300  # 5 min
    jwt_signing_key: str = ""  # Required in production — generate with: python -c "import secrets; print(secrets.token_hex(32))"
    # Dev auth bypass — ONLY active when debug=True AND this is non-empty. Never commit a value.
    debug_bypass_token: str = ""
    # Outbound email guard — must be explicitly set to True before Outlook/HubSpot
    # email push endpoints will fire real API calls. False by default so dev/staging
    # environments can't accidentally send emails to real contacts.
    allow_outbound_email: bool = False
    # Rate limiting (requests per window per IP)
    rate_limit_auth_per_minute: int = 10
    rate_limit_batch_refresh_per_hour: int = 5
    rate_limit_api_default_per_minute: int = 120

    # Agent pipeline
    agent_urgency_threshold: float = 0.7   # Drafts created above this
    agent_push_threshold: float = 0.85     # Real-time alerts above this
    nightly_cron_hour: int = 2             # 2:00am per workspace timezone

    # Allowed email domains for workspace invitations (empty = allow all)
    allowed_email_domains: list[str] = []

    # Internal workspace (single-tenant mode)
    default_workspace_id: str = "00000000-0000-0000-0000-000000000001"

    # Frontend URL (for OAuth redirects)
    frontend_url: str = "http://localhost:3000"

    @field_validator("frontend_url", mode="before")
    @classmethod
    def _strip_frontend_url(cls, v: str) -> str:
        return v.strip().rstrip("/") if v else v

    # Embeddings (VoyageAI via voyageai SDK)
    voyage_api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
