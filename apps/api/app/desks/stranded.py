from app.watchers import register

register(
    {
        "id": "stranded-desk",
        "name_en": "Stranded desk",
        "name_es": "Mesa de viaje",
        "signal": "urgency",
        "phrases": (
            "stuck abroad",
            "can't video",
            "cannot video",
            "send a ticket",
            "my phone broke",
            "no puedo hacer videollamada",
            "estoy varado",
            "estoy varada",
            "mándame un boleto",
            "mandame un boleto",
        ),
        "sentence_en": "Someone says they are stuck and need travel money, and they will not get on video.",
        "sentence_es": "Alguien dice que está varado y necesita dinero de viaje, y no quiere hacer una videollamada.",
    }
)
