import warnings

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

    # CORS：生产环境应通过 .env 设置 CORS_ORIGINS 为具体域名列表
    # 例：CORS_ORIGINS=["https://yourdomain.com","https://api.yourdomain.com"]
    cors_origins: list[str] = [
        "http://localhost:8010",
        "http://localhost:8000",
        "http://localhost:3000",
        "http://127.0.0.1:8010",
    ]


settings = Settings()

# 启动时检查弱密钥，在所有环境下均输出警告
if settings.secret_key == "changeme":
    warnings.warn(
        "[安全警告] SECRET_KEY 使用默认值 'changeme'，"
        "请在 .env 中设置强随机密钥（建议：openssl rand -hex 32）",
        stacklevel=1,
    )
