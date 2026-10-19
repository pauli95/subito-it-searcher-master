"""Download e parsing dei risultati di ricerca di subito.it (JSON `__NEXT_DATA__`).

Struttura verificata su pagine reali (ottobre 2026):
- `props.pageProps.initialState.items.originalList[]`: annunci (oggetti diretti).
  Formato precedente gestito dallo script originale: `items.list[].item`.
- `items.galleryList[]`: annunci "in vetrina", per lo più estranei alla lista: ignorati.
- Per ogni annuncio: `urn` ("id:ad:<uuid>:list:<id numerico>"), `subject`, `urls.default`,
  `geo.town.value`, `geo.city.shortName` (sigla provincia), `geo.region.value`,
  `category.friendlyName`, `type.key` ("s" vendita, "k" cerco, ...), `date`,
  `advertiser.company`, `images[].cdnBaseUrl`, `sold` (null se non venduto).
- `features["/price"].values[0].key`: prezzo intero come stringa.
- `features["/item_shippable"].values[0].key`: "1" (Sì) / "0" (No); la feature può mancare.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from .models import ScrapedAd

# Header di un browser reale. Lo script originale li aveva tra virgolette doppie
# ('"text/html..."'): corretti; verificato che subito.it risponde 200 anche così.
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.5,en;q=0.3",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Brave";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Gpc": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
}

TIMEOUT = 30


class ScrapeError(Exception):
    """Errore leggibile dall'utente.

    kind: "network" (connessione/timeout), "blocked" (403/429), "http" (altri codici),
    "structure" (pagina cambiata: dati non trovati dove previsto).
    """

    def __init__(self, message: str, kind: str = "network"):
        super().__init__(message)
        self.kind = kind


def fetch_html(url: str, session: requests.Session | None = None) -> str:
    getter = session or requests
    try:
        resp = getter.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.exceptions.Timeout as e:
        raise ScrapeError("Timeout: subito.it non ha risposto in tempo", "network") from e
    except requests.exceptions.ConnectionError as e:
        raise ScrapeError("Errore di connessione: impossibile raggiungere subito.it", "network") from e
    except requests.exceptions.RequestException as e:
        raise ScrapeError(f"Errore di rete: {e}", "network") from e
    if resp.status_code in (403, 429):
        raise ScrapeError(f"subito.it ha bloccato la richiesta (HTTP {resp.status_code})", "blocked")
    if resp.status_code >= 400:
        raise ScrapeError(f"subito.it ha risposto con HTTP {resp.status_code}", "http")
    return resp.text


def extract_next_data(html: str) -> dict[str, Any]:
    tag = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        raise ScrapeError("Struttura della pagina cambiata: blocco __NEXT_DATA__ non trovato", "structure")
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError as e:
        raise ScrapeError("JSON della pagina non valido", "structure") from e


def extract_items(data: dict[str, Any]) -> list[Any]:
    try:
        items = data["props"]["pageProps"]["initialState"]["items"]
    except (KeyError, TypeError) as e:
        raise ScrapeError("Struttura della pagina cambiata: dati annunci non trovati", "structure") from e
    if isinstance(items.get("list"), list):  # formato gestito dallo script originale
        return [w.get("item") for w in items["list"] if isinstance(w, dict)]
    if isinstance(items.get("originalList"), list):  # formato attuale
        return items["originalList"]
    raise ScrapeError("Struttura della pagina cambiata: lista annunci non trovata", "structure")


def _first_value(features: Any, name: str) -> dict[str, Any] | None:
    feature = features.get(name) if isinstance(features, dict) else None
    values = feature.get("values") if isinstance(feature, dict) else None
    if isinstance(values, list) and values and isinstance(values[0], dict):
        return values[0]
    return None


_URN_ID = re.compile(r":list:(\d+)$")
_LINK_ID = re.compile(r"-(\d+)\.htm")


def ad_key_from(urn: str | None, link: str | None) -> str | None:
    """Id numerico dell'annuncio, uguale in urn e link: chiave di deduplicazione."""
    for pattern, value in ((_URN_ID, urn), (_LINK_ID, link)):
        if value:
            m = pattern.search(value)
            if m:
                return m.group(1)
    return None


def parse_ad(product: Any) -> ScrapedAd | None:
    """Converte un annuncio JSON; None se mancano i dati minimi (link)."""
    if not isinstance(product, dict):
        return None
    link = (product.get("urls") or {}).get("default") or ""
    if not link:
        return None
    urn = product.get("urn")
    key = ad_key_from(urn, link) or link

    geo = product.get("geo") or {}
    features = product.get("features") or {}

    price: int | None = None
    pv = _first_value(features, "/price")
    if pv and pv.get("key") not in (None, ""):
        try:
            price = int(pv["key"])
        except (TypeError, ValueError):
            price = None

    sv = _first_value(features, "/item_shippable")
    shipping = None if sv is None else str(sv.get("key")) == "1"

    images = product.get("images") or []
    image = images[0].get("cdnBaseUrl") if images and isinstance(images[0], dict) else None
    advertiser = product.get("advertiser") or {}

    return ScrapedAd(
        ad_key=key,
        urn=urn,
        link=link,
        title=(product.get("subject") or "").strip() or "Senza titolo",
        price=price,
        town=(geo.get("town") or {}).get("value"),
        province=(geo.get("city") or {}).get("shortName"),
        region=(geo.get("region") or {}).get("value"),
        category=(product.get("category") or {}).get("friendlyName"),
        ad_type=(product.get("type") or {}).get("key"),
        shipping=shipping,
        company=advertiser.get("company") if isinstance(advertiser.get("company"), bool) else None,
        image=image,
        published_at=product.get("date"),
        sold=bool(product.get("sold")),
    )


def parse_page(html: str) -> list[ScrapedAd]:
    ads: list[ScrapedAd] = []
    seen: set[str] = set()
    for product in extract_items(extract_next_data(html)):
        ad = parse_ad(product)
        if ad and ad.ad_key not in seen:
            seen.add(ad.ad_key)
            ads.append(ad)
    return ads


def fetch_ads(url: str, session: requests.Session | None = None) -> list[ScrapedAd]:
    return parse_page(fetch_html(url, session))
