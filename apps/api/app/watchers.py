"""Desks that can be added without changing the score.

A desk notices words and may turn on one signal the scorer already knows.
That signal is already worth at most 15, so one desk cannot hold a payment.
Drop a module in app/desks that calls register(), or POST /watchers.
"""

import importlib.util
from pathlib import Path

from app.labels import MESSAGE_SIGNALS
from app.reasons import POINTS

DESKS: list[dict] = []
_loaded = False


def register(spec: dict) -> None:
    if any(item["id"] == spec["id"] for item in DESKS):
        return
    if spec["signal"] not in MESSAGE_SIGNALS:
        raise ValueError("A desk can only turn on a message signal.")
    DESKS.append(spec)


def load_desks() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    folder = Path(__file__).resolve().parent / "desks"
    if not folder.exists():
        return
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"app.desks.{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def apply_watchers(text: str, signals: dict[str, bool], watchers: list[dict], language: str) -> tuple[dict[str, bool], list[dict]]:
    haystack = (text or "").lower()
    out = dict(signals)
    hits = []
    for watcher in watchers:
        phrases = [str(item).strip().lower() for item in watcher.get("phrases", []) if str(item).strip()]
        matched = next((phrase for phrase in phrases if len(phrase) >= 3 and phrase in haystack), None)
        if matched is None:
            continue
        signal = str(watcher.get("signal") or "")
        if signal not in POINTS:
            continue
        heat = 0 if out.get(signal) else POINTS[signal]
        out[signal] = True
        spanish = language == "es"
        hits.append(
            {
                "id": watcher["id"],
                "name": watcher["name_es"] if spanish else watcher["name_en"],
                "sentence": watcher["sentence_es"] if spanish else watcher["sentence_en"],
                "signal": signal,
                "heat": heat,
            }
        )
    return out, hits


def reader_line(source: str, language: str, heat: int) -> dict:
    if language == "es":
        names = {
            "gemini": ("Gemini", "Gemini leyó las palabras que usted compartió."),
            "fallback": ("Reglas sin conexión", "Las reglas sin conexión leyeron las palabras que usted compartió."),
        }
        name, sentence = names.get(source, ("Sin mensaje", "No había palabras para leer."))
    else:
        names = {
            "gemini": ("Gemini", "Gemini read the words you shared."),
            "fallback": ("Offline rules", "Offline rules read the words you shared."),
        }
        name, sentence = names.get(source, ("No message", "There were no words to read."))
    return {"id": "reader", "name": name, "sentence": sentence, "signal": "message", "heat": heat}


def ledger_line(signals: dict[str, bool], language: str) -> dict:
    heat = sum(POINTS[key] for key in ("new_recipient", "unusual_amount", "irreversible_method") if signals.get(key))
    if language == "es":
        name, sentence = "El Libro", "El Libro miró a quién, cuánto y cómo se envía."
    else:
        name, sentence = "The Ledger", "The Ledger checked who, how much, and how it sends."
    return {"id": "ledger", "name": name, "sentence": sentence, "signal": "wallet", "heat": heat}


def reason_line(language: str, sentence: str, heat: int) -> dict:
    name = "La Razón" if language == "es" else "The Reason"
    return {"id": "reason", "name": name, "sentence": sentence, "signal": "stated_reason", "heat": heat}
