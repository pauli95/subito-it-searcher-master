"""Filtri applicati lato nostro sugli annunci (prezzo, parole escluse)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


def price_in_range(price: int | None, min_price: int | None, max_price: int | None) -> bool:
    """Come lo script originale: un prezzo sconosciuto passa sempre il filtro."""
    if price is None:
        return True
    if min_price is not None and price < min_price:
        return False
    if max_price is not None and price > max_price:
        return False
    return True


def normalize(text: str) -> str:
    """Minuscolo e senza accenti: "Perché" -> "perche"."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def parse_words(value: str | Iterable[str] | None) -> list[str]:
    """Accetta "rotto, ricambi; cover" oppure una lista; restituisce parole pulite e uniche."""
    if value is None:
        return []
    parts = re.split(r"[,;\n]", value) if isinstance(value, str) else list(value)
    out: list[str] = []
    for part in parts:
        word = " ".join(str(part).split())
        if word and normalize(word) not in {normalize(w) for w in out}:
            out.append(word)
    return out


def excluded_by(title: str, words: Iterable[str]) -> str | None:
    """Restituisce la prima parola esclusa presente nel titolo (o None).

    Il confronto ignora maiuscole e accenti e lavora su parole intere all'inizio:
    "rott" esclude "rotto"/"rotta", ma "cover" non esclude "discovery".
    Le espressioni di più parole ("non funzionante") vanno cercate come frase.
    """
    text = normalize(title)
    for word in words:
        w = normalize(word).strip()
        if w and re.search(r"(?<![\w])" + re.escape(w), text):
            return word
    return None


def passes_filters(title: str, price: int | None, min_price: int | None, max_price: int | None,
                   exclude_words: Iterable[str]) -> bool:
    return price_in_range(price, min_price, max_price) and excluded_by(title, exclude_words) is None
