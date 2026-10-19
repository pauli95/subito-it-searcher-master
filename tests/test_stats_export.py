"""Fase 5: statistiche di prezzo, esportazione CSV, avvisi per il browser, avvio con Windows."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from core import App, Autostart, Paths
from core.autostart import FILE_NAME, script_text
from core.exporting import ads_to_csv, iter_ads
from core.repo import price_summary
from tests.helpers import FakeFetch, make_ad
from tests.test_api import client, core, create  # noqa: F401  (fixture condivise)


# ------------------------------------------------------------------ statistiche

def test_price_summary():
    assert price_summary([]) == {"min": None, "max": None, "mean": None, "median": None, "p25": None, "p75": None}
    assert price_summary([10, 20, 90]) == {"min": 10, "max": 90, "mean": 40.0, "median": 20, "p25": 15.0, "p75": 55.0}
    assert price_summary([10, 20, 30, 40, 50]) | {} == {"min": 10, "max": 50, "mean": 30.0, "median": 30,
                                                     "p25": 20.0, "p75": 40.0}
    assert price_summary([10, 20, 30, 41])["median"] == 25
    assert price_summary([7])["median"] == 7


def test_stats_endpoint_excludes_sold_unknown_and_zero_prices(client, core):  # noqa: F811
    sid = create(client)["search"]["id"]
    core.engine._fetch.default = [make_ad("1", 80), make_ad("2", 300, sold=True), make_ad("4", 50),
                                  make_ad("5", None), make_ad("6", 0)]
    client.post(f"/api/searches/{sid}/run")
    st = client.get("/api/ads/stats").json()
    # attivi: 1 (80), 4 (50), 5 (n.d.), 6 (0 = da concordare); venduto 2 escluso
    published = st.pop("published")
    assert st == {"count": 4, "priced": 2, "shipping": 4, "min": 50, "max": 80, "mean": 65.0, "median": 65.0,
                  "p25": 57.5, "p75": 72.5}
    assert published["last7"] == 0 and published["avg_day"] is None    # make_ad: nessuna data di pubblicazione
    assert client.get("/api/ads/stats", params={"status": "sold"}).json()["median"] == 300
    assert client.get("/api/ads/stats", params={"q": "Annuncio 4"}).json()["priced"] == 1
    assert client.get("/api/ads/stats", params={"search_id": 999}).json()["count"] == 0
    # un annuncio nascosto esce anche dalle statistiche
    ad1 = next(a for a in client.get("/api/ads").json()["items"] if a["ad_key"] == "1")
    client.patch(f"/api/ads/{ad1['id']}", json={"hidden": True})
    assert client.get("/api/ads/stats").json()["max"] == 50


# ------------------------------------------------------------------ CSV

def read_csv(text: str) -> list[dict[str, str]]:
    assert text.startswith("\ufeff")
    return list(csv.DictReader(io.StringIO(text[1:]), delimiter=";"))


def test_csv_format_and_formula_injection():
    item = {"id": 1, "title": "=HYPERLINK(\"http://x\")", "price": 120, "shipping": True, "company": None,
            "searches": [{"id": 1, "name": "TV"}, {"id": 2, "name": "Monitor"}],
            "first_seen_at": "2026-10-19T10:00:00.123", "link": "https://www.subito.it/a.htm"}
    rows = read_csv(ads_to_csv([item]))
    assert rows[0]["titolo"].startswith("'=")
    assert rows[0]["prezzo"] == "120" and rows[0]["spedizione"] == "sì" and rows[0]["azienda"] == ""
    assert rows[0]["ricerche"] == "TV, Monitor"
    assert rows[0]["trovato_il"] == "2026-10-19 10:00:00.123"


def test_csv_endpoint_respects_filters(client, core):  # noqa: F811
    sid = create(client)["search"]["id"]
    core.engine._fetch.default = [make_ad("1", 80), make_ad("4", 50, title="Annuncio; con \"virgolette\"")]
    client.post(f"/api/searches/{sid}/run")
    r = client.get("/api/ads/export.csv", params={"sort": "price_asc"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="annunci-subito-')
    rows = read_csv(r.content.decode("utf-8"))
    assert [row["prezzo"] for row in rows] == ["50", "80", "300"]
    assert rows[0]["titolo"] == 'Annuncio; con "virgolette"'      # separatore e virgolette nel testo
    assert len(read_csv(client.get("/api/ads/export.csv", params={"max_price": 60}).content.decode())) == 1


def test_iter_ads_pages_through_everything(tmp_path: Path):
    app = App(Paths(legacy=tmp_path, data=tmp_path / "data"), file_logging=False, throttle=False)
    try:
        from core import Search
        s = app.repo.create_search(Search(id=None, name="x", url="https://www.subito.it/annunci-italia/vendita/usato/"))
        app.repo.record_results(s.id, [make_ad(str(i), i) for i in range(1, 8)])
        assert len(list(iter_ads(app.repo, page=3))) == 7
        assert [a["price"] for a in iter_ads(app.repo, page=2, sort="price_desc")][:2] == [7, 6]
    finally:
        app.close()


# ------------------------------------------------------------------ avvisi browser / suono

@pytest.fixture
def app(tmp_path: Path):
    a = App(Paths(legacy=tmp_path, data=tmp_path / "data"), file_logging=False, throttle=False)
    a.engine._fetch = FakeFetch()
    a.settings.update("notifications", {"windows": False, "telegram": False, "ntfy": False})
    yield a
    a.close()


def alerts(app: App) -> list[dict]:
    return [e for e in app.events.since(0) if e.get("alert")]


def test_browser_alert_event(app: App):
    app.notifier.notify("TV", 1, [make_ad("1", 100)], [])
    assert alerts(app) == []                                   # browser e suono spenti di default
    app.settings.update("notifications", {"browser": True})
    app.notifier.notify("TV", 1, [make_ad("1", 100, title="Sony")], [])
    a = alerts(app)[-1]["alert"]
    assert a["title"] == "TV: 1 nuovi annunci" and a["body"] == "Sony — € 100"
    assert a["link"].endswith("a-1.htm") and a["browser"] and not a["sound"]
    app.settings.update("notifications", {"browser": False, "sound": True})
    app.notifier.notify("TV", 1, [make_ad("2", 5), make_ad("3", 6)], [(make_ad("4", 7), 9)])
    a = alerts(app)[-1]["alert"]
    assert a["title"] == "TV: 2 nuovi annunci, 1 ribassi di prezzo" and a["link"] is None and a["sound"]
    assert a["body"].count("•") == 3


def test_browser_alert_respects_dnd(app: App):
    app.settings.update("notifications", {"browser": True, "sound": True, "dnd": True})
    app.notifier.notify("TV", 1, [make_ad("1", 100)], [])
    assert alerts(app) == []


def test_browser_alert_only_for_notified_ads(app: App):
    """Le regole della ricerca (soglia di prezzo) valgono anche per browser e suono."""
    from core import Search
    app.settings.update("notifications", {"browser": True})
    s = app.repo.create_search(Search(id=None, name="TV", url="https://www.subito.it/annunci-italia/vendita/usato/",
                                      notify_max_price=50))
    app.engine._fetch.default = [make_ad("1", 100)]
    app.engine.run_search(s.id, notify=True)
    assert alerts(app) == []
    app.engine._fetch.default = [make_ad("1", 100), make_ad("2", 40)]
    app.engine.run_search(s.id, notify=True)
    assert alerts(app)[-1]["alert"]["body"] == "Annuncio 2 — € 40"


# ------------------------------------------------------------------ avvio con Windows

def test_autostart_script(tmp_path: Path):
    text = script_text(Path(r"C:\App\.venv\Scripts\python.exe"), Path(r"C:\Mio posto\server.py"))
    # stringa VBScript: virgolette interne raddoppiate; 0 = finestra nascosta, False = non attendere
    assert 'shell.Run """C:\\App\\.venv\\Scripts\\python.exe"" ""C:\\Mio posto\\server.py""", 0, False' in text
    assert 'shell.CurrentDirectory = "C:\\Mio posto"' in text
    assert text.endswith("\r\n")


def test_autostart_enable_disable(tmp_path: Path):
    auto = Autostart(folder=tmp_path, python=tmp_path / "python.exe", server=tmp_path / "server.py")
    assert auto.status() == {"supported": True, "enabled": False, "path": str(tmp_path / FILE_NAME)}
    auto.enable()
    assert auto.status()["enabled"] and "server.py" in (tmp_path / FILE_NAME).read_text(encoding="utf-8")
    auto.disable()
    auto.disable()                                             # idempotente
    assert not auto.status()["enabled"]


def test_autostart_api(client, core, tmp_path: Path):  # noqa: F811
    core.autostart = Autostart(folder=tmp_path / "startup", python=tmp_path / "python.exe", server=tmp_path / "s.py")
    r = client.put("/api/system/autostart", json={"enabled": True})
    assert r.status_code == 400 and "non trovata" in r.json()["detail"]
    (tmp_path / "startup").mkdir()
    assert client.put("/api/system/autostart", json={"enabled": True}).json()["enabled"] is True
    assert client.get("/api/system/autostart").json()["enabled"] is True
    assert client.put("/api/system/autostart", json={"enabled": False}).json()["enabled"] is False


def test_browser_and_sound_test_messages(client, core):  # noqa: F811
    for channel in ("browser", "sound"):
        assert client.post(f"/api/notifications/test/{channel}").status_code == 200
    got = [e["alert"] for e in core.events.since(0) if e.get("alert")]
    assert [(a["browser"], a["sound"]) for a in got] == [(True, False), (False, True)]


def test_shutdown_endpoint(client):  # noqa: F811
    assert client.post("/api/system/shutdown").status_code == 400      # senza server.py: non disponibile
    calls = []
    client.app.state.shutdown = lambda: calls.append(1)
    assert client.post("/api/system/shutdown").json() == {"ok": True}
    assert client.post("/api/system/shutdown", headers={"Origin": "https://evil.example"}).status_code == 403


def test_publish_rate(tmp_path: Path):
    """Media giornaliera calcolata sul periodo effettivamente coperto dagli annunci raccolti."""
    from datetime import datetime, timedelta

    from core import Search
    app = App(Paths(legacy=tmp_path, data=tmp_path / "data"), file_logging=False, throttle=False)
    try:
        now = datetime(2026, 10, 19, 12, 0, 0)
        s = app.repo.create_search(Search(id=None, name="x", url="https://www.subito.it/annunci-italia/vendita/usato/"))

        def ad(key: str, hours_ago: float, **kw):
            stamp = (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
            a = make_ad(key, 100, **kw)
            a.published_at = stamp
            return a

        # ricerca "veloce": 12 annunci nelle ultime 5,5 ore -> 12 / (5,5/24) = 52,4 al giorno, non 12/7
        app.repo.record_results(s.id, [ad(str(i), i * 0.5) for i in range(12)])
        p = app.repo.publish_stats(now=now)
        assert p["last7"] == 12 and p["today"] == 12
        assert p["avg_day"] == 52.4 and p["span_days"] == 0.23
        # annunci sparsi su 10 giorni: la finestra di 7 giorni è coperta tutta
        app.repo.record_results(s.id, [ad(f"old{d}", d * 24) for d in range(1, 11)])
        p = app.repo.publish_stats(now=now)
        assert p["last7"] == 12 + 7 and p["avg_day"] == round(19 / 7, 1)   # il 7° giorno è incluso
        assert len(p["per_day"]) == 14 and p["per_day"][-1] == {"day": "2026-10-19", "count": 12}
        assert p["last30"] == 22
    finally:
        app.close()
