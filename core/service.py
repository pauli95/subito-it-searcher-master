"""Operazioni di alto livello usate dalle API: ricerche da form, export/import, anteprima, backup."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .filters import parse_words
from .models import Search, now_iso
from .repo import Conflict, Repository
from .scraper import MAX_RESULTS
from .timeutil import format_hour
from .urlbuilder import SearchParams, UrlBuilder, UrlError

MIN_INTERVAL = 60          # secondi: limite minimo per non sovraccaricare il sito
EXPORT_VERSION = 1
_URL_HOSTS = ("https://www.subito.it/", "http://www.subito.it/", "https://subito.it/", "https://m.subito.it/")


class InputError(ValueError):
    """Dati del form non validi (messaggio mostrabile all'utente)."""


def _opt_int(value: Any, field: str, minimum: int | None = 0) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as e:
        raise InputError(f"{field}: numero non valido") from e
    if minimum is not None and number < minimum:
        raise InputError(f"{field}: deve essere almeno {minimum}")
    return number


def _opt_hour(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return format_hour(value)
    except ValueError as e:
        raise InputError(f"{field}: {e}") from e


class SearchService:
    def __init__(self, repo: Repository, urls: UrlBuilder, engine, events):
        self.repo = repo
        self.urls = urls
        self.engine = engine
        self.events = events

    # ------------------------------------------------------------------ form -> Search
    def resolve_query(self, data: dict[str, Any]) -> dict[str, Any]:
        """Dal form: URL finale, parametri (o None se solo URL), prezzi per il filtro locale, avvisi."""
        params_data = data.get("params")
        if params_data is not None and data.get("mode", "params") == "params":
            try:
                params = SearchParams.from_dict(params_data)
                built = self.urls.build(params)
            except (UrlError, ValueError, TypeError) as e:
                raise InputError(str(e)) from e
            return {"url": built.url, "params": params.to_dict(), "min_price": params.min_price,
                    "max_price": params.max_price, "warnings": built.warnings,
                    "location": built.location.to_dict(), "price_on_site": built.price_on_site}

        url = (data.get("url") or "").strip()
        if not url.lower().startswith(_URL_HOSTS):
            raise InputError("L'URL deve essere una ricerca di subito.it (https://www.subito.it/annunci-…)")
        min_p = _opt_int(data.get("min_price"), "Prezzo minimo")
        max_p = _opt_int(data.get("max_price"), "Prezzo massimo")
        try:
            parsed = self.urls.parse(url)
        except UrlError as e:
            return {"url": url, "params": None, "min_price": min_p, "max_price": max_p,
                    "warnings": [f"{e}"], "location": None, "price_on_site": False}
        params = parsed.params
        params.min_price = params.min_price if min_p is None else min_p
        params.max_price = params.max_price if max_p is None else max_p
        return {"url": url, "params": params.to_dict(), "min_price": params.min_price,
                "max_price": params.max_price, "warnings": parsed.warnings,
                "location": None, "price_on_site": False}

    def search_from_input(self, data: dict[str, Any], base: Search | None = None) -> tuple[Search, list[str]]:
        name = " ".join(str(data.get("name") or "").split())
        if not name:
            raise InputError("Il nome della ricerca è obbligatorio")
        if len(name) > 100:
            raise InputError("Nome troppo lungo (max 100 caratteri)")
        q = self.resolve_query(data)
        if q["min_price"] is not None and q["max_price"] is not None and q["min_price"] > q["max_price"]:
            raise InputError("Il prezzo minimo è maggiore del massimo")
        interval = _opt_int(data.get("interval_sec"), "Intervallo", MIN_INTERVAL)
        active_from = _opt_hour(data.get("active_from"), "Attiva dalle")
        active_to = _opt_hour(data.get("active_to"), "Attiva fino alle")
        if (active_from is None) != (active_to is None):
            raise InputError("Fascia oraria: indica sia l'inizio sia la fine (o nessuno dei due)")
        search = replace(
            base or Search(id=None, name=name, url=q["url"]),
            name=name, url=q["url"], params=q["params"], min_price=q["min_price"], max_price=q["max_price"],
            exclude_words=parse_words(data.get("exclude_words")),
            enabled=bool(data.get("enabled", True)),
            interval_sec=interval, active_from=active_from, active_to=active_to,
            notify_new=bool(data.get("notify_new", True)),
            notify_price_drop=bool(data.get("notify_price_drop", False)),
            notify_max_price=_opt_int(data.get("notify_max_price"), "Soglia notifica"),
        )
        return search, q["warnings"]

    # ------------------------------------------------------------------ CRUD
    def create(self, data: dict[str, Any], run: bool = True) -> dict[str, Any]:
        search, warnings = self.search_from_input(data)
        try:
            saved = self.repo.create_search(search)
        except Conflict as e:
            raise InputError(str(e)) from e
        self.events.info(f"Ricerca '{saved.name}' creata", kind="search", search_id=saved.id)
        result = self._initial_run(saved.id) if run else None
        return {"search": self.repo.get_search(saved.id), "warnings": warnings, "run": result}

    def update(self, search_id: int, data: dict[str, Any]) -> dict[str, Any]:
        current = self.repo.get_search(search_id)
        search, warnings = self.search_from_input(data, base=current)
        reset = search.url != current.url
        try:
            saved = self.repo.update_search(search_id, search, reset_results=reset)
        except Conflict as e:
            raise InputError(str(e)) from e
        self.events.info(f"Ricerca '{saved.name}' modificata" + (" (query cambiata: risultati azzerati)"
                                                                 if reset else ""),
                         kind="search", search_id=saved.id)
        result = self._initial_run(saved.id) if reset else None
        return {"search": self.repo.get_search(saved.id), "warnings": warnings, "run": result, "reset": reset}

    def _initial_run(self, search_id: int) -> dict[str, Any]:
        """Come --add: primo giro senza notifiche, risultati già "visti"."""
        result = self.engine.run_search(search_id, notify=False)
        self.repo.mark_seen(search_id)
        return result.to_dict()

    def duplicate(self, search_id: int) -> Search:
        src = self.repo.get_search(search_id)
        name = self._free_name(f"{src.name} (copia)")
        copy = replace(src, id=None, name=name, created_at=None, seen_at=None, enabled=False)
        saved = self.repo.create_search(copy)
        self.events.info(f"Ricerca '{src.name}' duplicata come '{name}' (disattivata)", kind="search",
                         search_id=saved.id)
        return saved

    def set_enabled(self, search_id: int, enabled: bool) -> Search:
        s = self.repo.get_search(search_id)
        self.repo.set_enabled(search_id, enabled)
        self.events.info(f"Ricerca '{s.name}' {'attivata' if enabled else 'disattivata'}", kind="search",
                         search_id=search_id)
        return self.repo.get_search(search_id)

    def delete(self, search_id: int) -> None:
        s = self.repo.get_search(search_id)
        self.repo.delete_search(search_id)
        self.events.info(f"Ricerca '{s.name}' eliminata", kind="search")

    def _free_name(self, name: str) -> str:
        candidate, n = name, 2
        while self.repo.find_search(candidate):
            candidate, n = f"{name} {n}", n + 1
        return candidate

    # ------------------------------------------------------------------ export / import
    EXPORT_FIELDS = ("name", "url", "params", "min_price", "max_price", "exclude_words", "enabled",
                     "interval_sec", "active_from", "active_to", "notify_new", "notify_price_drop",
                     "notify_max_price")

    def export(self) -> dict[str, Any]:
        return {
            "app": "subito-searcher", "version": EXPORT_VERSION, "exported_at": now_iso(),
            "searches": [{k: getattr(s, k) for k in self.EXPORT_FIELDS} for s in self.repo.list_searches()],
        }

    def import_(self, data: Any) -> dict[str, Any]:
        items = data.get("searches") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise InputError("Formato non valido: atteso {\"searches\": [...]} esportato dall'app")
        created, errors = [], []
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict):
                errors.append(f"#{i}: elemento non valido")
                continue
            payload = dict(item)
            payload["mode"] = "params" if item.get("params") else "url"
            payload["name"] = self._free_name(" ".join(str(item.get("name") or f"Importata {i}").split()))
            try:
                search, _ = self.search_from_input(payload)
                saved = self.repo.create_search(search)
                self.repo.mark_seen(saved.id)
                created.append(saved.name)
            except (InputError, Conflict) as e:
                errors.append(f"#{i} {item.get('name', '')}: {e}")
        self.events.info(f"Import ricerche: {len(created)} create, {len(errors)} scartate", kind="search")
        return {"created": created, "errors": errors}

    # ------------------------------------------------------------------ anteprima
    def preview(self, data: dict[str, Any], limit: int = MAX_RESULTS) -> dict[str, Any]:
        """Esegue la query senza salvarla. Gli errori di rete diventano ScrapeError (gestiti dall'API)."""
        q = self.resolve_query(data)
        probe = Search(id=None, name="anteprima", url=q["url"], min_price=q["min_price"],
                       max_price=q["max_price"], exclude_words=parse_words(data.get("exclude_words")))
        ads, matched = self.engine.preview(q["url"], probe)
        prices = sorted(a.price for a in matched if a.price is not None)
        return {
            "url": q["url"], "warnings": q["warnings"], "found": len(ads), "matched": len(matched),
            "excluded": len(ads) - len(matched),
            "price_min": prices[0] if prices else None, "price_max": prices[-1] if prices else None,
            "items": [{"title": a.title, "price": a.price, "location": a.location, "link": a.link,
                       "shipping": a.shipping, "image": a.image, "published_at": a.published_at}
                      for a in matched[:limit]],
        }


class BackupService:
    _NAME = re.compile(r"^subito-\d{8}-\d{6}(-\d+)?\.db$")

    def __init__(self, db, folder: Path, events):
        self.db = db
        self.folder = folder
        self.events = events

    def create(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        base = f"subito-{datetime.now():%Y%m%d-%H%M%S}"
        path, n = self.folder / f"{base}.db", 2
        while path.exists():  # due backup nello stesso secondo (es. copia di sicurezza prima di un ripristino)
            path, n = self.folder / f"{base}-{n}.db", n + 1
        self.db.backup_to(path)
        self.events.info(f"Backup creato: {path.name}", kind="system")
        return path

    def list(self) -> list[dict[str, Any]]:
        if not self.folder.is_dir():
            return []
        out = []
        for p in sorted(self.folder.glob("subito-*.db"), reverse=True):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size,
                        "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
        return out

    def path_of(self, name: str) -> Path:
        if not self._NAME.match(name):
            raise InputError("Nome di backup non valido")
        path = self.folder / name
        if not path.is_file():
            raise InputError("Backup non trovato")
        return path

    def restore(self, source: Path) -> None:
        """Prima di ripristinare salva lo stato attuale, così l'operazione è reversibile."""
        try:
            self.db.check_backup(source)
        except ValueError as e:
            raise InputError(str(e)) from e
        safety = self.create()
        self.db.restore_from(source)
        self.events.warning(f"Database ripristinato da backup (stato precedente salvato in {safety.name})",
                            kind="system")

    def delete(self, name: str) -> None:
        self.path_of(name).unlink()

    def save_upload(self, data: bytes) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"upload-{datetime.now():%Y%m%d-%H%M%S}.tmp"
        path.write_bytes(data)
        return path
