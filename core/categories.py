"""Categorie e tipi di annuncio di subito.it (dati in core/resources/categories.json).

Rigenerare i dati con:  python tools/build_categories.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

RESOURCE = Path(__file__).resolve().parent / "resources" / "categories.json"

ORDER_LABELS = {
    "datedesc": "Più recenti",
    "relevance": "Rilevanza",
    "priceasc": "Prezzo crescente",
    "pricedesc": "Prezzo decrescente",
    "yearasc": "Anno crescente",
    "yeardesc": "Anno decrescente",
    "mileageasc": "Chilometri crescenti",
    "mileagedesc": "Chilometri decrescenti",
}


@dataclass(frozen=True)
class AdType:
    key: str     # "s", "k", "u", "g", "h"
    slug: str    # segmento dell'URL: "vendita", "cerco", ...
    label: str


@dataclass(frozen=True)
class Category:
    id: str
    slug: str
    name: str
    parent_id: str | None
    ad_types: tuple[str, ...]
    orders: tuple[str, ...]     # il primo è l'ordinamento predefinito del sito
    price_filter: bool          # il sito applica ps/pe in questa categoria

    @property
    def is_macro(self) -> bool:
        return self.parent_id is None and self.id != "0"

    @property
    def label(self) -> str:
        # le macrocategorie arrivano in maiuscolo ("ELETTRONICA", "PER LA CASA e LA PERSONA")
        letters = [c for c in self.name if c.isalpha()]
        mostly_upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.8
        return self.name.capitalize() if mostly_upper else self.name


class Catalog:
    def __init__(self, data: dict[str, Any]):
        self.generated: str | None = data.get("generated")
        self.ad_types = {k: AdType(k, v["slug"], v["label"]) for k, v in data["ad_types"].items()}
        self._ad_type_by_slug = {t.slug: t for t in self.ad_types.values()}
        self.categories = [
            Category(id=c["id"], slug=c["slug"], name=c["name"], parent_id=c.get("parent_id"),
                     ad_types=tuple(c["ad_types"]), orders=tuple(c.get("orders") or ()),
                     price_filter=bool(c.get("price_filter")))
            for c in data["categories"]
        ]
        self._by_slug = {c.slug: c for c in self.categories}
        self._by_id = {c.id: c for c in self.categories}

    def category(self, slug: str) -> Category | None:
        return self._by_slug.get(slug)

    def by_id(self, category_id: str) -> Category | None:
        return self._by_id.get(category_id)

    def ad_type_by_slug(self, slug: str) -> AdType | None:
        return self._ad_type_by_slug.get(slug)

    def tree(self) -> list[dict[str, Any]]:
        """Per la select del form: macrocategorie con le loro sottocategorie."""
        out = []
        for c in self.categories:
            if c.parent_id is None:
                out.append({"slug": c.slug, "label": c.label, "children": []})
            else:
                parent = next(o for o in out if o["slug"] == self._by_id[c.parent_id].slug)
                parent["children"].append({"slug": c.slug, "label": c.label})
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated": self.generated,
            "ad_types": [{"key": t.key, "slug": t.slug, "label": t.label} for t in self.ad_types.values()],
            "orders": ORDER_LABELS,
            "categories": [{"id": c.id, "slug": c.slug, "label": c.label, "parent_id": c.parent_id,
                            "ad_types": list(c.ad_types), "orders": list(c.orders),
                            "price_filter": c.price_filter} for c in self.categories],
            "tree": self.tree(),
        }


@lru_cache(maxsize=1)
def load_catalog(path: Path = RESOURCE) -> Catalog:
    return Catalog(json.loads(path.read_text(encoding="utf-8")))
