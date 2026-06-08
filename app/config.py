from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Aplicação
    app_name: str = "torre-controle"
    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8001

    # Oracle (Winthor)
    oracle_host: str = ""
    oracle_port: int = 1521
    oracle_service_name: str = ""
    oracle_user: str = ""
    oracle_password: str = Field(default="", repr=False)
    oracle_query_timeout_seconds: int = 60

    # Fusion
    fusion_enabled: bool = False
    fusion_api_url: str = ""
    fusion_api_token: str = Field(default="", repr=False)

    # Claude / IA
    anthropic_api_key: str = Field(default="", repr=False)
    ai_model: str = "claude-haiku-4-5-20251001"
    ai_enabled: bool = True

    # WhatsApp
    whatsapp_enabled: bool = False
    whatsapp_api_url: str = ""
    whatsapp_api_token: str = Field(default="", repr=False)
    whatsapp_verify_token: str = Field(default="", repr=False)
    whatsapp_timeout_seconds: int = 30

    # Alertas
    alerta_horas_sem_fatura: int = 72
    alerta_horas_faturado_sem_carga: int = 24

    # Log
    log_level: str = "INFO"


settings = Settings()
