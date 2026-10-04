from app.watchers import register
from app.why import EMERGENCY_CUES

register(
    {
        "id": "emergency-desk",
        "name_en": "Emergency desk",
        "name_es": "Mesa de emergencia",
        "signal": "urgency",
        "phrases": EMERGENCY_CUES,
        "sentence_en": "The words say someone is at a doctor, in jail, or in an accident and needs money now.",
        "sentence_es": "Las palabras dicen que alguien está en el médico, en la cárcel o en un accidente y necesita el dinero ahora.",
    }
)
