from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core import App, Conflict, Paths, Search
from core.notifier import format_html, send_telegram
from core.scraper import ScrapeError
from tests.helpers import FakeFetch, make_ad


@pytest.fixture
def app(tmp_path: Path):
    a = App(Paths(legacy=tmp_path, data=tmp_path / "data"), file_logging=False, throttle=False)
    a.engine._fetch = FakeFetch()
    yield a
    a.close()


def add(app: App, name: str, url: str, **kw) -> Search:
    return app.repo.create_search(Search(id=None, name=name, url=url, **kw))


# ------------------------------------------------------------------- import legacy

def test_import_legacy_files(tmp_path: Path):
    legacy = {
        "iphone": {"https://www.subito.it/annunci-veneto/vendita/telefonia/?q=iphone": {"100": {"1400": {
            "https://www.subito.it/telefonia/iphone-11-treviso-665076969.htm":
                {"title": "Iphone 11", "price": 180, "location": "Maser (TV)"},
            "https://www.subito.it/telefonia/iphone-x-padova-111.htm":
                {"title": "Iphone X", "price": "Unknown price", "location": "Padova (PD)"},
        }}}},
        "auto": {"https://www.subito.it/annunci-italia/vendita/usato/?q=auto": {"null": {"null": {
            # stesso annuncio di "iphone": deve essere deduplicato
            "https://www.subito.it/telefonia/iphone-11-treviso-665076969.htm":
                {"title": "Iphone 11", "price": 180, "location": "Maser (TV)"},
        }}}},
    }
    (tmp_path / "searches.tracked").write_text(json.dumps(legacy))
    (tmp_path / "telegram_api_credentials").write_text(json.dumps({"token": "123:abc", "chatid": "@canale"}))
    (tmp_path / "ntfy_config").write_text(json.dumps({"ntfy_server": "https://ntfy.sh", "ntfy_topic": "t"}))

    app = App(Paths(legacy=tmp_path, data=tmp_path / "data"), file_logging=False)
    try:
        r = app.import_report
        assert r["searches"] == 2 and r["ads"] == 2 and not r["errors"]
        iphone = app.repo.find_search("iphone")
        assert (iphone.min_price, iphone.max_price) == (100, 1400)
        assert app.repo.find_search("auto").min_price is None
        ads = {a["ad_key"]: a for a in app.repo.ads_for_search(iphone.id)}
        assert ads["665076969"]["town"] == "Maser" and ads["665076969"]["province"] == "TV"
        assert ads["111"]["price"] is None
        assert app.repo.count_ads() == 2
        assert app.settings.get("telegram") == {"token": "123:abc", "chatid": "@canale"}
        assert app.settings.get("ntfy") == {"server": "https://ntfy.sh", "topic": "t"}
    finally:
        app.close()

    # secondo avvio: nessun nuovo import, file originali intatti
    app2 = App(Paths(legacy=tmp_path, data=tmp_path / "data"), file_logging=False)
    try:
        assert app2.import_report is None
        assert len(app2.repo.list_searches()) == 2
    finally:
        app2.close()
    assert json.loads((tmp_path / "searches.tracked").read_text()) == legacy


def test_import_without_files(app: App):
    assert app.import_report["searches"] == 0 and app.import_report["files"] == []


# ------------------------------------------------------------------- ricerche

def test_unique_names_case_insensitive(app: App):
    add(app, "iPhone", "https://www.subito.it/a")
    with pytest.raises(Conflict):
        add(app, "iphone", "https://www.subito.it/b")


def test_delete_keeps_shared_and_favorite_ads(app: App):
    a = add(app, "A", "https://www.subito.it/a")
    b = add(app, "B", "https://www.subito.it/b")
    app.engine._fetch.pages = {a.url: [make_ad("1"), make_ad("2"), make_ad("3")], b.url: [make_ad("1")]}
    app.engine.run_all(notify=False)
    fav = next(r for r in app.repo.ads_for_search(a.id) if r["ad_key"] == "3")
    app.repo.set_ad_flags(fav["id"], favorite=True)
    app.repo.delete_search(a.id)
    keys = {r["ad_key"] for r in app.repo.db.query("SELECT ad_key FROM ads")}
    assert keys == {"1", "3"}  # "1" è ancora di B, "3" è preferito, "2" eliminato


# ------------------------------------------------------------------- engine

def test_new_dedup_price_drop_and_sold(app: App):
    a = add(app, "A", "https://www.subito.it/a")
    b = add(app, "B", "https://www.subito.it/b")
    fetch = app.engine._fetch
    fetch.pages = {a.url: [make_ad("1", 300), make_ad("2", 100)], b.url: [make_ad("1", 300)]}

    r = app.engine.run_all(notify=False)
    assert [len(x.new) for x in r] == [2, 0]   # "1" trovato anche da B: non è di nuovo "nuovo"
    assert app.repo.count_ads() == 2
    assert app.repo.count_ads(b.id) == 1

    # secondo giro: ribasso di "1", "2" venduto, "3" nuovo
    fetch.pages[a.url] = [make_ad("1", 250), make_ad("2", 100, sold=True), make_ad("3", 50)]
    res = app.engine.run_search(a.id, notify=False)
    assert [x.ad_key for x in res.new] == ["3"]
    assert [(ad.ad_key, old) for ad, old in res.price_drops] == [("1", 300)]
    assert res.sold == 1
    one = app.repo.db.query_one("SELECT id FROM ads WHERE ad_key = '1'")["id"]
    assert [h["price"] for h in app.repo.price_history(one)] == [300, 250]
    assert app.repo.db.query_one("SELECT sold_at FROM ads WHERE ad_key = '2'")["sold_at"]

    # prezzo invariato: nessuna nuova riga di storico
    app.engine.run_search(a.id, notify=False)
    assert len(app.repo.price_history(one)) == 2


def test_hidden_ads_do_not_generate_price_drops(app: App):
    a = add(app, "A", "https://www.subito.it/a")
    app.engine._fetch.pages = {a.url: [make_ad("1", 300)]}
    app.engine.run_search(a.id, notify=False)
    ad_id = app.repo.db.query_one("SELECT id FROM ads")["id"]
    app.repo.set_ad_flags(ad_id, hidden=True)
    app.engine._fetch.pages = {a.url: [make_ad("1", 200)]}
    assert app.engine.run_search(a.id, notify=False).price_drops == []


def test_local_filters(app: App):
    a = add(app, "A", "https://www.subito.it/a", min_price=100, max_price=500, exclude_words=["rotto"])
    app.engine._fetch.pages = {a.url: [make_ad("1", 50), make_ad("2", 300), make_ad("3", 900),
                                       make_ad("4", 300, title="iPhone ROTTO"), make_ad("5", None)]}
    res = app.engine.run_search(a.id, notify=False)
    assert sorted(x.ad_key for x in res.new) == ["2", "5"]
    assert res.found == 5 and res.matched == 2


def test_notification_rules(app: App):
    s = Search(id=1, name="A", url="u", notify_new=True, notify_price_drop=False, notify_max_price=200)
    new, drops = app.engine.notification_targets(s, [make_ad("1", 150), make_ad("2", 300), make_ad("3", None)],
                                                 [(make_ad("4", 100), 150)])
    assert [a.ad_key for a in new] == ["1", "3"] and drops == []
    s2 = replace(s, notify_new=False, notify_price_drop=True, notify_max_price=None)
    new, drops = app.engine.notification_targets(s2, [make_ad("1")], [(make_ad("4", 100), 150)])
    assert new == [] and len(drops) == 1


def test_errors_are_recorded_and_do_not_stop_other_searches(app: App):
    a = add(app, "A", "https://www.subito.it/a")
    b = add(app, "B", "https://www.subito.it/b")
    app.engine._fetch.pages = {a.url: ScrapeError("bloccato", "blocked"), b.url: [make_ad("1")]}
    res = app.engine.run_all(notify=False)
    assert [x.ok for x in res] == [False, True]
    app.engine.run_search(a.id, notify=False)
    sa = app.repo.get_search(a.id)
    assert sa.consecutive_errors == 2 and sa.last_error == "bloccato"
    errors = [e for e in app.events.since() if e["level"] == "error"]
    assert errors and errors[-1]["error_kind"] == "blocked"


def test_unexpected_exception_is_reported(app: App):
    a = add(app, "A", "https://www.subito.it/a")
    app.engine._fetch.pages = {a.url: RuntimeError("boom")}
    res = app.engine.run_search(a.id, notify=False)
    assert not res.ok and "RuntimeError: boom" in res.error


def test_disabled_searches_are_skipped(app: App):
    a = add(app, "A", "https://www.subito.it/a", enabled=False)
    assert app.engine.run_all(notify=False) == []
    assert app.engine.run_search(a.id, notify=False).ok  # "Esegui ora" funziona comunque


def test_update_with_reset_unlinks_results(app: App):
    a = add(app, "A", "https://www.subito.it/a")
    app.engine._fetch.pages = {a.url: [make_ad("1")]}
    app.engine.run_search(a.id, notify=False)
    app.repo.update_search(a.id, replace(a, url="https://www.subito.it/z"), reset_results=True)
    assert app.repo.count_ads(a.id) == 0
    assert app.repo.get_search(a.id).last_run_at is None


# ------------------------------------------------------------------- telegram

def test_telegram_escapes_and_uses_params(monkeypatch):
    calls = {}

    class Resp:
        status_code = 200

    def fake_get(url, params=None, timeout=None):
        calls.update(url=url, params=params)
        return Resp()

    monkeypatch.setattr("core.notifier.requests.get", fake_get)
    ad = make_ad("1", 100, title="iPhone_12 *nuovo* <top> & [garanzia]")
    send_telegram({"token": "T", "chatid": "@c"}, format_html(ad, "Ricerca & co"))
    assert calls["url"] == "https://api.telegram.org/botT/sendMessage"   # niente query string a mano
    text = calls["params"]["text"]
    assert "&lt;top&gt; &amp; [garanzia]" in text and "Ricerca &amp; co" in text
    assert calls["params"]["parse_mode"] == "HTML"


# ------------------------------------------------------------------- conversione URL -> parametri

def test_legacy_urls_converted_to_params(tmp_path: Path):
    legacy = {
        "tv": {"https://www.subito.it/annunci-veneto/vendita/elettronica/?q=tv": {"50": {"null": {}}}},
        "mondeo": {"https://www.subito.it/annunci-italia/vendita/auto/ford/mondeo/": {"null": {"null": {}}}},
    }
    (tmp_path / "searches.tracked").write_text(json.dumps(legacy))
    paths = Paths(legacy=tmp_path, data=tmp_path / "data")
    app = App(paths, file_logging=False)
    try:
        tv = app.repo.find_search("tv")
        assert tv.params["region"] == "veneto" and tv.params["category"] == "elettronica"
        assert tv.params["keywords"] == "tv" and tv.params["min_price"] == 50
        assert tv.url == "https://www.subito.it/annunci-veneto/vendita/elettronica/?q=tv"  # URL invariato
        assert app.repo.find_search("mondeo").params is None                              # resta solo URL
        warnings = [e for e in app.events.since() if "non convertibile" in e["message"]]
        assert len(warnings) == 1
    finally:
        app.close()
    app2 = App(paths, file_logging=False)  # al riavvio nessun nuovo avviso
    try:
        assert len([e for e in app2.events.since() if "non convertibile" in e["message"]]) == 1
    finally:
        app2.close()


def test_run_emits_start_and_end_phases(app: App):
    """L'interfaccia mostra "controllo in corso" tra l'evento start e quello end."""
    s = add(app, "TV", "https://www.subito.it/annunci-italia/vendita/usato/?q=tv")
    app.engine._fetch.default = [make_ad("1")]
    app.engine.run_search(s.id, notify=False)
    app.engine._fetch.default = []
    app.engine.run_search(s.id, notify=False)
    app.engine._fetch.pages[s.url] = ScrapeError("giù", "network")
    app.engine.run_search(s.id, notify=False)
    phases = [(e["phase"], e["kind"]) for e in app.events.since(0) if e.get("phase")]
    assert phases == [("start", "query"), ("end", "new_items"), ("start", "query"), ("end", "query"),
                      ("start", "query"), ("end", "error")]
