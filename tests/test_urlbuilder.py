from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

import pytest

from core.geo import load_geo, slugify
from core.urlbuilder import SearchParams, UrlBuilder, UrlError


@pytest.fixture(scope="module")
def ub() -> UrlBuilder:
    return UrlBuilder()


# ------------------------------------------------------------------ build

def test_default_is_all_italy_all_categories_newest_first(ub):
    assert ub.build(SearchParams()).url == "https://www.subito.it/annunci-italia/vendita/usato/?order=datedesc"


def test_full_town_search(ub):
    p = SearchParams(keywords="iphone  13 pro", title_only=True, region="veneto", province="padova",
                     town="padova", category="telefonia", min_price=100, max_price=300, shipping_only=True)
    r = ub.build(p)
    assert r.url == ("https://www.subito.it/annunci-veneto/vendita/telefonia/padova/padova/"
                     "?q=iphone+13+pro&qso=true&shp=true&ps=100&pe=300&order=datedesc")
    assert r.price_on_site and r.warnings == []
    assert r.location.label == "Padova (PD)"


def test_region_and_province_only(ub):
    assert ub.build(SearchParams(region="lombardia", order=None)).url == \
        "https://www.subito.it/annunci-lombardia/vendita/usato/"
    assert ub.build(SearchParams(region="valle-d-aosta", province="aosta", order=None)).url == \
        "https://www.subito.it/annunci-valle-d-aosta/vendita/usato/aosta/"


@pytest.mark.parametrize("ad_type, slug, category", [
    ("s", "vendita", "usato"), ("k", "cerco", "usato"), ("g", "regalo", "telefonia"),
    ("u", "affitto", "appartamenti"), ("h", "affitto-vacanze", "case-vacanza"),
])
def test_ad_type_slugs(ub, ad_type, slug, category):
    url = ub.build(SearchParams(ad_type=ad_type, category=category, order=None)).url
    assert url == f"https://www.subito.it/annunci-italia/{slug}/{category}/"


def test_price_not_supported_on_all_categories(ub):
    # Verificato: su "usato" il sito ignora ps/pe -> non nell'URL, filtro solo locale
    r = ub.build(SearchParams(keywords="tv", min_price=50))
    assert "ps=" not in r.url and not r.price_on_site
    assert r.warnings and "applicato dall'app" in r.warnings[0]


def test_title_only_without_keywords_is_ignored(ub):
    r = ub.build(SearchParams(title_only=True, order=None))
    assert "qso" not in r.url and r.warnings


def test_order_not_available_for_category(ub):
    r = ub.build(SearchParams(category="motori", order="relevance"))
    assert "order=" not in r.url and r.warnings


def test_extra_params_are_kept(ub):
    r = ub.build(SearchParams(category="telefonia", order=None, extra={"advt": "0", "q": "ignorato"}))
    assert r.url.endswith("/telefonia/?advt=0")


def test_special_characters_in_keywords(ub):
    url = ub.build(SearchParams(keywords="d'epoca & c++ 50%", order=None)).url
    assert url.endswith("?q=d%27epoca+%26+c%2B%2B+50%25")
    assert ub.parse(url).params.keywords == "d'epoca & c++ 50%"


@pytest.mark.parametrize("params, message", [
    (SearchParams(category="inesistente"), "Categoria"),
    (SearchParams(ad_type="x"), "Tipo"),
    (SearchParams(category="auto", ad_type="g"), "non è disponibile"),
    (SearchParams(region="atlantide"), "Regione"),
    (SearchParams(region="veneto", province="milano"), "Provincia"),
    (SearchParams(region="veneto", province="padova", town="vicenza"), "Comune"),
    (SearchParams(province="padova"), "senza regione"),
    (SearchParams(region="veneto", town="padova"), "senza provincia"),
    (SearchParams(category="telefonia", min_price=300, max_price=100), "minimo"),
    (SearchParams(category="telefonia", min_price=-1), "negativo"),
])
def test_invalid_params(ub, params, message):
    with pytest.raises(UrlError, match=message):
        ub.build(params)


# ------------------------------------------------------------------ parse (operazione inversa)

@pytest.mark.parametrize("url", [
    "https://www.subito.it/annunci-italia/vendita/usato/",
    "https://www.subito.it/annunci-veneto/vendita/telefonia/padova/padova/?q=iphone&qso=true&shp=true&ps=100&pe=300&order=datedesc",
    "https://www.subito.it/annunci-abruzzo/vendita/appartamenti/l-aquila/sulmona/",
    "https://www.subito.it/annunci-campania/affitto/immobili/benevento/san-giorgio-del-sannio/",
    "https://www.subito.it/annunci-italia/affitto-vacanze/case-vacanza/",
    "https://www.subito.it/annunci-emilia-romagna/vendita/offerte-lavoro/parma/?q=autista",
    "https://www.subito.it/annunci-italia/vendita/telefonia/?q=iphone&advt=0&order=priceasc",
])
def test_round_trip(ub, url):
    # stesso percorso e stessi parametri (l'ordine nella query string è irrilevante per il sito)
    rebuilt = urlsplit(ub.build(ub.parse(url).params).url)
    original = urlsplit(url)
    assert rebuilt.path == original.path
    assert sorted(parse_qsl(rebuilt.query)) == sorted(parse_qsl(original.query))


def test_parse_fields(ub):
    r = ub.parse("https://www.subito.it/annunci-veneto/vendita/telefonia/padova/?q=iphone+13&shp=true&ps=1.000")
    p = r.params
    assert (p.region, p.province, p.town, p.category, p.ad_type) == ("veneto", "padova", None, "telefonia", "s")
    assert p.keywords == "iphone 13" and p.shipping_only and not p.title_only
    assert p.min_price == 1000 and p.max_price is None
    assert p.order is None   # assente nell'URL: si conserva il comportamento del sito


def test_parse_tolerant_inputs(ub):
    assert ub.parse("subito.it/annunci-italia/vendita/usato").params.category == "usato"
    assert ub.parse("https://WWW.SUBITO.IT/annunci-italia/vendita/usato/").params.category == "usato"


def test_parse_keeps_unknown_params(ub):
    r = ub.parse("https://www.subito.it/annunci-italia/vendita/telefonia/?advt=0&ic=10")
    assert r.params.extra == {"advt": "0", "ic": "10"} and r.warnings


@pytest.mark.parametrize("url, message", [
    ("https://www.google.com/annunci-italia/vendita/usato/", "subito.it"),
    ("https://www.subito.it/telefonia/iphone-venezia-665091820.htm", "ricerca"),
    ("https://www.subito.it/annunci-italia/noleggio/usato/", "Tipo"),
    ("https://www.subito.it/annunci-italia/vendita/astronavi/", "Categoria"),
    ("https://www.subito.it/annunci-italia/vendita/auto/ford/mondeo/", "marca/modello"),
    ("https://www.subito.it/annunci-veneto/vendita/usato/milano/", "Provincia"),
    ("", "vuoto"),
])
def test_parse_errors(ub, url, message):
    with pytest.raises(UrlError, match=message):
        ub.parse(url)


def test_legacy_url_from_searches_tracked(ub):
    url = "https://www.subito.it/annunci-veneto/vendita/elettronica/?q=tv"
    p = ub.parse(url).params
    assert (p.region, p.category, p.keywords) == ("veneto", "elettronica", "tv")
    assert ub.build(p).url == url


# ------------------------------------------------------------------ località

def test_slugify_rule():
    assert slugify("Paderno d'Adda") == "paderno-d-adda"
    assert slugify("Forlì-Cesena") == "forli-cesena"
    assert slugify("  Reggio nell'Emilia ") == "reggio-nell-emilia"


def test_geo_data_consistency():
    geo = load_geo()
    assert len(geo.regions) == 20
    assert len(geo.provinces) >= 100
    assert len(geo.towns) > 7800
    # regola degli slug valida per tutti i comuni (anche con nomi accentati presi da ISTAT)
    assert [t.name for t in geo.towns if slugify(t.name) != t.slug] == []
    # province con la stessa chiave in regioni diverse (Padova e Brescia) restano distinte
    pd = geo.resolve("veneto", "padova")
    bs = geo.resolve("lombardia", "brescia")
    assert pd.province.id != bs.province.id


def test_autocomplete_pad():
    labels = [loc.label for loc in load_geo().search("Pad")[:3]]
    assert labels[:2] == ["Padova (provincia)", "Padova (PD)"]


def test_autocomplete_accents_and_codes():
    geo = load_geo()
    assert geo.search("forli")[0].label.startswith("Forlì")
    assert geo.search("italia")[0].kind == "italia"
    assert geo.search("PD")[0].label == "Padova (provincia)"
    assert geo.search("veneto")[0].kind == "region"
    assert geo.search("") == []


def test_homonyms_have_distinct_slugs():
    geo = load_geo()
    towns = [loc for loc in geo.search("calliano", limit=5) if loc.kind == "town"]
    assert {t.town.slug for t in towns} >= {"calliano", "calliano-tn"}


def test_autocomplete_accepts_own_labels():
    geo = load_geo()
    assert geo.search("Padova (PD)")[0].label == "Padova (PD)"
    assert geo.search("Padova (provincia)")[0].label == "Padova (provincia)"
    assert geo.search("Calliano TN")[0].town.slug == "calliano-tn"
    assert geo.search("san vito lo")[0].town.slug == "san-vito-lo-capo"   # "LO" non è inteso come Lodi


def test_category_labels_are_readable():
    from core.categories import load_catalog

    labels = {c.slug: c.label for c in load_catalog().categories}
    assert labels["casa-e-persona"] == "Per la casa e la persona"
    assert labels["elettronica"] == "Elettronica"
    assert labels["telefonia"] == "Telefonia"
