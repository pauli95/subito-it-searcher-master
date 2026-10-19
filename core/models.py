"""Modelli dati del dominio."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def now_iso() -> str:
    # millisecondi: distingue "trovato" e "segnato come visto" anche nello stesso secondo.
    # Il confronto tra stringhe resta corretto con i valori al secondo già salvati.
    return datetime.now().isoformat(timespec="milliseconds")


@dataclass
class ScrapedAd:
    """Annuncio così come letto dalla pagina di subito.it."""

    ad_key: str            # id numerico dell'annuncio (es. "665091820")
    urn: str | None
    link: str
    title: str
    price: int | None      # None = prezzo non indicato
    town: str | None
    province: str | None   # sigla, es. "PD"
    region: str | None
    category: str | None
    ad_type: str | None    # "s" vendita, "k" cerco, ...
    shipping: bool | None  # None = feature assente nella pagina
    company: bool | None
    image: str | None
    published_at: str | None
    sold: bool = False

    @property
    def location(self) -> str:
        town = self.town or "Località sconosciuta"
        return f"{town} ({self.province})" if self.province else town


@dataclass
class Search:
    id: int | None
    name: str
    url: str
    params: dict[str, Any] | None = None
    min_price: int | None = None
    max_price: int | None = None
    exclude_words: list[str] = field(default_factory=list)
    enabled: bool = True
    interval_sec: int | None = None
    active_from: str | None = None
    active_to: str | None = None
    notify_new: bool = True
    notify_price_drop: bool = False
    notify_max_price: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    seen_at: str | None = None
    last_run_at: str | None = None
    last_ok_at: str | None = None
    last_error: str | None = None
    consecutive_errors: int = 0
    last_found: int | None = None
    last_new: int | None = None

    # Campi modificabili dall'utente (gli altri sono stato gestito dall'app).
    EDITABLE = ("name", "url", "params", "min_price", "max_price", "exclude_words", "enabled",
                "interval_sec", "active_from", "active_to", "notify_new", "notify_price_drop",
                "notify_max_price")

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Search":
        data = dict(row)
        data["params"] = json.loads(data["params"]) if data.get("params") else None
        data["exclude_words"] = json.loads(data.get("exclude_words") or "[]")
        for key in ("enabled", "notify_new", "notify_price_drop"):
            data[key] = bool(data[key])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    search_id: int
    name: str
    ok: bool
    found: int = 0                 # annunci letti dalla pagina
    matched: int = 0               # annunci che passano i filtri locali
    new: list[ScrapedAd] = field(default_factory=list)
    price_drops: list[tuple[ScrapedAd, int]] = field(default_factory=list)  # (annuncio, prezzo precedente)
    sold: int = 0
    error: str | None = None
    error_kind: str | None = None  # network | blocked | http | structure | unexpected
    duration: float = 0.0          # secondi

    def to_dict(self) -> dict[str, Any]:
        return {
            "search_id": self.search_id, "name": self.name, "ok": self.ok, "found": self.found,
            "matched": self.matched, "new": len(self.new), "price_drops": len(self.price_drops),
            "sold": self.sold, "error": self.error, "error_kind": self.error_kind,
            "duration": round(self.duration, 2),
        }
