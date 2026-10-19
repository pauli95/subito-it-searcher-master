#!/usr/bin/env python3
"""Interfaccia a riga di comando di Subito Searcher (stesse opzioni della versione originale).

I dati stanno nel database data/subito.db; al primo avvio vengono importati
automaticamente searches.tracked, telegram_api_credentials e ntfy_config.
"""

from __future__ import annotations

import argparse
import sys
import time as t
from datetime import datetime
from typing import Any

from core import App, Conflict, Search, UrlError
from core.filters import parse_words
from core.notifier import format_price
from core.timeutil import in_between, parse_hour


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--add", dest='name', help="name of new tracking to be added")
    parser.add_argument("--url", help="url for your new tracking's search query")
    parser.add_argument("--minPrice", type=int, help="minimum price for the query")
    parser.add_argument("--maxPrice", type=int, help="maximum price for the query")
    parser.add_argument("--exclude", help="comma separated words to exclude from titles (new)")
    parser.add_argument("--delete", help="name of the search you want to delete")
    parser.add_argument('--refresh', '-r', dest='refresh', action='store_true', help="refresh search results once")
    parser.add_argument('--daemon', '-d', dest='daemon', action='store_true',
                        help="keep refreshing search results forever (default delay 120 seconds)")
    parser.add_argument('--activeHour', '-ah', dest='activeHour', default="0",
                        help="Time slot. Hour when to be active in 24h notation")
    parser.add_argument('--pauseHour', '-ph', dest='pauseHour', default="0",
                        help="Time slot. Hour when to pause in 24h notation")
    parser.add_argument('--delay', dest='delay', type=int, default=120, help="delay for the daemon option (in seconds)")
    parser.add_argument('--list', dest='list', action='store_true', help="print a list of current trackings")
    parser.add_argument('--short_list', dest='short_list', action='store_true', help="print a more compact list")
    parser.add_argument('--tgoff', dest='tgoff', action='store_true', help="turn off telegram messages")
    parser.add_argument('--notifyoff', dest='win_notifyoff', action='store_true', help="turn off windows notifications")
    parser.add_argument('--addtoken', dest='token', help="telegram setup: add bot API token")
    parser.add_argument('--addchatid', dest='chatid', help="telegram setup: add bot chat id")
    parser.add_argument('--ntfy_server', dest='ntfy_server', help="Set ntfy server URL")
    parser.add_argument('--ntfy_topic', dest='ntfy_topic', help="Set ntfy topic for notifications")
    parser.add_argument('--ntfyoff', dest='ntfyoff', action='store_true', help="Turn off ntfy notifications")
    return parser


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d, %H:%M:%S")


def print_event(event: dict[str, Any]) -> None:
    print(f"{stamp()} {event['message']}")
    for item in event.get("items") or []:
        print(f"    {item['title']} : {format_price(item['price'])} --> {item['link']}")


def price_range(s: Search) -> str:
    if s.min_price is None and s.max_price is None:
        return ""
    lo = f"{s.min_price} < " if s.min_price is not None else ""
    hi = f" < {s.max_price}" if s.max_price is not None else ""
    return f"  {lo}price{hi}"


def print_queries(app: App) -> None:
    for s in app.repo.list_searches():
        print("\nsearch: ", s.name)
        print("query url:", s.url)
        for ad in app.repo.ads_for_search(s.id):
            print("\n", ad["title"], ":", format_price(ad["price"]), "-->", ad["location"])
            print(" ", ad["link"])


def print_sitrep(app: App) -> None:
    for i, s in enumerate(app.repo.list_searches(), 1):
        state = "" if s.enabled else "  [disattivata]"
        print(f"\n{i}) search: {s.name}{state}  ({app.repo.count_ads(s.id)} annunci)")
        print(f"query url: {s.url}{price_range(s)}")
        if s.exclude_words:
            print("escludi:", ", ".join(s.exclude_words))


def main(argv: list[str] | None = None) -> None:
    # Titoli con emoji non devono far crashare la stampa su console/file cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        parser.print_help()
        return
    args = parser.parse_args(argv)

    # --tgoff/--notifyoff/--ntfyoff valgono solo per questa esecuzione.
    overrides = {}
    if args.tgoff:
        overrides["telegram"] = False
    if args.win_notifyoff:
        overrides["windows"] = False
    if args.ntfyoff:
        overrides["ntfy"] = False

    app = App(notify_overrides=overrides)
    if app.import_report and app.import_report["files"]:
        r = app.import_report
        print(f"{stamp()} Importati {r['searches']} ricerche e {r['ads']} annunci da: {', '.join(r['files'])}")
    app.events.subscribe(print_event)

    if args.list:
        print(stamp() + " printing current status...")
        print_queries(app)

    if args.short_list:
        print(stamp() + " printing quick sitrep...")
        print_sitrep(app)

    if args.url is not None and args.name is not None:
        if not args.url.lower().startswith(("https://www.subito.it/", "http://www.subito.it/",
                                            "https://subito.it/")):
            parser.error("--url deve essere un indirizzo di ricerca di subito.it")
        params = None
        try:
            parsed = app.urls.parse(args.url)
            params = parsed.params
            params.min_price, params.max_price = args.minPrice, args.maxPrice
            for warning in parsed.warnings:
                print(stamp() + " Avviso: " + warning)
        except UrlError as e:
            print(stamp() + f" Avviso: {e} (la ricerca viene salvata solo come URL)")
        search = Search(id=None, name=args.name, url=args.url, min_price=args.minPrice,
                        max_price=args.maxPrice, exclude_words=parse_words(args.exclude),
                        params=params.to_dict() if params else None)
        existing = app.repo.find_search(args.name)
        try:
            # come l'originale: --add con un nome esistente sostituisce la ricerca
            saved = (app.repo.update_search(existing.id, search, reset_results=True) if existing
                     else app.repo.create_search(search))
        except Conflict as e:
            parser.error(str(e))
        app.engine.run_search(saved.id, notify=False)  # primo giro senza notifiche
        app.repo.mark_seen(saved.id)
        print(stamp() + " Query added.")

    if args.delete is not None:
        existing = app.repo.find_search(args.delete)
        if existing:
            app.repo.delete_search(existing.id)
            print(stamp() + f" Query \"{args.delete}\" deleted.")
        else:
            print(stamp() + f" Ricerca '{args.delete}' non trovata")

    if args.ntfy_server is not None and args.ntfy_topic is not None:
        app.settings.update("ntfy", {"server": args.ntfy_server, "topic": args.ntfy_topic})
        print(stamp() + " ntfy configuration saved.")

    if args.token is not None and args.chatid is not None:
        app.settings.update("telegram", {"token": args.token, "chatid": args.chatid})
        print(stamp() + " Telegram configuration saved.")

    if args.refresh:
        app.engine.run_all(notify=True)

    if args.daemon:
        try:
            start, end = parse_hour(args.activeHour), parse_hour(args.pauseHour)
        except ValueError as e:
            parser.error(str(e))
        notify = False  # primo giro senza notifiche, per non riceverne decine
        try:
            while True:
                if in_between(datetime.now().time(), start, end):
                    app.engine.run_all(notify=notify)
                    notify = True
                    print(f"\n{args.delay} seconds to next poll.")
                t.sleep(args.delay)
        except KeyboardInterrupt:
            print("\nStopped.")
    app.close()


if __name__ == '__main__':
    main()
