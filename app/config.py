"""全局配置：环境变量 + .env，统一通过 get_settings() 获取。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "pr-sentinel"
    app_version: str = "0.1.0"

    # GitHub（M2 起使用）
    github_token: str = ""
    github_webhook_secret: str = ""

    # LLM（OpenAI 兼容协议）
    openai_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com/v1"
    model_fast: str = "deepseek-chat"
    model_strong: str = "deepseek-chat"

    # Agent 安全阀
    max_steps: int = 8
    request_timeout_s: float = 60.0

    # Langfuse（D9）
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Postgres（D2）
    database_url: str = (
        "postgresql+asyncpg://prsentinel:prsentinel@localhost:5432/prsentinel"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
