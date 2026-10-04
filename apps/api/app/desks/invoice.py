from app.watchers import register

register(
    {
        "id": "invoice-desk",
        "name_en": "Invoice desk",
        "name_es": "Mesa de facturas",
        "signal": "sensitive_request",
        "phrases": (
            "routing number",
            "new account number",
            "updated invoice",
            "wire the difference",
            "payment details changed",
            "número de ruta",
            "numero de ruta",
            "cuenta nueva",
            "factura nueva",
        ),
        "sentence_en": "The payment instructions changed. That is how invoice scams work.",
        "sentence_es": "Las instrucciones de pago cambiaron. Así funcionan las estafas de facturas.",
    }
)
