from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", API_ROOT / ".env"),
        extra="ignore",
    )

    database_url: str = f"sqlite+aiosqlite:///{API_ROOT / 'data' / 'lookout.db'}"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_en: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_voice_es: str = "21m00Tcm4TlvDq8ikWAM"
    presage_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    public_base_url: str = ""
    hold_timeout_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
