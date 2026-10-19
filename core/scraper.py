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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .filters import normalize
from .models import ScrapedAd

MAX_RESULTS = 100
_PAGE_SIZE_HINT = 30

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


def _parse_products(products: list[Any]) -> list[ScrapedAd]:
    ads: list[ScrapedAd] = []
    seen: set[str] = set()
    for product in products:
        ad = parse_ad(product)
        if ad and ad.ad_key not in seen:
            seen.add(ad.ad_key)
            ads.append(ad)
    return ads


def parse_page(html: str) -> list[ScrapedAd]:
    return _parse_products(extract_items(extract_next_data(html)))


def _fetch_page_with_meta(url: str, session: requests.Session | None) -> tuple[list[ScrapedAd], int | None]:
    data = extract_next_data(fetch_html(url, session))
    products = extract_items(data)
    ads = _parse_products(products)
    try:
        items = data["props"]["pageProps"]["initialState"]["items"]
        total_pages = int(items.get("totalPages"))
        if total_pages < 1:
            total_pages = None
    except (KeyError, TypeError, ValueError):
        total_pages = None
    return ads, total_pages


def _query_terms(url: str) -> list[str | None]:
    query = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    values = [value for key, value in query if key.lower() == "q"]
    if not values:
        return [None]
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        for term in value.split():
            key = normalize(term)
            if key and key not in seen:
                seen.add(key)
                terms.append(term)
    return terms or [None]


def _page_url(url: str, term: str | None, page: int, terms: list[str | None]) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    raw_terms = [value for key, value in query if key.lower() == "q"]
    has_page = any(key.lower() == "o" for key, _ in query)
    if page == 1 and not has_page and len(terms) == 1:
        if (term is None and not raw_terms) or raw_terms == [term]:
            return url
    kept = [(key, value) for key, value in query if key.lower() not in {"q", "o"}]
    if term is not None:
        kept.append(("q", term))
    if page > 1:
        kept.append(("o", str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def fetch_ads_limited(url: str, session: requests.Session | None = None, *, limit: int = MAX_RESULTS,
                      before_request=None, page_fetch=None) -> list[ScrapedAd]:
    """Unisce le parole chiave come OR, deduplica e legge al massimo `limit` annunci.

    Subito assegna gli annunci a pagine tramite `o=2`, `o=3`, ecc. I risultati dei
    diversi termini vengono alternati per non lasciare fuori un termine quando si
    raggiunge il limite complessivo.
    """
    limit = max(1, min(int(limit), MAX_RESULTS))
    terms = _query_terms(url)
    use_site_parser = page_fetch is None or page_fetch is fetch_ads
    custom_fetch = page_fetch or fetch_ads
    by_term: dict[str | None, list[ScrapedAd]] = {term: [] for term in terms}
    term_seen: dict[str | None, set[str]] = {term: set() for term in terms}
    total_pages: dict[str | None, int] = {}
    exhausted: set[str | None] = set()

    def merged() -> list[ScrapedAd]:
        result: list[ScrapedAd] = []
        seen: set[str] = set()
        longest = max((len(by_term[term]) for term in terms), default=0)
        for index in range(longest):
            for term in terms:
                ads = by_term[term]
                if index >= len(ads):
                    continue
                ad = ads[index]
                key = ad.ad_key or ad.link
                if key not in seen:
                    seen.add(key)
                    result.append(ad)
                    if len(result) >= limit:
                        return result
        return result

    for page in range(1, limit + 1):
        made_progress = False
        for term in terms:
            if term in exhausted:
                continue
            if term in total_pages and page > total_pages[term]:
                exhausted.add(term)
                continue
            if before_request:
                before_request()
            page_url = _page_url(url, term, page, terms)
            if use_site_parser:
                ads, page_count = _fetch_page_with_meta(page_url, session)
                if page_count is not None:
                    total_pages[term] = page_count
            else:
                ads = custom_fetch(page_url, session)
                page_count = None

            fresh: list[ScrapedAd] = []
            for ad in ads:
                key = ad.ad_key or ad.link
                if key not in term_seen[term]:
                    term_seen[term].add(key)
                    fresh.append(ad)
            if fresh:
                by_term[term].extend(fresh)
                made_progress = True
            if not ads or not fresh:
                exhausted.add(term)
            elif page_count is not None and page >= page_count:
                exhausted.add(term)
            elif page_count is None and len(ads) < _PAGE_SIZE_HINT:
                exhausted.add(term)

        result = merged()
        if len(result) >= limit or not made_progress or len(exhausted) == len(terms):
            return result[:limit]
    return merged()[:limit]


def fetch_ads(url: str, session: requests.Session | None = None) -> list[ScrapedAd]:
    """Scarica e analizza una sola pagina dei risultati."""
    return parse_page(fetch_html(url, session))
