"""Strumenti comuni ai test: annunci finti e un fetch senza rete."""

from __future__ import annotations

from core.models import ScrapedAd


def make_ad(key: str, price: int | None = 100, title: str | None = None, **kw) -> ScrapedAd:
    return ScrapedAd(ad_key=key, urn=f"id:ad:x:list:{key}", link=f"https://www.subito.it/x/a-{key}.htm",
                     title=title or f"Annuncio {key}", price=price, town="Padova", province="PD", region="Veneto",
                     category="telefonia", ad_type="s", shipping=True, company=False, image=None,
                     published_at=None, **kw)


class FakeFetch:
    """Restituisce gli annunci configurati per URL; un'eccezione se configurata. Conta le chiamate."""

    def __init__(self):
        self.pages: dict[str, list[ScrapedAd] | Exception] = {}
        self.default: list[ScrapedAd] = []
        self.calls: list[str] = []

    def __call__(self, url, session=None):
        self.calls.append(url)
        page = self.pages.get(url, self.default)
        if isinstance(page, Exception):
            raise page
        return list(page)
