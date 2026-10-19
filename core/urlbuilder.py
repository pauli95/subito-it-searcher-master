"""Costruzione degli URL di ricerca di subito.it dai parametri del form, e operazione inversa.

Formato verificato su pagine reali (ottobre 2026) leggendo `initialState.search` nel
`__NEXT_DATA__`, che riporta i parametri effettivamente interpretati dal sito:

    https://www.subito.it/annunci-{regione}/{tipo}/{categoria}/[{provincia}/[{comune}/]]?{query}

- regione: slug di subito ("veneto", "valle-d-aosta"); "italia" = tutta Italia.
  Provincia e comune sono ammessi solo con una regione.             -> search.geo.*.friendlyName
- tipo: vendita (s), cerco (k), affitto (u), regalo (g), affitto-vacanze (h) -> search.adType
- categoria: slug della categoria; "usato" = tutte le categorie.     -> search.category.friendly
- slug non validi in qualsiasi posizione -> HTTP 404.
- query string:
    q=parole+chiave                                                  -> search.query
    qso=true   ricerca solo nel titolo                               -> search.qso
    shp=true   solo con spedizione                                   -> search.includeShippableOnly
    ps=100&pe=300  prezzo min/max in euro, valori liberi; applicati  -> search.filters.ps/pe
               SOLO se la categoria ha il filtro prezzo (non su "usato": ignorati)
    order=datedesc|relevance|priceasc|pricedesc (+ altri per auto/moto) -> search.orderIndex
  In molte categorie l'ordinamento predefinito è "relevance": per il monitoraggio si usa
  "datedesc", così gli annunci nuovi sono in prima pagina.
Altri parametri del sito (es. advt, ic, urg) non gestiti dal form vengono conservati in `extra`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from .categories import Catalog, load_catalog
from .geo import Geo, Location, load_geo

BASE = "https://www.subito.it"
DEFAULT_ORDER = "datedesc"
_PATH = re.compile(r"^/annunci-(?P<region>[a-z0-9-]+)/(?P<type>[a-z-]+)/(?P<rest>[a-z0-9/-]+?)/?$")
_KNOWN_QUERY = {"q", "qso", "shp", "ps", "pe", "order"}
_TRUE = {"true", "1", "s", "si", "yes", "on"}


class UrlError(ValueError):
    """Parametri non validi o URL non riconosciuto."""


@dataclass
class SearchParams:
    keywords: str = ""
    title_only: bool = False
    region: str | None = None        # slug; None = tutta Italia
    province: str | None = None
    town: str | None = None
    category: str = "usato"
    ad_type: str = "s"
    min_price: int | None = None
    max_price: int | None = None
    shipping_only: bool = False
    order: str | None = DEFAULT_ORDER  # None = ordinamento predefinito del sito
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchParams":
        known = {f for f in cls.__dataclass_fields__}
        values = {k: v for k, v in data.items() if k in known}
        for key in ("region", "province", "town", "order"):
            if values.get(key) == "":
                values[key] = None
        for key in ("min_price", "max_price"):
            if values.get(key) in ("", None):
                values[key] = None
            else:
                values[key] = int(values[key])
        values["extra"] = {str(k): str(v) for k, v in (values.get("extra") or {}).items()}
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BuildResult:
    url: str
    warnings: list[str]
    location: Location
    price_on_site: bool  # True se ps/pe sono nell'URL; il filtro locale si applica comunque


@dataclass
class ParseResult:
    params: SearchParams
    warnings: list[str]


class UrlBuilder:
    def __init__(self, geo: Geo | None = None, catalog: Catalog | None = None):
        self.geo = geo or load_geo()
        self.catalog = catalog or load_catalog()

    # ------------------------------------------------------------------ parametri -> URL
    def build(self, p: SearchParams) -> BuildResult:
        warnings: list[str] = []
        category = self.catalog.category(p.category or "usato")
        if not category:
            raise UrlError(f"Categoria sconosciuta: {p.category}")
        ad_type = self.catalog.ad_types.get(p.ad_type)
        if not ad_type:
            raise UrlError(f"Tipo di annuncio sconosciuto: {p.ad_type}")
        if ad_type.key not in category.ad_types:
            allowed = ", ".join(self.catalog.ad_types[k].label for k in category.ad_types)
            raise UrlError(f"'{ad_type.label}' non è disponibile per {category.label} (ammessi: {allowed})")
        try:
            location = self.geo.resolve(p.region, p.province, p.town)
        except ValueError as e:
            raise UrlError(str(e)) from e
        if p.min_price is not None and p.max_price is not None and p.min_price > p.max_price:
            raise UrlError("Il prezzo minimo è maggiore del massimo")
        if any(v is not None and v < 0 for v in (p.min_price, p.max_price)):
            raise UrlError("Il prezzo non può essere negativo")

        path = [f"annunci-{location.region.slug if location.region else 'italia'}", ad_type.slug, category.slug]
        if location.province:
            path.append(location.province.slug)
        if location.town:
            path.append(location.town.slug)

        query: list[tuple[str, str]] = []
        keywords = " ".join(p.keywords.split())
        if keywords:
            query.append(("q", keywords))
            if p.title_only:
                query.append(("qso", "true"))
        elif p.title_only:
            warnings.append("'Solo nel titolo' ignorato: nessuna parola chiave")
        if p.shipping_only:
            query.append(("shp", "true"))

        has_price = p.min_price is not None or p.max_price is not None
        price_on_site = has_price and category.price_filter
        if price_on_site:
            if p.min_price is not None:
                query.append(("ps", str(p.min_price)))
            if p.max_price is not None:
                query.append(("pe", str(p.max_price)))
        elif has_price:
            warnings.append(f"Il sito non filtra per prezzo in '{category.label}': "
                            "il filtro prezzo viene applicato dall'app sui risultati")

        if p.order:
            if category.orders and p.order not in category.orders:
                warnings.append(f"Ordinamento '{p.order}' non disponibile per {category.label}: ignorato")
            else:
                query.append(("order", p.order))

        for key, value in p.extra.items():
            if key not in _KNOWN_QUERY:
                query.append((key, value))

        url = f"{BASE}/{'/'.join(path)}/"
        if query:
            url += "?" + urlencode(query)   # spazi come "+", come negli URL del sito
        return BuildResult(url, warnings, location, price_on_site)

    # ------------------------------------------------------------------ URL -> parametri
    def parse(self, url: str) -> ParseResult:
        """Riconosce un URL di ricerca di subito.it. UrlError se non è interpretabile."""
        text = (url or "").strip()
        if not text:
            raise UrlError("URL vuoto")
        if "://" not in text:
            text = "https://" + text
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        if host not in ("subito.it", "www.subito.it", "m.subito.it"):
            raise UrlError("Non è un indirizzo di subito.it")
        m = _PATH.match(parts.path.lower())
        if not m:
            raise UrlError("Non è una pagina di ricerca di subito.it (atteso /annunci-…/…/…/)")

        warnings: list[str] = []
        ad_type = self.catalog.ad_type_by_slug(m["type"])
        if not ad_type:
            raise UrlError(f"Tipo di annuncio non riconosciuto: {m['type']}")
        segments = m["rest"].split("/")
        category = self.catalog.category(segments[0])
        if not category:
            raise UrlError(f"Categoria non riconosciuta: {segments[0]}")
        geo_segments = segments[1:]
        if len(geo_segments) > 2:
            raise UrlError("Percorso con filtri non gestiti dal form (es. marca/modello): "
                           "la ricerca resta valida ma solo come URL")

        region = None if m["region"] == "italia" else m["region"]
        province = geo_segments[0] if geo_segments else None
        town = geo_segments[1] if len(geo_segments) > 1 else None
        if region is None and province:
            raise UrlError("Percorso con filtri non gestiti dal form (es. marca/modello): "
                           "la ricerca resta valida ma solo come URL")
        try:
            self.geo.resolve(region, province, town)
        except ValueError as e:
            raise UrlError(str(e)) from e

        p = SearchParams(region=region, province=province, town=town, category=category.slug,
                         ad_type=ad_type.key, order=None)
        for key, value in parse_qsl(parts.query, keep_blank_values=False):
            if key == "q":
                p.keywords = " ".join(value.split())
            elif key == "qso":
                p.title_only = value.lower() in _TRUE
            elif key == "shp":
                p.shipping_only = value.lower() in _TRUE
            elif key in ("ps", "pe"):
                try:
                    number = int(value.replace(".", ""))
                except ValueError:
                    warnings.append(f"Prezzo non valido ignorato: {key}={value}")
                    continue
                if key == "ps":
                    p.min_price = number
                else:
                    p.max_price = number
            elif key == "order":
                p.order = value
            else:
                p.extra[key] = value
        if ad_type.key not in category.ad_types:
            warnings.append(f"'{ad_type.label}' non è previsto per {category.label}")
        if p.extra:
            warnings.append("Parametri conservati ma non modificabili dal form: " + ", ".join(p.extra))
        return ParseResult(p, warnings)
