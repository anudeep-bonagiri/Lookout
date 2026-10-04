import httpx

from app.config import get_settings
from app.reasons import warning_for


async def synthesize(language: str) -> tuple[bytes | None, str]:
    text = warning_for(language)
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        return None, text
    voice = settings.elevenlabs_voice_es if language == "es" else settings.elevenlabs_voice_en
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
            },
        )
        response.raise_for_status()
        return response.content, text
