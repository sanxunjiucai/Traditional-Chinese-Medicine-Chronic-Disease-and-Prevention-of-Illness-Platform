from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/tcm"
    test_database_url: str = "postgresql+asyncpg://app:app@localhost:5432/tcm_test"

    secret_key: str = "changeme"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days

    demo_mode: bool = False

    anthropic_api_key: str = ""


settings = Settings()
