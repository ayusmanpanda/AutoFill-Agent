"""Application settings, loaded from backend/.env.

We use pydantic-settings so config is typed and validated. LiteLLM reads
provider credentials from environment variables, so after loading we bridge
the keys into os.environ.
"""
import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Provider LiteLLM routes to (e.g. "groq", "gemini"). Set explicitly so a
    # model id that itself contains a "/" — like Groq's "openai/gpt-oss-120b" —
    # isn't mis-detected as OpenAI.
    LLM_PROVIDER: str = "groq"

    # The provider's own model id (no extra provider prefix). Examples:
    #   groq   -> openai/gpt-oss-120b   (capable default)
    #   groq   -> openai/gpt-oss-20b    (faster, higher rate limits)
    #   groq   -> qwen/qwen3.6-27b
    #   gemini -> gemini-1.5-flash
    LLM_MODEL: str = "openai/gpt-oss-120b"

    # Shared secret the browser extension must send as the X-Local-Token header.
    LOCAL_TOKEN: str = "change-me"

    # Provider keys — set the ONE that matches LLM_MODEL.
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None


settings = Settings()

# LiteLLM looks for provider keys in the environment; bridge them across.
for _key in ("GROQ_API_KEY", "GEMINI_API_KEY"):
    _val = getattr(settings, _key)
    if _val:
        os.environ[_key] = _val
