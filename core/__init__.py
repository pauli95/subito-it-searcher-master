"""Logica riutilizzabile di Subito Searcher (usata dalla web app e dalla CLI)."""

from __future__ import annotations

from .autostart import Autostart, AutostartError
from .config import Paths, Settings
from .db import Database
from .engine import Engine
from .events import EventLog, setup_file_logging
from .importer import convert_legacy_params, import_legacy
from .models import RunResult, ScrapedAd, Search
from .monitor import Monitor
from .notifier import Notifier, NotifyError
from .repo import Conflict, NotFound, Repository
from .scraper import ScrapeError
from .service import BackupService, InputError, SearchService
from .urlbuilder import SearchParams, UrlBuilder, UrlError


class App:
    """Contenitore con tutti i servizi collegati. Al primo avvio importa i vecchi file."""

    def __init__(self, paths: Paths | None = None, notify_overrides: dict[str, bool] | None = None,
                 file_logging: bool = True, throttle: bool = True):
        self.paths = paths or Paths.default()
        if file_logging:
            setup_file_logging(self.paths.log)
        self.db = Database(self.paths.db)
        self.repo = Repository(self.db)
        self.settings = Settings(self.repo)
        self.events = EventLog(self.repo)
        self.notifier = Notifier(self.settings, self.events, notify_overrides)
        self.engine = Engine(self.repo, self.settings, self.notifier, self.events, throttle=throttle)
        self.import_report = import_legacy(self.paths, self.repo, self.settings, self.events)
        self.urls = UrlBuilder()
        convert_legacy_params(self.repo, self.urls, self.events)
        self.searches = SearchService(self.repo, self.urls, self.engine, self.events)
        self.backups = BackupService(self.db, self.paths.backups, self.events)
        self.monitor = Monitor(self.engine, self.repo, self.settings, self.events)
        self.autostart = Autostart()

    def close(self) -> None:
        self.db.close()


__all__ = [
    "App", "Autostart", "AutostartError", "BackupService", "Conflict", "InputError", "Monitor", "SearchService", "Database", "Engine", "EventLog", "NotFound", "Notifier", "NotifyError", "Paths",
    "Repository", "RunResult", "ScrapeError", "ScrapedAd", "Search", "SearchParams", "Settings",
    "UrlBuilder", "UrlError",
]
