"""Esportazione degli annunci in CSV (apribile direttamente con Excel in italiano)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from typing import Any

from .repo import Repository

COLUMNS: list[tuple[str, str]] = [
    ("id", "id"), ("titolo", "title"), ("prezzo", "price"), ("prezzo_precedente", "prev_price"),
    ("localita", "location"), ("comune", "town"), ("provincia", "province"), ("regione", "region"),
    ("categoria", "category"), ("spedizione", "shipping"), ("azienda", "company"),
    ("nuovo", "is_new"), ("ribasso", "is_drop"), ("venduto_il", "sold_at"),
    ("preferito", "favorite"), ("nascosto", "hidden"), ("trovato_il", "first_seen_at"),
    ("ultimo_visto_il", "last_seen_at"), ("pubblicato_il", "published_at"), ("ricerche", "searches"),
    ("link", "link"),
]


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "sì" if value else "no"
    if isinstance(value, list):  # ricerche
        return ", ".join(s["name"] for s in value)
    if isinstance(value, str):
        value = value.replace("T", " ", 1) if len(value) >= 19 and value[10:11] == "T" else value
        # niente formule eseguite da Excel/LibreOffice (CSV injection): =, +, -, @ all'inizio
        if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + value
    return value


def ads_to_csv(items: Iterable[dict[str, Any]]) -> str:
    """Separatore ';' e BOM UTF-8: Excel con impostazioni italiane apre il file senza importazione guidata."""
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([header for header, _ in COLUMNS])
    for item in items:
        writer.writerow([_cell(item.get(key)) for _, key in COLUMNS])
    return buf.getvalue()


def iter_ads(repo: Repository, page: int = 500, **filters: Any) -> Iterator[dict[str, Any]]:
    """Tutti gli annunci che rispettano i filtri, a pagine (query_ads restituisce al massimo 500 righe)."""
    offset = 0
    while True:
        items, total = repo.query_ads(limit=page, offset=offset, **filters)
        yield from items
        offset += len(items)
        if not items or offset >= total:
            return
