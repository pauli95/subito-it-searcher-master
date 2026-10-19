"""Località di subito.it: regioni, province, comuni (dati in core/resources/geo.json).

Rigenerare i dati con:  python tools/build_geo.py
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

RESOURCE = Path(__file__).resolve().parent / "resources" / "geo.json"


def slugify(text: str) -> str:
    """Regola degli slug di subito (verificata su tutti i comuni):
    "Paderno d'Adda" -> "paderno-d-adda", "Forlì" -> "forli"."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def _norm(text: str) -> str:
    return slugify(text).replace("-", " ")


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    slug: str


@dataclass(frozen=True)
class Province:
    id: str
    region_id: str
    name: str
    slug: str
    code: str | None   # sigla, es. "PD"
    istat: str | None


@dataclass(frozen=True)
class Town:
    istat: str
    name: str
    slug: str
    province_id: str


@dataclass(frozen=True)
class Location:
    """Una località selezionabile: tutta Italia, una regione, una provincia o un comune."""

    kind: str                  # "italia" | "region" | "province" | "town"
    region: Region | None = None
    province: Province | None = None
    town: Town | None = None

    @property
    def label(self) -> str:
        if self.kind == "italia":
            return "Tutta Italia"
        if self.kind == "region":
            return self.region.name
        if self.kind == "province":
            return f"{self.province.name} (provincia)"
        return f"{self.town.name} ({self.province.code})"

    @property
    def detail(self) -> str:
        if self.kind == "region":
            return "Regione"
        if self.kind == "province":
            return f"Provincia · {self.region.name}"
        if self.kind == "town":
            return f"Comune · {self.province.name}, {self.region.name}"
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "label": self.label, "detail": self.detail,
            "region": self.region.slug if self.region else None,
            "province": self.province.slug if self.province else None,
            "town": self.town.slug if self.town else None,
        }


ITALIA = Location("italia")


class Geo:
    def __init__(self, data: dict[str, Any]):
        self.generated: str | None = data.get("generated")
        self.regions = [Region(**r) for r in data["regions"]]
        self.provinces = [Province(**p) for p in data["provinces"]]
        self.towns = [Town(istat=t[0], name=t[1], slug=t[2], province_id=t[3]) for t in data["towns"]]

        self._region_by_slug = {r.slug: r for r in self.regions}
        self._region_by_id = {r.id: r for r in self.regions}
        self._province_by_id = {p.id: p for p in self.provinces}
        self._province_by_slug = {(p.region_id, p.slug): p for p in self.provinces}
        self._town_by_slug = {(t.province_id, t.slug): t for t in self.towns}
        self._codes = {p.code for p in self.provinces if p.code}

        # indice per l'autocompletamento: (nome normalizzato, priorità tipo, Location)
        self._index: list[tuple[str, int, Location]] = [("tutta italia", 0, ITALIA)]
        self._index += [(_norm(r.name), 1, Location("region", region=r)) for r in self.regions]
        for p in self.provinces:
            loc = Location("province", region=self._region_by_id[p.region_id], province=p)
            self._index.append((_norm(p.name), 2, loc))
        for t in self.towns:
            p = self._province_by_id[t.province_id]
            loc = Location("town", region=self._region_by_id[p.region_id], province=p, town=t)
            self._index.append((_norm(t.name), 3, loc))

    # ------------------------------------------------------------------ ricerca per slug
    def region(self, slug: str) -> Region | None:
        return self._region_by_slug.get(slug)

    def province(self, region: Region, slug: str) -> Province | None:
        return self._province_by_slug.get((region.id, slug))

    def town(self, province: Province, slug: str) -> Town | None:
        return self._town_by_slug.get((province.id, slug))

    def resolve(self, region: str | None, province: str | None = None, town: str | None = None) -> Location:
        """Slug -> Location; ValueError se la combinazione non esiste."""
        if not region or region == "italia":
            if province or town:
                raise ValueError("Provincia o comune senza regione")
            return ITALIA
        reg = self.region(region)
        if not reg:
            raise ValueError(f"Regione sconosciuta: {region}")
        if not province:
            if town:
                raise ValueError("Comune senza provincia")
            return Location("region", region=reg)
        prov = self.province(reg, province)
        if not prov:
            raise ValueError(f"Provincia '{province}' non trovata in {reg.name}")
        if not town:
            return Location("province", region=reg, province=prov)
        tw = self.town(prov, town)
        if not tw:
            raise ValueError(f"Comune '{town}' non trovato in provincia di {prov.name}")
        return Location("town", region=reg, province=prov, town=tw)

    # ------------------------------------------------------------------ autocompletamento
    def search(self, query: str, limit: int = 12) -> list[Location]:
        """"Pad" -> Padova (provincia), Padova (comune), Padenghe sul Garda, ...

        Ordine: corrispondenza esatta, inizio del nome, inizio di una parola, sottostringa;
        a parità, regione > provincia > comune, e il comune capoluogo prima degli altri.
        Accetta anche la sigla di provincia ("PD").
        """
        text = (query or "").strip()
        only_kind: str | None = None
        only_code: str | None = None
        # accetta le etichette che mostriamo noi: "Padova (provincia)", "Padova (PD)", "Calliano TN"
        m = re.match(r"^(.*?)\s*\(\s*provincia\s*\)$", text, re.IGNORECASE)
        if m:
            text, only_kind = m.group(1), "province"
        else:
            m = re.match(r"^(.+?)[\s,]+\(?([A-Za-z]{2})\)?$", text)
            if m and m.group(2).upper() in self._codes:
                text, only_code = m.group(1), m.group(2).upper()
        q = _norm(text)
        if not q:
            return []
        scored: list[tuple[tuple, Location]] = []
        for name, kind_rank, loc in self._index:
            if only_kind and loc.kind != only_kind:
                continue
            if only_code and not (loc.province and loc.province.code == only_code):
                continue
            if name == q:
                match = 0
            elif name.startswith(q):
                match = 1
            elif f" {q}" in f" {name}":
                match = 2
            elif q in name:
                match = 3
            elif loc.kind == "province" and loc.province.code and loc.province.code.lower() == q:
                match = 0
            else:
                continue
            capital = 0 if loc.kind == "town" and loc.town.slug == loc.province.slug else 1
            if only_code:  # "Padova (PD)" è l'etichetta di un comune: i comuni prima
                kind_rank = 0 if loc.kind == "town" else kind_rank
            scored.append(((match, kind_rank, capital, len(name), name), loc))
        if not scored and (only_kind or only_code):
            # es. "San Vito Lo": "Lo" è anche la sigla di Lodi -> riprova senza interpretare la sigla
            return self._search_plain(query, limit)
        scored.sort(key=lambda x: x[0])
        return [loc for _, loc in scored[:limit]]

    def _search_plain(self, query: str, limit: int) -> list[Location]:
        q = _norm(query)
        hits = [(0 if n.startswith(q) else 1, rank, len(n), n, loc)
                for n, rank, loc in self._index if q and q in n]
        hits.sort(key=lambda x: x[:4])
        return [h[-1] for h in hits[:limit]]


@lru_cache(maxsize=1)
def load_geo(path: Path = RESOURCE) -> Geo:
    return Geo(json.loads(path.read_text(encoding="utf-8")))
