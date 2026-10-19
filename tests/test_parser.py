from __future__ import annotations

import pytest

from core.scraper import ScrapeError, ad_key_from, parse_page
from tests.conftest import items_of


def test_parse_real_page(page_html):
    ads = parse_page(page_html)
    assert len(ads) == 8
    first = ads[0]
    assert first.ad_key == "665091820"
    assert first.urn.endswith(":list:665091820")
    assert first.link == "https://www.subito.it/telefonia/iphone-venezia-665091820.htm"
    assert first.title == "Iphone"
    assert first.price == 50
    assert first.location == "Venezia (VE)"
    assert first.region == "Veneto"
    assert first.category == "telefonia"
    assert first.ad_type == "s"
    assert first.shipping is True
    assert first.sold is False
    assert first.published_at == "2026-10-19 11:37:56"
    assert first.image and first.image.startswith("https://images.sbito.it/")


def test_shipping_no_is_false_not_true(page_html):
    # Bug originale: value "No" è una stringa non vuota e veniva letta come "spedizione disponibile".
    ad = next(a for a in parse_page(page_html) if a.ad_key == "665061469")
    assert ad.shipping is False


def test_missing_shippable_feature_does_not_skip_ad(make_html):
    # Bug originale: senza /item_shippable l'annuncio veniva saltato in silenzio.
    def mutate(d):
        items_of(d)[0]["features"].pop("/item_shippable")
    ads = parse_page(make_html(mutate))
    assert len(ads) == 8
    assert ads[0].shipping is None


def test_missing_or_invalid_price(make_html):
    def mutate(d):
        items_of(d)[0]["features"].pop("/price")
        items_of(d)[1]["features"]["/price"]["values"][0]["key"] = "abc"
    ads = parse_page(make_html(mutate))
    assert ads[0].price is None and ads[1].price is None


def test_missing_geo_and_features(make_html):
    def mutate(d):
        for key in ("geo", "features", "images", "category", "type", "advertiser"):
            items_of(d)[0].pop(key)
    ad = parse_page(make_html(mutate))[0]
    assert ad.location == "Località sconosciuta"
    assert ad.price is None and ad.shipping is None and ad.image is None


def test_ad_without_link_is_ignored(make_html):
    def mutate(d):
        items_of(d)[0]["urls"] = {}
    assert len(parse_page(make_html(mutate))) == 7


def test_sold_flag(make_html):
    def mutate(d):
        items_of(d)[2]["sold"] = True
    assert parse_page(make_html(mutate))[2].sold is True


def test_duplicates_in_page_are_removed(make_html):
    def mutate(d):
        lst = items_of(d)
        lst.append(dict(lst[0]))
    assert len(parse_page(make_html(mutate))) == 8


def test_legacy_list_format(make_html):
    # Formato gestito dallo script originale: items.list[].item
    def mutate(d):
        items = d["props"]["pageProps"]["initialState"]["items"]
        items["list"] = [{"item": a} for a in items.pop("originalList")]
    assert len(parse_page(make_html(mutate))) == 8


def test_structure_errors(make_html):
    with pytest.raises(ScrapeError) as e:
        parse_page("<html><body>niente</body></html>")
    assert e.value.kind == "structure"

    def no_items(d):
        del d["props"]["pageProps"]["initialState"]["items"]
    with pytest.raises(ScrapeError) as e:
        parse_page(make_html(no_items))
    assert e.value.kind == "structure"

    def no_list(d):
        del d["props"]["pageProps"]["initialState"]["items"]["originalList"]
    with pytest.raises(ScrapeError):
        parse_page(make_html(no_list))


def test_ad_key_from():
    assert ad_key_from("id:ad:abc:list:123", None) == "123"
    assert ad_key_from(None, "https://www.subito.it/telefonia/iphone-venezia-665091820.htm") == "665091820"
    assert ad_key_from(None, "https://example.com/x") is None
