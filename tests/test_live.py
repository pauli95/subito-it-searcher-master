"""Verifica degli URL generati contro subito.it reale (richiede internet).

Esclusi di default; eseguirli con:  python -m pytest -m live
Ogni pagina riporta in initialState.search i parametri effettivamente interpretati dal sito.
"""

from __future__ import annotations

import time

import pytest
import requests

from core.geo import load_geo
from core.scraper import HEADERS, extract_next_data
from core.urlbuilder import SearchParams, UrlBuilder

pytestmark = pytest.mark.live

CASES = [
    SearchParams(keywords="iphone", title_only=True, region="veneto", province="padova", town="padova",
                 category="telefonia", min_price=100, max_price=300, shipping_only=True, order="priceasc"),
    SearchParams(region="abruzzo", province="l-aquila", town="sulmona", category="appartamenti"),
    SearchParams(ad_type="h", category="case-vacanza"),
    SearchParams(ad_type="g", category="telefonia", region="sardegna", province="gallura"),
    SearchParams(ad_type="k", keywords="bici corsa", category="biciclette", order="pricedesc"),
    SearchParams(region="trentino-alto-adige", province="trento", town="calliano-tn"),
]


@pytest.fixture(scope="module")
def session():
    return requests.Session()


def state_of(session, url):
    time.sleep(1.5)  # rispetto per il sito
    r = session.get(url, headers=HEADERS, timeout=30)
    assert r.status_code == 200, f"{r.status_code} per {url}"
    return extract_next_data(r.text)["props"]["pageProps"]["initialState"]


@pytest.mark.parametrize("params", CASES, ids=lambda p: f"{p.ad_type}-{p.category}-{p.town or p.province or p.region}")
def test_site_interprets_params(session, params):
    ub = UrlBuilder()
    url = ub.build(params).url
    st = state_of(session, url)
    s = st["search"]
    geo = s.get("geo") or {}
    assert s["adType"] == params.ad_type
    assert s["category"]["friendly"] == params.category
    assert (geo.get("region") or {}).get("friendlyName") == (params.region or "italia")
    assert (geo.get("city") or {}).get("friendlyName") == params.province
    assert (geo.get("town") or {}).get("friendlyName") == params.town
    assert (s.get("query") or "") == params.keywords
    assert bool(s.get("qso")) == params.title_only
    assert bool(s.get("includeShippableOnly")) == params.shipping_only
    if params.order:
        assert s["category"]["orders"][s["orderIndex"]] == params.order
    filters = s.get("filters") or {}
    if params.min_price is not None:
        assert filters.get("ps") == str(params.min_price)
    if params.max_price is not None:
        assert filters.get("pe") == str(params.max_price)


def test_random_town_slugs_exist(session):
    """Campione di comuni (inclusi apostrofi e omonimi): la pagina deve esistere e riconoscerli."""
    import random

    geo = load_geo()
    rng = random.Random(42)
    tricky = [t for t in geo.towns if t.slug in ("paderno-d-adda", "samone-tn", "forli", "maiera")]
    sample = rng.sample(geo.towns, 6) + tricky
    ub = UrlBuilder()
    for t in sample:
        prov = next(p for p in geo.provinces if p.id == t.province_id)
        region = next(r for r in geo.regions if r.id == prov.region_id)
        url = ub.build(SearchParams(region=region.slug, province=prov.slug, town=t.slug, order=None)).url
        st = state_of(session, url)
        assert st["search"]["geo"]["town"]["friendlyName"] == t.slug, url
