#!/usr/bin/env python3
"""Rigenera core/resources/categories.json (categorie, tipi di annuncio, filtro prezzo, ordinamenti).

Uso:  python tools/build_categories.py

Fonti (verificate a ottobre 2026):
- https://hades.subito.it/v1/values/categories                 -> 45 categorie (key, value, friendly_name,
                                                                   macrocategory_id per le sottocategorie)
- https://hades.subito.it/v1/values/categories/{id}/adtypes     -> tipi di annuncio ammessi
- pagina di ricerca /annunci-italia/{tipo}/{categoria}/          -> in __NEXT_DATA__:
    initialState.search.category.orders           ordinamenti disponibili (il primo è il predefinito)
    initialState.filtersConfig.filtersStore       presenza del filtro /price (queryString ps/pe)

Tipi di annuncio -> segmento dell'URL (ogni coppia verificata: pagina 200 e search.adType coerente):
    s = vendita, k = cerco, u = affitto, g = regalo, h = affitto-vacanze
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.scraper import HEADERS, extract_next_data  # noqa: E402

API = "https://hades.subito.it/v1/values/categories"
OUT = ROOT / "core" / "resources" / "categories.json"

AD_TYPES = {
    "s": {"slug": "vendita", "label": "In vendita"},
    "k": {"slug": "cerco", "label": "Cercasi"},
    "u": {"slug": "affitto", "label": "In affitto"},
    "g": {"slug": "regalo", "label": "In regalo"},
    "h": {"slug": "affitto-vacanze", "label": "In affitto per vacanze"},
}


def get(session: requests.Session, url: str, json_api: bool = True) -> requests.Response:
    headers = dict(HEADERS, Accept="application/json") if json_api else HEADERS
    for attempt in range(3):
        try:
            r = session.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == 2:
                raise SystemExit(f"Errore scaricando {url}: {e}")
            time.sleep(3)
    raise AssertionError


def page_info(session: requests.Session, ad_type: str, slug: str) -> dict:
    url = f"https://www.subito.it/annunci-italia/{AD_TYPES[ad_type]['slug']}/{slug}/"
    data = extract_next_data(get(session, url, json_api=False).text)
    state = data["props"]["pageProps"]["initialState"]
    search = state["search"]
    if search.get("adType") != ad_type or (search.get("category") or {}).get("friendly") != slug:
        raise SystemExit(f"Pagina inattesa per {url}: {search.get('adType')} {search.get('category')}")
    store = (state.get("filtersConfig") or {}).get("filtersStore") or {}
    filters = (store.get("filters") or []) + (store.get("sparseFilters") or [])
    return {
        "orders": (search.get("category") or {}).get("orders") or [],
        "price_filter": any(f.get("uri") in ("/price", "/price/min") for f in filters),
    }


def main() -> None:
    s = requests.Session()
    raw = get(s, API).json()["values"]
    categories = [{"id": "0", "slug": "usato", "name": "Tutte le categorie", "parent_id": None}]
    categories += [{"id": c["key"], "slug": c["friendly_name"], "name": c["value"],
                    "parent_id": c.get("macrocategory_id")} for c in raw]

    for cat in categories:
        time.sleep(0.5)
        ad_types = [t["key"] for t in get(s, f"{API}/{cat['id']}/adtypes").json()["values"]] \
            if cat["id"] != "0" else ["s", "k", "g", "u", "h"]
        unknown = set(ad_types) - set(AD_TYPES)
        if unknown:
            raise SystemExit(f"Tipi di annuncio sconosciuti per {cat['slug']}: {unknown}")
        cat["ad_types"] = ad_types
        time.sleep(1)
        cat.update(page_info(s, ad_types[0], cat["slug"]))
        flag = "prezzo" if cat["price_filter"] else "      "
        print(f"{cat['id']:>3} {cat['slug']:<28} {flag} {','.join(ad_types):<10} {cat['orders']}")

    data = {"generated": date.today().isoformat(), "source": "hades.subito.it/v1/values/categories",
            "ad_types": AD_TYPES, "categories": categories}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Scritto {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
