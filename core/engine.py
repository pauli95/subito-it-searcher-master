"""Esecuzione delle ricerche: scarica, filtra, salva, notifica."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable

import requests

from .config import Settings
from .filters import excluded_by, price_in_range
from .models import RunResult, ScrapedAd, Search
from .notifier import Notifier
from .repo import Repository
from .scraper import ScrapeError, fetch_ads

FetchFn = Callable[[str, requests.Session], list[ScrapedAd]]


class Engine:
    def __init__(self, repo: Repository, settings: Settings, notifier: Notifier, events,
                 fetch: FetchFn | None = None, throttle: bool = True):
        self.repo = repo
        self.settings = settings
        self.notifier = notifier
        self.events = events
        self._fetch: FetchFn = fetch or fetch_ads
        self._throttle_enabled = throttle
        # Serializza le esecuzioni: scheduler e "Esegui ora" non vanno mai in parallelo.
        self._run_lock = threading.Lock()
        self._last_request = 0.0
        self._session = requests.Session()

    @property
    def busy(self) -> bool:
        return self._run_lock.locked()

    def _throttle(self) -> None:
        """Pausa minima + jitter casuale tra due richieste consecutive a subito.it."""
        if not self._throttle_enabled:
            return
        cfg = self.settings.get("monitor")
        gap = float(cfg.get("min_gap_sec") or 0) + random.uniform(0, float(cfg.get("jitter_sec") or 0))
        wait = self._last_request + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @staticmethod
    def apply_filters(search: Search, ads: list[ScrapedAd]) -> list[ScrapedAd]:
        """Filtri locali; gli annunci venduti passano sempre (servono a marcarli VENDUTO)."""
        return [a for a in ads if a.sold or (price_in_range(a.price, search.min_price, search.max_price)
                                             and excluded_by(a.title, search.exclude_words) is None)]

    def preview(self, url: str, search: Search | None = None) -> tuple[list[ScrapedAd], list[ScrapedAd]]:
        """Esegue la query senza salvare nulla: (annunci letti, annunci che passano i filtri)."""
        with self._run_lock:
            self._throttle()
            ads = self._fetch(url, self._session)
        matched = self.apply_filters(search, ads) if search else ads
        return ads, [a for a in matched if not a.sold]

    def _run(self, search: Search, notify: bool) -> RunResult:
        assert search.id is not None
        # phase start/end: l'interfaccia mostra "controllo in corso" tra i due eventi
        self.events.info(f"Eseguo la ricerca '{search.name}'", kind="query", search_id=search.id,
                         phase="start", name=search.name)
        self._throttle()
        started = time.monotonic()  # durata = solo la risposta del sito, senza la pausa di cortesia
        try:
            ads = self._fetch(search.url, self._session)
        except ScrapeError as e:
            return self._fail(search, str(e), e.kind, time.monotonic() - started)
        except Exception as e:  # imprevisto: segnalato senza interrompere le altre ricerche
            return self._fail(search, f"Errore imprevisto: {type(e).__name__}: {e}", "unexpected",
                              time.monotonic() - started)
        fetch_time = time.monotonic() - started

        matched = self.apply_filters(search, ads)
        outcome = self.repo.record_results(search.id, matched)
        self.repo.record_run(search.id, ok=True, found=len(ads), new=len(outcome.new))
        result = RunResult(search.id, search.name, True, found=len(ads),
                           matched=sum(1 for a in matched if not a.sold), new=outcome.new,
                           price_drops=outcome.price_drops, sold=outcome.sold, duration=fetch_time)

        if outcome.new:
            self.events.success(f"'{search.name}': {len(outcome.new)} nuovi annunci", kind="new_items",
                                search_id=search.id, count=len(outcome.new), phase="end",
                                items=[{"title": a.title, "price": a.price, "link": a.link}
                                       for a in outcome.new[:20]])
        else:
            self.events.info(f"'{search.name}': nessun nuovo annuncio ({len(ads)} letti, {result.matched} validi)",
                             kind="query", search_id=search.id, phase="end")
        for ad, old in outcome.price_drops:
            self.events.success(f"'{search.name}': ribasso {old} € → {ad.price} € — {ad.title}",
                                kind="price_drop", search_id=search.id, link=ad.link)
        if outcome.sold:
            self.events.info(f"'{search.name}': {outcome.sold} annunci venduti", kind="sold", search_id=search.id)

        if notify:
            new, drops = self.notification_targets(search, outcome.new, outcome.price_drops)
            self.notifier.notify(search.name, search.id, new, drops)
        return result

    @staticmethod
    def notification_targets(search: Search, new: list[ScrapedAd], drops: list[tuple[ScrapedAd, int]]
                             ) -> tuple[list[ScrapedAd], list[tuple[ScrapedAd, int]]]:
        """Regole per ricerca: notifica nuovi / anche ribassi, soglia di prezzo."""
        def under(ad: ScrapedAd) -> bool:
            return search.notify_max_price is None or ad.price is None or ad.price <= search.notify_max_price

        to_new = [a for a in new if under(a)] if search.notify_new else []
        to_drops = [(a, old) for a, old in drops if under(a)] if search.notify_price_drop else []
        return to_new, to_drops

    def _fail(self, search: Search, message: str, kind: str, duration: float = 0.0) -> RunResult:
        assert search.id is not None
        self.repo.record_run(search.id, ok=False, error=message)
        self.events.error(f"'{search.name}': {message}", kind="error", search_id=search.id, error_kind=kind,
                          phase="end")
        return RunResult(search.id, search.name, False, error=message, error_kind=kind, duration=duration)

    def run_search(self, search_id: int, notify: bool = True) -> RunResult:
        with self._run_lock:
            return self._run(self.repo.get_search(search_id), notify)

    def run_all(self, notify: bool = True, only_enabled: bool = True,
                should_stop: Callable[[], bool] | None = None) -> list[RunResult]:
        results = []
        with self._run_lock:
            for search in self.repo.list_searches():
                if only_enabled and not search.enabled:
                    continue
                if should_stop and should_stop():
                    break
                results.append(self._run(search, notify))
        return results
