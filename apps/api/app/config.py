from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_P = Path(__file__).resolve().parents
ROOT = _P[3] if len(_P) > 3 else _P[-1]
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

    # PayPal sandbox app (developer.paypal.com). Lookout is the merchant-side
    # integrator: it creates AUTHORIZE orders, holds them while the scam check
    # and the trusted contact run, then captures or voids.
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_env: str = "sandbox"
    paypal_webhook_id: str = ""
    paypal_currency: str = "USD"

    # Shared secret the Next proxy sends on every API call. Empty = open (local demo).
    lookout_api_key: str = ""
    # ElevenLabs post-call webhook HMAC secret. Empty = unsigned transcripts accepted (local demo).
    elevenlabs_webhook_secret: str = ""
    # Comma-separated browser origins allowed to call the API directly. Empty = none.
    allowed_origins: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
