"""Monitoraggio in background (asyncio): sostituisce --daemon.

- modalità sincronizzata (predefinita): a ogni intervallo globale parte un "giro" che controlla tutte
  le ricerche una dopo l'altra, con un unico conto alla rovescia. Una ricerca con un intervallo proprio
  più lungo, o in backoff per errori, salta i giri finché non è il suo momento;
- modalità indipendente: ogni ricerca ha il suo intervallo (o quello globale) e il suo calendario;
- ogni ricerca può avere una sua fascia oraria;
- fascia oraria globale: fuori fascia il monitor resta "in pausa";
- le ricerche vengono eseguite una alla volta (l'engine aggiunge pausa minima + jitter tra le richieste);
- backoff esponenziale sugli errori di una ricerca; se subito.it blocca (403/429) si ferma tutto
  per un periodo crescente, perché il blocco riguarda l'indirizzo IP e non la singola ricerca;
- primo giro di ogni ricerca dopo l'avvio senza notifiche (come lo script originale);
- manutenzione giornaliera: pulizia annunci vecchi (se impostata) e del log eventi.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .models import RunResult, Search
from .timeutil import in_between, parse_hour

logger = logging.getLogger("subito")

MAX_BACKOFF = 2 * 3600       # secondi
BLOCK_PAUSE = 15 * 60        # pausa minima dopo un blocco del sito
TICK = 30                    # rivalutazione massima (secondi), anche senza eventi
MAINTENANCE_EVERY = 24 * 3600


def next_delay(interval: int, consecutive_errors: int, error_kind: str | None = None) -> float:
    """Secondi fino al prossimo controllo di una ricerca."""
    if consecutive_errors <= 0:
        return float(interval)
    delay = interval * 2 ** min(consecutive_errors, 6)
    if error_kind == "blocked":
        delay = max(delay, BLOCK_PAUSE)
    return float(min(delay, max(MAX_BACKOFF, interval)))


def block_pause(streak: int) -> float:
    """Pausa globale dopo `streak` blocchi consecutivi: 15, 30, 60, 120 minuti (max)."""
    return float(min(BLOCK_PAUSE * 2 ** max(0, streak - 1), MAX_BACKOFF))


def window_ok(now: datetime, start: str | None, end: str | None) -> bool:
    if not start or not end:
        return True
    return in_between(now.time(), parse_hour(start), parse_hour(end))


class Monitor:
    def __init__(self, engine, repo, settings, events, clock: Callable[[], float] = time.time):
        self.engine = engine
        self.repo = repo
        self.settings = settings
        self.events = events
        self.clock = clock
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self._stopping = False
        self.state = "stopped"          # stopped | running | checking | paused | cooldown
        self.started_at: float | None = None
        self.last_check: float | None = None
        self.current: int | None = None
        self.next_due: dict[int, float] = {}
        self.baseline: set[int] = set()  # ricerche già eseguite dopo l'avvio (da qui si notifica)
        self.cooldown_until: float | None = None
        self.block_streak = 0
        self.cycles = 0
        self.history: deque[dict[str, Any]] = deque(maxlen=50)
        self._last_maintenance = 0.0
        # modalità sincronizzata
        self.cycle_due = 0.0            # inizio del prossimo giro (0 = subito)
        self.cycle_started: float | None = None
        self.queue: list[int] = []      # ricerche ancora da controllare nel giro in corso

    # ------------------------------------------------------------------ controllo
    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> bool:
        if self.running:
            return False
        self._stopping = False
        self._wake = asyncio.Event()
        self.started_at = self.clock()
        self.baseline.clear()
        self.next_due.clear()
        self.cooldown_until = None
        self.block_streak = 0
        self.cycle_due, self.cycle_started, self.queue = 0.0, None, []
        self.state = "running"
        self._task = asyncio.create_task(self._loop(), name="subito-monitor")
        cfg = self.settings.get("monitor")
        self.events.info(f"Monitor avviato (intervallo predefinito {cfg['interval_sec']} s, "
                         f"fascia {cfg['active_from']}–{cfg['active_to']})", kind="scheduler")
        return True

    async def stop(self) -> bool:
        if not self.running:
            return False
        self._stopping = True
        self.wake()
        task = self._task
        try:
            # una ricerca in corso non si può interrompere: si aspetta che finisca (max ~1 min)
            await asyncio.wait_for(asyncio.shield(task), timeout=90)
        except asyncio.TimeoutError:
            task.cancel()
        self.events.info("Monitor fermato", kind="scheduler")
        return True

    def wake(self) -> None:
        """Rivaluta subito (impostazioni o ricerche cambiate)."""
        if self._wake is not None:
            self._wake.set()

    def note_run(self, result: RunResult) -> None:
        """Esecuzione manuale ("Esegui ora"): riparte l'intervallo e la ricerca entra nel giro."""
        self._record(result)
        if result.ok:
            self.baseline.add(result.search_id)
        try:
            search = self.repo.get_search(result.search_id)
        except LookupError:
            return
        self.next_due[result.search_id] = self.clock() + self._delay_for(search, result)
        self.wake()

    def note_cycle(self) -> None:
        """Esecuzione manuale di tutte le ricerche: in modalità sincronizzata vale come un giro."""
        if self.sync:
            now = self.clock()
            self.cycle_started = now
            self.cycle_due = now + self._cycle_interval()
            self.wake()

    # ------------------------------------------------------------------ calcoli
    @property
    def sync(self) -> bool:
        return bool(self.settings.get("monitor").get("sync", True))

    def _cycle_interval(self) -> float:
        cfg = self.settings.get("monitor")
        return float(cfg["interval_sec"]) + random.uniform(0, float(cfg.get("jitter_sec") or 0))

    def _tolerance(self) -> float:
        """Una ricerca entra nel giro se è "quasi" il suo momento: le ricerche dello stesso giro
        partono a qualche secondo di distanza e non devono slittare al giro successivo."""
        return float(self.settings.get("monitor")["interval_sec"]) * 0.5

    def _cycle_for(self, due: float) -> float:
        """Inizio del primo giro in cui partirà una ricerca con scadenza `due`."""
        start, step = self.cycle_due, float(self.settings.get("monitor")["interval_sec"])
        for _ in range(1000):
            if due <= start + self._tolerance():
                break
            start += step
        return start

    def _interval(self, search: Search) -> int:
        return int(search.interval_sec or self.settings.get("monitor")["interval_sec"])

    def _delay_for(self, search: Search, result: RunResult | None) -> float:
        errors = search.consecutive_errors
        kind = result.error_kind if result else None
        delay = next_delay(self._interval(search), errors, kind)
        jitter = float(self.settings.get("monitor").get("jitter_sec") or 0)
        return delay + random.uniform(0, jitter)

    def _eligible(self, now: datetime) -> list[Search]:
        return [s for s in self.repo.list_searches()
                if s.enabled and window_ok(now, s.active_from, s.active_to)]

    def global_window_ok(self, now: datetime | None = None) -> bool:
        cfg = self.settings.get("monitor")
        start, end = cfg.get("active_from"), cfg.get("active_to")
        return window_ok(now or datetime.now(), start, end) if start != end else True

    # ------------------------------------------------------------------ ciclo
    async def _loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    wait = await self._step()
                except Exception as e:  # il monitor non deve mai fermarsi per un errore
                    logger.exception("Errore nel monitor")
                    self.events.error(f"Errore interno del monitor: {type(e).__name__}: {e}", kind="scheduler")
                    wait = 10
                await self._sleep(wait)
        finally:
            self.state = "stopped"
            self.current = None

    async def _sleep(self, seconds: float) -> None:
        if self._stopping or self._wake is None:
            return
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=max(0.05, min(seconds, TICK)))
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    async def _step(self) -> float:
        """Un passo del ciclo; restituisce quanti secondi attendere prima del successivo."""
        now_ts = self.clock()
        now = datetime.fromtimestamp(now_ts)
        if now_ts - self._last_maintenance >= MAINTENANCE_EVERY:
            await asyncio.to_thread(self._maintenance)
            self._last_maintenance = now_ts

        if self.cooldown_until and now_ts < self.cooldown_until:
            self.state = "cooldown"
            return self.cooldown_until - now_ts
        self.cooldown_until = None

        if not self.global_window_ok(now):
            self.state = "paused"
            return TICK

        searches = self._eligible(now)
        for s in searches:
            self.next_due.setdefault(s.id, now_ts)  # mai eseguite da questo avvio: subito
        if self.sync:
            picked = self._next_in_cycle(searches, now_ts)
            if isinstance(picked, float):
                self.state = "running"
                return picked
            search_id = picked
        else:
            due = sorted((self.next_due[s.id], s.id) for s in searches if self.next_due[s.id] <= now_ts)
            if not due:
                self.state = "running"
                upcoming = [self.next_due[s.id] for s in searches]
                return (min(upcoming) - now_ts) if upcoming else TICK
            search_id = due[0][1]
        return await self._run_one(search_id)

    def _next_in_cycle(self, searches: list[Search], now_ts: float) -> int | float:
        """Modalità sincronizzata: id della prossima ricerca del giro, oppure i secondi da attendere."""
        eligible = {s.id for s in searches}
        self.queue = [sid for sid in self.queue if sid in eligible]   # disattivate/eliminate nel frattempo
        if not self.queue:
            if self.cycle_started is not None:   # intervallo accorciato dalle impostazioni: vale subito
                interval = float(self.settings.get("monitor")["interval_sec"])
                self.cycle_due = min(self.cycle_due, self.cycle_started + interval)
            if now_ts < self.cycle_due:
                return float(self.cycle_due - now_ts)
            limit = now_ts + self._tolerance()
            self.queue = [s.id for s in searches if self.next_due[s.id] <= limit]
            self.cycle_started = now_ts
            self.cycle_due = now_ts + self._cycle_interval()
            if not self.queue:
                return float(self.cycle_due - now_ts)
            if len(self.queue) > 1:
                self.events.info(f"Giro di controllo: {len(self.queue)} ricerche", kind="scheduler")
        return self.queue.pop(0)

    async def _run_one(self, search_id: int) -> float:
        notify = search_id in self.baseline or not self.settings.get("monitor").get("first_run_silent", True)
        self.state, self.current = "checking", search_id
        try:
            result = await asyncio.to_thread(self.engine.run_search, search_id, notify)
        finally:
            self.current = None
            self.state = "running"
        self.last_check = self.clock()
        self.cycles += 1
        self._record(result)
        if result.ok:
            self.baseline.add(search_id)
            self.block_streak = 0
        elif result.error_kind == "blocked":
            self.block_streak += 1
            pause = block_pause(self.block_streak)
            self.cooldown_until = self.clock() + pause
            self.events.warning(f"subito.it sta bloccando le richieste: monitor in pausa per "
                                f"{int(pause // 60)} minuti", kind="scheduler")
            self.queue.clear()   # il resto del giro riparte dopo la pausa
        try:
            search = self.repo.get_search(search_id)
        except LookupError:  # eliminata durante l'esecuzione
            self.next_due.pop(search_id, None)
            return 0
        if self.sync:   # niente jitter qui: il ritmo lo dà il giro
            self.next_due[search_id] = self.clock() + next_delay(
                self._interval(search), search.consecutive_errors, result.error_kind)
        else:
            self.next_due[search_id] = self.clock() + self._delay_for(search, result)
        return 0

    def _record(self, result: RunResult) -> None:
        self.history.appendleft({
            "time": datetime.now().isoformat(timespec="seconds"), "search_id": result.search_id,
            "name": result.name, "ok": result.ok, "error": result.error, "error_kind": result.error_kind,
            "found": result.found, "new": len(result.new), "duration": round(result.duration, 2),
        })

    def _maintenance(self) -> None:
        days = int(self.settings.get("maintenance").get("cleanup_days") or 0)
        removed = self.repo.cleanup_ads(days)
        if removed:
            self.events.info(f"Pulizia: eliminati {removed} annunci non visti da più di {days} giorni",
                             kind="system")
        self.repo.prune_events()

    # ------------------------------------------------------------------ stato
    def status(self) -> dict[str, Any]:
        cfg = self.settings.get("monitor")
        running = self.running
        upcoming = []
        if running and self.sync:
            upcoming = [self.clock() if self.queue else self.cycle_due]
        elif running:
            enabled = {s.id for s in self.repo.list_searches() if s.enabled}
            upcoming = [t for sid, t in self.next_due.items() if sid in enabled]
        return {
            "state": self.state if running else "stopped",
            "running": running,
            "busy": self.engine.busy,
            "current": self.current,
            "started_at": _iso(self.started_at),
            "last_check": _iso(self.last_check),
            "next_check": _iso(min(upcoming)) if upcoming and self.state != "cooldown" else
            _iso(self.cooldown_until) if running else None,
            "cooldown_until": _iso(self.cooldown_until),
            "cycles": self.cycles,
            "in_window": self.global_window_ok(),
            "sync": self.sync,
            "queue": len(self.queue),
            "settings": cfg,
        }

    def next_due_iso(self, search_id: int) -> str | None:
        if not self.running:
            return None
        if self.sync:
            if search_id in self.queue:
                return _iso(self.clock())
            due = self.next_due.get(search_id)
            return _iso(self._cycle_for(due) if due is not None else self.cycle_due)
        return _iso(self.next_due.get(search_id))

    def health(self) -> dict[str, Any]:
        recent = list(self.history)
        structure = [r for r in recent[:10] if r["error_kind"] == "structure"]
        ok_runs = [r for r in recent if r["ok"]][:5]
        empty = len(ok_runs) >= 3 and all(r["found"] == 0 for r in ok_runs) \
            and len({r["search_id"] for r in ok_runs}) >= 2
        alerts = []
        if structure:
            alerts.append("La struttura della pagina di subito.it sembra cambiata: " + structure[0]["error"])
        elif empty:
            alerts.append("Le ultime ricerche non trovano nessun annuncio: la struttura del sito potrebbe "
                          "essere cambiata")
        if self.cooldown_until:
            alerts.append(f"subito.it sta bloccando le richieste: pausa fino alle "
                          f"{datetime.fromtimestamp(self.cooldown_until):%H:%M}")
        searches = [{"id": s.id, "name": s.name, "enabled": s.enabled, "consecutive_errors": s.consecutive_errors,
                     "last_error": s.last_error, "last_ok_at": s.last_ok_at, "last_run_at": s.last_run_at,
                     "next_due": self.next_due_iso(s.id)} for s in self.repo.list_searches()]
        return {"alerts": alerts, "recent": recent, "searches": searches,
                "errors_total": sum(s["consecutive_errors"] for s in searches)}


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None
