"""Import automatico (una sola volta) dei file della versione precedente.

File letti (mai modificati né cancellati: restano come backup):
- searches.tracked          {nome: {url: {minPrice: {maxPrice: {link: {title, price, location, ...}}}}}}
                            con minPrice/maxPrice = "null" oppure numeri come stringa
- telegram_api_credentials  {"token": ..., "chatid": ...}
- ntfy_config               {"ntfy_server": ..., "ntfy_topic": ...}
- settings.json / app_state.json  (versione web precedente, se presenti)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import Paths, Settings
from .models import now_iso
from .repo import Repository
from .scraper import ad_key_from

IMPORT_FLAG = "legacy_import"
URL_ONLY_FLAG = "url_only_searches"
_LOCATION = re.compile(r"^(?P<town>.*?)\s*\((?P<prov>[A-Z]{2})\)\s*$")


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    # La versione originale scriveva con la codifica di default (cp1252 su Windows) ma
    # json.dumps produce solo ASCII, quindi utf-8 va bene; errors="replace" per sicurezza.
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return json.loads(text) if text else None


def _price(value: Any) -> int | None:
    if value in (None, "", "null", "Unknown price"):
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except ValueError:
        return None


def _hhmm(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    h, _, m = text.partition(":")
    try:
        return f"{int(h):02d}:{int(m or 0):02d}"
    except ValueError:
        return None


def _unique_name(c, name: str) -> str:
    candidate, n = name, 2
    while c.execute("SELECT 1 FROM searches WHERE name = ?", (candidate,)).fetchone():
        candidate, n = f"{name} ({n})", n + 1
    return candidate


def import_legacy(paths: Paths, repo: Repository, settings: Settings, events=None, force: bool = False
                  ) -> dict[str, Any] | None:
    """Importa i vecchi file se non è già stato fatto. Restituisce un riepilogo o None."""
    if repo.get_setting(IMPORT_FLAG) and not force:
        return None

    report: dict[str, Any] = {"at": now_iso(), "searches": 0, "ads": 0, "files": [], "errors": []}
    stamp = report["at"]

    def load(path: Path) -> Any:
        try:
            data = _read_json(path)
        except (OSError, ValueError) as e:
            report["errors"].append(f"{path.name}: {e}")
            return None
        if data is not None:
            report["files"].append(path.name)
        return data

    searches = load(paths.legacy_searches) or {}
    telegram = load(paths.legacy_telegram) or {}
    ntfy = load(paths.legacy_ntfy) or {}
    old_settings = load(paths.legacy_settings) or {}
    old_state = (load(paths.legacy_state) or {}).get("searches", {})

    with repo.db.transaction() as c:
        for name, by_url in (searches.items() if isinstance(searches, dict) else []):
            for url, by_min in (by_url or {}).items():
                for min_p, by_max in (by_min or {}).items():
                    for max_p, results in (by_max or {}).items():
                        meta = old_state.get(name, {})
                        final_name = _unique_name(c, str(name).strip() or "Ricerca")
                        cur = c.execute(
                            """INSERT INTO searches (name, url, min_price, max_price, created_at, updated_at,
                                   seen_at, last_run_at, last_error)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (final_name, url, _price(min_p), _price(max_p), meta.get("created_at") or stamp,
                             stamp, stamp, meta.get("last_run"), meta.get("last_error")))
                        search_id = cur.lastrowid
                        report["searches"] += 1
                        for link, rec in (results or {}).items():
                            report["ads"] += _import_ad(c, search_id, link, rec or {}, stamp)

    tg_values = {k: str(telegram[k]) for k in ("token", "chatid") if telegram.get(k)}
    if tg_values:
        settings.update("telegram", tg_values)
    ntfy_values = {new: str(ntfy[old]) for old, new in (("ntfy_server", "server"), ("ntfy_topic", "topic"))
                   if ntfy.get(old)}
    if ntfy_values:
        settings.update("ntfy", ntfy_values)

    sched = old_settings.get("scheduler") or {}
    monitor: dict[str, Any] = {}
    if sched.get("delay"):
        monitor["interval_sec"] = int(sched["delay"])
    for old, new in (("active_hour", "active_from"), ("pause_hour", "active_to")):
        if _hhmm(sched.get(old)):
            monitor[new] = _hhmm(sched.get(old))
    if "autostart" in sched:
        monitor["autostart"] = bool(sched["autostart"])
    if monitor:
        settings.update("monitor", monitor)
    toggles = {k: bool(v) for k, v in (old_settings.get("notifications") or {}).items()
               if k in ("windows", "telegram", "ntfy")}
    if toggles:
        settings.update("notifications", toggles)

    repo.set_setting(IMPORT_FLAG, report)
    if events and (report["files"] or report["errors"]):
        msg = (f"Importati dai file precedenti: {report['searches']} ricerche, {report['ads']} annunci"
               f" ({', '.join(report['files']) or 'nessun file'})")
        events.add(msg, "warning" if report["errors"] else "success", kind="system")
        for err in report["errors"]:
            events.error(f"Import: {err}", kind="system")
    return report


def convert_legacy_params(repo: Repository, builder, events=None) -> tuple[int, int]:
    """Ricerche salvate solo come URL -> parametri del form, dove l'URL è riconosciuto.

    L'URL salvato non viene modificato (il comportamento resta identico); i prezzi min/max
    della vecchia versione, che erano filtri locali, vengono riportati nei parametri.
    Restituisce (convertite, non convertibili). Le non convertibili restano "solo URL".
    """
    from dataclasses import replace

    from .urlbuilder import UrlError

    converted = failed = 0
    skipped = set(repo.get_setting(URL_ONLY_FLAG, []))  # già tentate: niente avvisi ripetuti
    for search in repo.list_searches():
        if search.params is not None or search.id in skipped:
            continue
        try:
            params = builder.parse(search.url).params
        except UrlError as e:
            failed += 1
            skipped.add(search.id)
            repo.set_setting(URL_ONLY_FLAG, sorted(skipped))
            if events:
                events.warning(f"'{search.name}': URL non convertibile in parametri ({e}); "
                               "la ricerca funziona ma si modifica solo come URL", kind="system",
                               search_id=search.id)
            continue
        if params.min_price is None:
            params.min_price = search.min_price
        if params.max_price is None:
            params.max_price = search.max_price
        repo.update_search(search.id, replace(search, params=params.to_dict(),
                                              min_price=params.min_price, max_price=params.max_price))
        converted += 1
    if converted and events:
        events.info(f"Convertite in parametri {converted} ricerche salvate come URL", kind="system")
    return converted, failed


def _import_ad(c, search_id: int, link: str, rec: dict[str, Any], stamp: str) -> int:
    key = ad_key_from(None, link) or link
    found = rec.get("found_at") or stamp
    location = rec.get("location")
    town = province = None
    if isinstance(location, str):
        m = _LOCATION.match(location)
        if m:
            town, province = m.group("town") or None, m.group("prov")
    shipping = rec.get("shipping")
    row = c.execute("SELECT id FROM ads WHERE ad_key = ?", (key,)).fetchone()
    created = 0
    if row:
        ad_id = row["id"]
    else:
        price = _price(rec.get("price"))
        ad_id = c.execute(
            """INSERT INTO ads (ad_key, link, title, price, location, town, province, shipping,
                   published_at, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, link, rec.get("title") or "Senza titolo", price, location, town, province,
             None if shipping is None else int(bool(shipping)), rec.get("published"), found, found)).lastrowid
        c.execute("INSERT INTO price_history (ad_id, price, seen_at) VALUES (?, ?, ?)", (ad_id, price, found))
        created = 1
    c.execute("INSERT OR IGNORE INTO search_ads (search_id, ad_id, found_at) VALUES (?, ?, ?)",
              (search_id, ad_id, found))
    return created
