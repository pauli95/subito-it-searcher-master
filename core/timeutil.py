"""Orari e fasce orarie."""

from __future__ import annotations

from datetime import time


def parse_hour(value: object) -> time:
    """Accetta "7", "07", "7:30", "07:30" -> time. Vuoto/None -> 00:00."""
    text = str(value if value is not None else "").strip()
    if not text:
        return time(0)
    try:
        if ":" in text:
            h, m = text.split(":", 1)
            return time(int(h), int(m))
        return time(int(text))
    except ValueError as e:
        raise ValueError(f"Orario non valido: {value!r} (usa HH o HH:MM)") from e


def format_hour(value: object) -> str:
    return parse_hour(value).strftime("%H:%M")


def in_between(now: time, start: time, end: time) -> bool:
    """Come lo script originale: start == end significa sempre attivo;
    start > end è una fascia a cavallo della mezzanotte (es. 22:00–07:00)."""
    if start < end:
        return start <= now < end
    if start == end:
        return True
    return start <= now or now < end
