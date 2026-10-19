#!/usr/bin/env python3
"""Prova l'URL builder da riga di comando (in attesa della UI).

Esempi:
  python tools/urltool.py luoghi Pad
  python tools/urltool.py categorie
  python tools/urltool.py analizza "https://www.subito.it/annunci-veneto/vendita/telefonia/padova/?q=iphone"
  python tools/urltool.py costruisci --parole "iphone 13" --luogo "Padova (PD)" --categoria telefonia --max 400 --spedizione
  python tools/urltool.py anteprima "https://www.subito.it/annunci-veneto/vendita/telefonia/?q=iphone" --escludi "rotto, cover"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.categories import load_catalog  # noqa: E402
from core.filters import excluded_by, parse_words, price_in_range  # noqa: E402
from core.geo import load_geo  # noqa: E402
from core.notifier import format_price  # noqa: E402
from core.scraper import ScrapeError, fetch_ads  # noqa: E402
from core.urlbuilder import SearchParams, UrlBuilder, UrlError  # noqa: E402


def cmd_luoghi(args) -> None:
    for loc in load_geo().search(args.testo, limit=args.n):
        print(f"{loc.label:<40} {loc.detail:<45} {json.dumps({k: v for k, v in loc.to_dict().items() if k in ('region', 'province', 'town')})}")


def cmd_categorie(args) -> None:
    cat = load_catalog()
    for c in cat.categories:
        indent = "    " if c.parent_id else ""
        types = ",".join(cat.ad_types[t].slug for t in c.ad_types)
        print(f"{indent}{c.slug:<28} {c.label:<34} tipi: {types:<38} prezzo sul sito: {'sì' if c.price_filter else 'no'}")


def cmd_analizza(args) -> None:
    try:
        r = UrlBuilder().parse(args.url)
    except UrlError as e:
        raise SystemExit(f"Non riconosciuto: {e}")
    print(json.dumps(r.params.to_dict(), ensure_ascii=False, indent=2))
    for w in r.warnings:
        print("Avviso:", w)
    print("URL ricostruito:", UrlBuilder().build(r.params).url)


def cmd_costruisci(args) -> None:
    p = SearchParams(keywords=args.parole or "", title_only=args.titolo, category=args.categoria,
                     ad_type=args.tipo, min_price=args.min, max_price=args.max, shipping_only=args.spedizione,
                     order=None if args.ordine == "sito" else args.ordine)
    if args.luogo:
        matches = load_geo().search(args.luogo, limit=1)
        if not matches:
            raise SystemExit(f"Località non trovata: {args.luogo}")
        loc = matches[0]
        print("Località:", loc.label, "-", loc.detail)
        p.region = loc.region.slug if loc.region else None
        p.province = loc.province.slug if loc.province else None
        p.town = loc.town.slug if loc.town else None
    try:
        r = UrlBuilder().build(p)
    except UrlError as e:
        raise SystemExit(f"Errore: {e}")
    print(r.url)
    for w in r.warnings:
        print("Avviso:", w)


def cmd_anteprima(args) -> None:
    words = parse_words(args.escludi)
    try:
        ads = fetch_ads(args.url)
    except ScrapeError as e:
        raise SystemExit(f"Errore: {e}")
    ok = [a for a in ads if price_in_range(a.price, args.min, args.max) and not excluded_by(a.title, words)]
    print(f"{len(ads)} annunci nella prima pagina, {len(ok)} dopo i filtri locali")
    for a in ok[:15]:
        print(f"  {format_price(a.price):>10}  {a.title[:60]:<60} {a.location}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("luoghi", help="autocompletamento località")
    s.add_argument("testo")
    s.add_argument("-n", type=int, default=10)
    s.set_defaults(func=cmd_luoghi)
    s = sub.add_parser("categorie", help="elenco categorie")
    s.set_defaults(func=cmd_categorie)
    s = sub.add_parser("analizza", help="URL -> parametri")
    s.add_argument("url")
    s.set_defaults(func=cmd_analizza)
    s = sub.add_parser("costruisci", help="parametri -> URL")
    s.add_argument("--parole")
    s.add_argument("--titolo", action="store_true", help="solo nel titolo")
    s.add_argument("--luogo", help="testo da cercare tra le località (si usa il primo risultato)")
    s.add_argument("--categoria", default="usato")
    s.add_argument("--tipo", default="s", choices=["s", "k", "u", "g", "h"])
    s.add_argument("--min", type=int)
    s.add_argument("--max", type=int)
    s.add_argument("--spedizione", action="store_true")
    s.add_argument("--ordine", default="datedesc", help="datedesc, relevance, priceasc, pricedesc, sito")
    s.set_defaults(func=cmd_costruisci)
    s = sub.add_parser("anteprima", help="esegue la ricerca senza salvarla")
    s.add_argument("url")
    s.add_argument("--min", type=int)
    s.add_argument("--max", type=int)
    s.add_argument("--escludi")
    s.set_defaults(func=cmd_anteprima)
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args.func(args)


if __name__ == "__main__":
    main()
