"""Registro eventi: salvato nel database e inoltrato ai listener (SSE, console CLI)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from .models import now_iso
from .repo import Repository

logger = logging.getLogger("subito")

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "success": logging.INFO,
           "warning": logging.WARNING, "error": logging.ERROR}

Listener = Callable[[dict[str, Any]], None]


class EventLog:
    """Evento: {id, time, level, kind, message, search_id, ...dati extra}

    level: info | success | warning | error
    kind:  query | new_items | price_drop | sold | error | scheduler | notify | config | search | system
    """

    def __init__(self, repo: Repository):
        self.repo = repo
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        self._count = 0

    def add(self, message: str, level: str = "info", kind: str = "system",
            search_id: int | None = None, **data: Any) -> dict[str, Any]:
        stamp = now_iso()
        try:
            event_id = self.repo.add_event(stamp, level, kind, message, search_id, data or None)
        except Exception:  # il log non deve mai far fallire l'operazione che lo genera
            logger.exception("Impossibile salvare l'evento")
            event_id = 0
        event = {"id": event_id, "time": stamp, "level": level, "kind": kind,
                 "message": message, "search_id": search_id, **data}
        logger.log(_LEVELS.get(level, logging.INFO), message)
        with self._lock:
            listeners = list(self._listeners)
            self._count += 1
            prune = self._count % 500 == 0
        if prune:
            self.repo.prune_events()
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                logger.exception("Errore in un listener degli eventi")
        return event

    def since(self, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        return self.repo.events_after(after_id, limit)

    def subscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def info(self, message: str, **kw: Any) -> dict[str, Any]:
        return self.add(message, "info", **kw)

    def success(self, message: str, **kw: Any) -> dict[str, Any]:
        return self.add(message, "success", **kw)

    def warning(self, message: str, **kw: Any) -> dict[str, Any]:
        return self.add(message, "warning", **kw)

    def error(self, message: str, **kw: Any) -> dict[str, Any]:
        return self.add(message, "error", **kw)


def setup_file_logging(path, level: int = logging.INFO) -> None:
    """Log persistente su file (rotazione a 1 MB, 3 backup)."""
    from logging.handlers import RotatingFileHandler

    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
