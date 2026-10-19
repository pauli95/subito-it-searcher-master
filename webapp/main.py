"""Backend FastAPI: API REST + Server-Sent Events sopra il modulo core.

Documentazione interattiva delle API: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core import App, AutostartError, InputError, NotFound, ScrapeError, Search, UrlError
from core.config import SettingsError, clean_settings
from core.exporting import ads_to_csv, iter_ads
from core.models import RunResult
from core.notifier import NotifyError
from core.urlbuilder import SearchParams

from .security import COOKIE, AuthConfig, LoginLimiter, SecurityMiddleware, login_page

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_UPLOAD = 200 * 1024 * 1024
VERSION = "2.0.0"


# =============================================================================== modelli input

AdStatus = Literal["new", "drop", "sold", "favorite", "hidden", "active"]
AdSort = Literal["found_desc", "found_asc", "price_asc", "price_desc", "published_desc"]


class SearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mode: Literal["params", "url"] = "params"
    params: dict[str, Any] | None = None
    url: str | None = None
    min_price: int | None = None        # solo in modalità URL (in modalità parametri stanno in params)
    max_price: int | None = None
    exclude_words: list[str] | str | None = None
    enabled: bool = True
    interval_sec: int | None = None
    active_from: str | None = None
    active_to: str | None = None
    notify_new: bool = True
    notify_price_drop: bool = False
    notify_max_price: int | None = None


class PreviewIn(BaseModel):
    mode: Literal["params", "url"] = "params"
    params: dict[str, Any] | None = None
    url: str | None = None
    min_price: int | None = None
    max_price: int | None = None
    exclude_words: list[str] | str | None = None


class UrlIn(BaseModel):
    url: str


class ToggleIn(BaseModel):
    enabled: bool


class AutostartIn(BaseModel):
    enabled: bool


class AdFlagsIn(BaseModel):
    favorite: bool | None = None
    hidden: bool | None = None


# =============================================================================== app factory

def create_app(core: App | None = None, trusted_hosts: set[str] | None = None) -> FastAPI:
    core = core or App()
    auth = AuthConfig(core.settings, core.repo)
    limiter = LoginLimiter()
    run_all_task: dict[str, asyncio.Task | None] = {"task": None}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        core.events.info(f"Server avviato (versione {VERSION})", kind="system")
        if core.settings.get("monitor").get("autostart"):
            await core.monitor.start()
        yield
        if core.monitor.running:
            await core.monitor.stop()

    app = FastAPI(title="Subito Searcher", version=VERSION, lifespan=lifespan,
                  description="API locali di Subito Searcher. Tutte le risposte sono in JSON.")
    app.add_middleware(SecurityMiddleware, auth=auth, trusted_hosts=trusted_hosts)
    app.state.core = core

    # ------------------------------------------------------------------ errori comuni
    @app.exception_handler(InputError)
    @app.exception_handler(AutostartError)
    @app.exception_handler(SettingsError)
    @app.exception_handler(UrlError)
    async def _bad_request(_req: Request, exc: Exception):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(NotFound)
    async def _not_found(_req: Request, exc: Exception):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ScrapeError)
    async def _scrape(_req: Request, exc: ScrapeError):
        return JSONResponse({"detail": str(exc), "kind": exc.kind}, status_code=502)

    # ------------------------------------------------------------------ helper
    def search_view(s: Search, stats: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
        data = s.to_dict()
        data["stats"] = (stats or core.repo.search_stats()).get(s.id, {"total": 0, "new": 0, "active": 0})
        data["next_due"] = core.monitor.next_due_iso(s.id)
        data["summary"] = describe(s)
        return data

    def describe(s: Search) -> dict[str, Any]:
        """Etichette leggibili: località, categoria, tipo, URL ricostruito dai parametri."""
        if not s.params:
            return {"mode": "url", "location": None, "category": None, "ad_type": None}
        try:
            p = SearchParams.from_dict(s.params)
            loc = core.urls.geo.resolve(p.region, p.province, p.town)
            cat = core.urls.catalog.category(p.category)
            ad_type = core.urls.catalog.ad_types.get(p.ad_type)
            return {"mode": "params", "location": loc.label, "category": cat.label if cat else p.category,
                    "ad_type": ad_type.label if ad_type else p.ad_type, "keywords": p.keywords}
        except (ValueError, TypeError):
            return {"mode": "params", "location": None, "category": None, "ad_type": None}

    async def run_now(search_id: int) -> dict[str, Any]:
        core.repo.get_search(search_id)
        result: RunResult = await asyncio.to_thread(core.engine.run_search, search_id, True)
        core.monitor.note_run(result)
        return result.to_dict()

    # ================================================================== meta / supporto form
    @app.get("/api/meta", tags=["supporto"])
    def meta():
        return {"version": VERSION, "catalog": core.urls.catalog.to_dict(),
                "geo_generated": core.urls.geo.generated, "defaults": SearchParams().to_dict(),
                "min_interval": 60}

    @app.get("/api/geo", tags=["supporto"])
    def geo_search(q: str = Query(..., min_length=1, max_length=60), limit: int = Query(12, ge=1, le=50)):
        return [loc.to_dict() for loc in core.urls.geo.search(q, limit)]

    @app.post("/api/url/build", tags=["supporto"])
    def url_build(params: dict[str, Any]):
        try:
            built = core.urls.build(SearchParams.from_dict(params))
        except (ValueError, TypeError) as e:
            raise InputError(str(e)) from e
        return {"url": built.url, "warnings": built.warnings, "location": built.location.to_dict(),
                "price_on_site": built.price_on_site}

    @app.post("/api/url/parse", tags=["supporto"])
    def url_parse(data: UrlIn):
        parsed = core.urls.parse(data.url)
        return {"params": parsed.params.to_dict(), "warnings": parsed.warnings}

    @app.post("/api/preview", tags=["supporto"])
    async def preview(data: PreviewIn):
        return await asyncio.to_thread(core.searches.preview, data.model_dump())

    # ================================================================== ricerche
    @app.get("/api/searches", tags=["ricerche"])
    def list_searches():
        stats = core.repo.search_stats()
        return [search_view(s, stats) for s in core.repo.list_searches()]

    @app.post("/api/searches", status_code=201, tags=["ricerche"])
    async def create_search(data: SearchIn, run: bool = True):
        out = await asyncio.to_thread(core.searches.create, data.model_dump(), run)
        if out["run"]:
            core.monitor.note_run(_result_stub(out["search"].id, out["search"].name, out["run"]))
        core.monitor.wake()
        return {**out, "search": search_view(out["search"])}

    @app.get("/api/searches/export", tags=["ricerche"])
    def export_searches():
        body = json.dumps(core.searches.export(), ensure_ascii=False, indent=2)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="ricerche-subito.json"'})

    @app.post("/api/searches/import", tags=["ricerche"])
    def import_searches(data: dict[str, Any] | list[Any]):
        out = core.searches.import_(data)
        core.monitor.wake()
        return out

    @app.get("/api/searches/{search_id}", tags=["ricerche"])
    def get_search(search_id: int):
        return search_view(core.repo.get_search(search_id))

    @app.put("/api/searches/{search_id}", tags=["ricerche"])
    async def update_search(search_id: int, data: SearchIn):
        out = await asyncio.to_thread(core.searches.update, search_id, data.model_dump())
        if out["reset"]:
            core.monitor.next_due.pop(search_id, None)
        core.monitor.wake()
        return {**out, "search": search_view(out["search"])}

    @app.delete("/api/searches/{search_id}", tags=["ricerche"])
    def delete_search(search_id: int):
        core.searches.delete(search_id)
        core.monitor.next_due.pop(search_id, None)
        return {"ok": True}

    @app.post("/api/searches/{search_id}/duplicate", status_code=201, tags=["ricerche"])
    def duplicate_search(search_id: int):
        return search_view(core.searches.duplicate(search_id))

    @app.post("/api/searches/{search_id}/enabled", tags=["ricerche"])
    def toggle_search(search_id: int, data: ToggleIn):
        s = core.searches.set_enabled(search_id, data.enabled)
        core.monitor.wake()
        return search_view(s)

    @app.post("/api/searches/{search_id}/run", tags=["ricerche"])
    async def run_search(search_id: int):
        return await run_now(search_id)

    @app.post("/api/searches/{search_id}/seen", tags=["ricerche"])
    def seen_search(search_id: int):
        core.repo.get_search(search_id)
        core.repo.mark_seen(search_id)
        return {"ok": True}

    @app.post("/api/seen", tags=["ricerche"])
    def seen_all():
        core.repo.mark_seen(None)
        return {"ok": True}

    @app.post("/api/run-all", status_code=202, tags=["ricerche"])
    async def run_all():
        """Avvia l'esecuzione di tutte le ricerche attive in background; l'esito arriva negli eventi."""
        task = run_all_task["task"]
        if task and not task.done():
            return {"started": False, "detail": "Esecuzione già in corso"}

        async def worker():
            results = await asyncio.to_thread(core.engine.run_all, True)
            for r in results:
                core.monitor.note_run(r)
            core.monitor.note_cycle()   # modalità sincronizzata: il conto alla rovescia riparte da qui
            new = sum(len(r.new) for r in results)
            errors = sum(not r.ok for r in results)
            core.events.add(f"Esecuzione manuale completata: {len(results)} ricerche, {new} nuovi annunci"
                            + (f", {errors} errori" if errors else ""),
                            "warning" if errors else "success", kind="scheduler")

        run_all_task["task"] = asyncio.create_task(worker())
        return {"started": True}

    # ================================================================== annunci
    def ad_filters(search_id: int | None = None, q: str | None = Query(None, max_length=100),
                   min_price: int | None = None, max_price: int | None = None, shipping: bool | None = None,
                   status: AdStatus | None = None) -> dict[str, Any]:
        return {"search_id": search_id, "text": q, "min_price": min_price, "max_price": max_price,
                "shipping": shipping, "status": status}

    @app.get("/api/ads", tags=["annunci"])
    def list_ads(filters: dict[str, Any] = Depends(ad_filters), sort: AdSort = "published_desc",
                 limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        items, total = core.repo.query_ads(**filters, sort=sort, limit=limit, offset=offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @app.get("/api/ads/stats", tags=["annunci"])
    def ads_stats(filters: dict[str, Any] = Depends(ad_filters)):
        """Numero, prezzo minimo, massimo, medio e mediano degli annunci filtrati (venduti esclusi)."""
        return core.repo.price_stats(**filters)

    @app.get("/api/ads/export.csv", tags=["annunci"])
    def ads_export(filters: dict[str, Any] = Depends(ad_filters), sort: AdSort = "published_desc"):
        """Tutti gli annunci filtrati in CSV (separatore ';', UTF-8 con BOM per Excel)."""
        body = ads_to_csv(iter_ads(core.repo, **filters, sort=sort))
        name = f"annunci-subito-{datetime.now():%Y%m%d-%H%M}.csv"
        return Response(body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/ads/{ad_id}", tags=["annunci"])
    def get_ad(ad_id: int):
        return core.repo.get_ad(ad_id)

    @app.patch("/api/ads/{ad_id}", tags=["annunci"])
    def flag_ad(ad_id: int, data: AdFlagsIn):
        core.repo.get_ad(ad_id)
        core.repo.set_ad_flags(ad_id, favorite=data.favorite, hidden=data.hidden)
        return core.repo.get_ad(ad_id)

    # ================================================================== dashboard / monitor / salute
    @app.get("/api/dashboard", tags=["monitor"])
    def dashboard(days: int = Query(30, ge=1, le=365)):
        latest, _ = core.repo.query_ads(limit=10)
        return {**core.repo.dashboard(days), "latest": latest, "monitor": core.monitor.status(),
                "alerts": core.monitor.health()["alerts"]}

    @app.get("/api/monitor", tags=["monitor"])
    def monitor_status():
        return core.monitor.status()

    @app.post("/api/monitor/start", tags=["monitor"])
    async def monitor_start():
        await core.monitor.start()
        return core.monitor.status()

    @app.post("/api/monitor/stop", tags=["monitor"])
    async def monitor_stop():
        await core.monitor.stop()
        return core.monitor.status()

    @app.get("/api/health", tags=["monitor"])
    def health():
        return core.monitor.health()

    # ================================================================== impostazioni
    def settings_view() -> dict[str, Any]:
        data = core.settings.all()
        token = data["telegram"].pop("token", "")
        data["telegram"]["token_set"] = bool(token)
        data["telegram"]["token_hint"] = f"…{token[-4:]}" if len(token) > 8 else ""
        data["server"]["pin_set"] = bool(data["server"].pop("pin", ""))
        data["channels"] = core.notifier.channels_status()
        return data

    @app.get("/api/settings", tags=["impostazioni"])
    def get_settings():
        return settings_view()

    @app.put("/api/settings/{section}", tags=["impostazioni"])
    def put_settings(section: str, values: dict[str, Any]):
        cleaned = clean_settings(section, values, core.settings.get(section))
        if cleaned:
            core.settings.update(section, cleaned)
        if section == "monitor":
            core.monitor.wake()
        what = ", ".join(k for k in cleaned if k != "token") + (" token" if "token" in cleaned else "")
        core.events.info(f"Impostazioni '{section}' salvate ({what or 'nessuna modifica'})", kind="config")
        view = settings_view()
        if section == "server":
            view["restart_required"] = True
        return view

    @app.post("/api/notifications/test/{channel}", tags=["impostazioni"])
    async def test_notification(channel: Literal["windows", "telegram", "ntfy", "browser", "sound"]):
        try:
            await asyncio.to_thread(core.notifier.test, channel)
        except NotifyError as e:
            core.events.error(f"Test {channel} fallito: {e}", kind="notify")
            raise InputError(str(e)) from e
        core.events.success(f"Messaggio di prova {channel} inviato", kind="notify")
        return {"ok": True}

    @app.get("/api/system/autostart", tags=["impostazioni"])
    def autostart_status():
        return core.autostart.status()

    @app.put("/api/system/autostart", tags=["impostazioni"])
    def autostart_set(data: AutostartIn):
        if data.enabled:
            core.autostart.enable()
        else:
            core.autostart.disable()
        core.events.info("Avvio con Windows " + ("attivato" if data.enabled else "disattivato"), kind="config")
        return core.autostart.status()

    @app.post("/api/system/shutdown", tags=["impostazioni"])
    async def shutdown(request: Request):
        """Arresta il server (utile quando gira in background senza finestra)."""
        stop = getattr(request.app.state, "shutdown", None)
        if stop is None:
            raise InputError("Arresto dall'interfaccia non disponibile: chiudi la finestra del server")
        core.events.info("Arresto del server richiesto dall'interfaccia", kind="system")
        asyncio.get_running_loop().call_later(0.5, stop)  # prima la risposta, poi l'arresto
        return {"ok": True}

    # ================================================================== manutenzione
    @app.get("/api/backups", tags=["manutenzione"])
    def list_backups():
        return core.backups.list()

    @app.post("/api/backups", status_code=201, tags=["manutenzione"])
    async def create_backup():
        path = await asyncio.to_thread(core.backups.create)
        return {"name": path.name}

    @app.get("/api/backups/{name}", tags=["manutenzione"])
    def download_backup(name: str):
        return FileResponse(core.backups.path_of(name), filename=name, media_type="application/octet-stream")

    @app.delete("/api/backups/{name}", tags=["manutenzione"])
    def delete_backup(name: str):
        core.backups.delete(name)
        return {"ok": True}

    @app.post("/api/backups/{name}/restore", tags=["manutenzione"])
    async def restore_backup(name: str):
        await _restore(core.backups.path_of(name))
        return {"ok": True}

    @app.post("/api/backups/upload/restore", tags=["manutenzione"])
    async def restore_upload(request: Request):
        """Corpo della richiesta = file .db (application/octet-stream)."""
        body = await request.body()
        if not body or len(body) > MAX_UPLOAD:
            raise InputError("File vuoto o troppo grande")
        path = core.backups.save_upload(body)
        try:
            await _restore(path)
        finally:
            path.unlink(missing_ok=True)
        return {"ok": True}

    async def _restore(path: Path) -> None:
        was_running = core.monitor.running
        if was_running:
            await core.monitor.stop()
        try:
            await asyncio.to_thread(core.backups.restore, path)
        finally:
            if was_running:
                await core.monitor.start()

    @app.post("/api/maintenance/cleanup", tags=["manutenzione"])
    def cleanup(days: int = Query(..., ge=1, le=3650)):
        removed = core.repo.cleanup_ads(days)
        core.events.info(f"Pulizia manuale: eliminati {removed} annunci non visti da più di {days} giorni",
                         kind="system")
        return {"removed": removed}

    # ================================================================== eventi (log)
    @app.get("/api/events", tags=["log"])
    def events(after: int = 0, limit: int = Query(300, ge=1, le=2000)):
        return core.events.since(after, limit)

    @app.get("/api/events/stream", tags=["log"])
    async def events_stream(request: Request, after: int = 0):
        """Server-Sent Events: `message` per ogni evento, `status` con lo stato del monitor ogni 5 s."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

        def listener(event: dict[str, Any]) -> None:  # chiamato anche da thread di lavoro
            loop.call_soon_threadsafe(_put, queue, event)

        last = after or int(request.headers.get("last-event-id") or 0)
        backlog = core.events.since(last) if last else []
        core.events.subscribe(listener)

        async def gen():
            try:
                yield "retry: 3000\n\n"
                for e in backlog:
                    yield _sse(e)
                last_status = 0.0
                while not await request.is_disconnected():
                    try:
                        e = await asyncio.wait_for(queue.get(), timeout=1.0)
                        yield _sse(e)
                    except asyncio.TimeoutError:
                        pass
                    if loop.time() - last_status >= 5:
                        last_status = loop.time()
                        yield f"event: status\ndata: {json.dumps(core.monitor.status())}\n\n"
            finally:
                core.events.unsubscribe(listener)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ================================================================== accesso (rete locale)
    @app.get("/login", include_in_schema=False)
    def login_form():
        return login_page()

    @app.post("/login", include_in_schema=False)
    async def login(request: Request):
        ip = request.client.host if request.client else "?"
        if not limiter.allow(ip):
            return login_page("Troppi tentativi: riprova tra qualche minuto")
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        if not auth.check_pin((form.get("pin") or [""])[0]):
            core.events.warning(f"PIN errato da {ip}", kind="system")
            return login_page("PIN errato")
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, auth.token(), httponly=True, samesite="strict", max_age=30 * 86400)
        return resp

    # ================================================================== frontend
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


def _put(queue: asyncio.Queue, event: dict[str, Any]) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:  # client troppo lento: si perde l'evento, non si blocca il server
        pass


def _sse(event: dict[str, Any]) -> str:
    return f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _result_stub(search_id: int, name: str, data: dict[str, Any]) -> RunResult:
    """RunResult minimale dal dizionario restituito dal servizio (per il monitor)."""
    return RunResult(search_id, name, data["ok"], found=data["found"], error=data["error"],
                     error_kind=data.get("error_kind"), duration=data.get("duration", 0.0))


__all__ = ["create_app"]
