from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import App, Paths
from tests.helpers import FakeFetch, make_ad
from webapp.main import create_app

PARAMS = {"keywords": "iphone", "region": "veneto", "province": "padova", "category": "telefonia",
          "max_price": 400}


@pytest.fixture
def core(tmp_path: Path):
    app = App(Paths(legacy=tmp_path, data=tmp_path / "data"), file_logging=False, throttle=False)
    app.engine._fetch = FakeFetch()
    app.engine._fetch.default = [make_ad("1", 100), make_ad("2", 300), make_ad("3", 900)]
    app.notifier.notify = lambda *a, **k: None
    yield app
    app.close()


@pytest.fixture
def client(core):
    with TestClient(create_app(core, trusted_hosts={"testserver"})) as c:
        yield c


def create(client, name="iPhone", **extra):
    body = {"name": name, "mode": "params", "params": PARAMS, **extra}
    r = client.post("/api/searches", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ supporto form

def test_meta_geo_url(client):
    meta = client.get("/api/meta").json()
    assert any(c["slug"] == "telefonia" for c in meta["catalog"]["categories"])
    geo = client.get("/api/geo", params={"q": "Pad"}).json()
    assert geo[0]["label"] == "Padova (provincia)"
    built = client.post("/api/url/build", json=PARAMS).json()
    assert built["url"] == ("https://www.subito.it/annunci-veneto/vendita/telefonia/padova/"
                            "?q=iphone&pe=400&order=datedesc")
    parsed = client.post("/api/url/parse", json={"url": built["url"]}).json()
    assert parsed["params"]["province"] == "padova"
    assert client.post("/api/url/parse", json={"url": "https://example.com"}).status_code == 400
    assert client.post("/api/url/build", json={"category": "boh"}).status_code == 400


def test_preview_does_not_save(client, core):
    r = client.post("/api/preview", json={"params": PARAMS, "exclude_words": "annuncio 2"}).json()
    assert r["found"] == 3 and r["matched"] == 1          # prezzo max 400 e parola esclusa
    assert core.repo.count_ads() == 0


# ------------------------------------------------------------------ ricerche

def test_create_runs_silently_and_lists(client):
    out = create(client)
    s = out["search"]
    assert s["url"].endswith("?q=iphone&pe=400&order=datedesc")
    assert out["run"]["ok"] and s["stats"]["total"] == 2 and s["stats"]["new"] == 0
    assert s["summary"]["location"] == "Padova (provincia)"
    listed = client.get("/api/searches").json()
    assert [x["name"] for x in listed] == ["iPhone"]


def test_create_url_mode_unrecognized(client):
    r = client.post("/api/searches", params={"run": False}, json={
        "name": "Mondeo", "mode": "url", "url": "https://www.subito.it/annunci-italia/vendita/auto/ford/mondeo/",
        "max_price": 5000})
    assert r.status_code == 201
    body = r.json()
    assert body["search"]["params"] is None and body["search"]["max_price"] == 5000 and body["warnings"]


@pytest.mark.parametrize("body, msg", [
    ({"name": "x", "params": PARAMS, "interval_sec": 10}, "Intervallo"),
    ({"name": "x", "params": PARAMS, "active_from": "08:00"}, "Fascia"),
    ({"name": "x", "params": {**PARAMS, "category": "auto", "ad_type": "g"}}, "non è disponibile"),
    ({"name": "x", "mode": "url", "url": "https://google.com"}, "subito.it"),
])
def test_create_validation(client, body, msg):
    r = client.post("/api/searches", json=body)
    assert r.status_code == 400 and msg in r.json()["detail"]


def test_duplicate_names_rejected(client):
    create(client)
    r = client.post("/api/searches", json={"name": "iphone", "params": PARAMS})
    assert r.status_code == 400


def test_update_rename_keeps_results_and_url_change_resets(client):
    sid = create(client)["search"]["id"]
    r = client.put(f"/api/searches/{sid}", json={"name": "Nuovo nome", "params": PARAMS}).json()
    assert not r["reset"] and r["search"]["stats"]["total"] == 2
    r = client.put(f"/api/searches/{sid}", json={"name": "Nuovo nome", "params": {**PARAMS, "max_price": 1000}}).json()
    assert r["reset"] and r["run"]["ok"] and r["search"]["stats"]["total"] == 3


def test_duplicate_toggle_run_delete(client):
    sid = create(client)["search"]["id"]
    dup = client.post(f"/api/searches/{sid}/duplicate").json()
    assert dup["name"] == "iPhone (copia)" and dup["enabled"] is False
    assert client.post(f"/api/searches/{sid}/enabled", json={"enabled": False}).json()["enabled"] is False
    run = client.post(f"/api/searches/{sid}/run").json()
    assert run["ok"] and run["found"] == 3
    assert client.delete(f"/api/searches/{sid}").status_code == 200
    assert client.get(f"/api/searches/{sid}").status_code == 404
    assert client.post("/api/searches/999/run").status_code == 404


def test_export_import_round_trip(client):
    create(client, exclude_words="rotto, cover", interval_sec=600)
    exported = client.get("/api/searches/export")
    assert "attachment" in exported.headers["content-disposition"]
    data = exported.json()
    assert data["searches"][0]["exclude_words"] == ["rotto", "cover"]
    out = client.post("/api/searches/import", json=data).json()
    assert out["created"] == ["iPhone 2"] and out["errors"] == []
    bad = client.post("/api/searches/import", json={"searches": [{"name": "x", "url": "nope"}]}).json()
    assert bad["created"] == [] and len(bad["errors"]) == 1


def test_run_all_is_background(client, core):
    create(client)
    assert client.post("/api/run-all").status_code == 202
    for _ in range(100):
        if any("Esecuzione manuale completata" in e["message"] for e in core.events.since()):
            break
        time.sleep(0.02)
    assert any("Esecuzione manuale completata" in e["message"] for e in client.get("/api/events").json())


# ------------------------------------------------------------------ annunci

def test_ads_filters_flags_and_history(client, core):
    sid = create(client)["search"]["id"]
    core.engine._fetch.default = [make_ad("1", 80), make_ad("2", 300, sold=True), make_ad("4", 50)]
    client.post(f"/api/searches/{sid}/run")
    all_ads = client.get("/api/ads").json()
    assert all_ads["total"] == 3
    keys = lambda status: sorted(a["ad_key"] for a in client.get("/api/ads", params={"status": status}).json()["items"])  # noqa: E731
    assert keys("new") == ["4"]
    assert keys("drop") == ["1"]
    assert keys("sold") == ["2"]
    ad1 = next(a for a in all_ads["items"] if a["ad_key"] == "1")
    assert ad1["prev_price"] == 100 and ad1["is_drop"] and ad1["searches"][0]["name"] == "iPhone"
    detail = client.get(f"/api/ads/{ad1['id']}").json()
    assert [h["price"] for h in detail["history"]] == [100, 80]
    client.patch(f"/api/ads/{ad1['id']}", json={"favorite": True, "hidden": True})
    assert keys("hidden") == ["1"]
    assert all(a["ad_key"] != "1" for a in client.get("/api/ads").json()["items"])
    sorted_ads = client.get("/api/ads", params={"sort": "price_asc"}).json()["items"]
    assert [a["price"] for a in sorted_ads] == [50, 300]
    assert client.get("/api/ads", params={"q": "Annuncio 4"}).json()["total"] == 1
    assert client.post(f"/api/searches/{sid}/seen").status_code == 200
    assert keys("new") == []


def test_dashboard(client):
    create(client)
    d = client.get("/api/dashboard").json()
    assert d["searches_active"] == 1 and d["ads_total"] == 2 and d["new_today"] == 2
    assert d["per_day"][-1]["count"] == 2 and len(d["latest"]) == 2


# ------------------------------------------------------------------ monitor

def test_monitor_start_stop(client):
    assert client.post("/api/monitor/start").json()["running"] is True
    assert client.post("/api/monitor/stop").json()["state"] == "stopped"
    assert "alerts" in client.get("/api/health").json()


# ------------------------------------------------------------------ impostazioni

def test_settings_mask_token_and_validate(client, core):
    tok = "123456789:" + "A" * 30
    r = client.put("/api/settings/telegram", json={"token": tok, "chatid": "@canale"}).json()
    assert r["telegram"]["token_set"] and "token" not in r["telegram"] and r["telegram"]["token_hint"] == "…AAAA"
    client.put("/api/settings/telegram", json={"token": "", "chatid": "@altro"})       # vuoto = invariato
    assert core.settings.get("telegram")["token"] == tok
    client.put("/api/settings/telegram", json={"clear_token": True})
    assert core.settings.get("telegram")["token"] == ""
    for section, body in [("telegram", {"token": "abc"}), ("monitor", {"interval_sec": 5}),
                          ("ntfy", {"server": "ftp://x"}), ("monitor", {"boh": 1}), ("nope", {}),
                          ("server", {"lan": True}), ("server", {"pin": "12"})]:
        assert client.put(f"/api/settings/{section}", json=body).status_code == 400, (section, body)
    r = client.put("/api/settings/monitor", json={"interval_sec": 120, "active_from": "8", "active_to": "23:30"})
    assert r.json()["monitor"]["active_from"] == "08:00"


def test_notification_test_errors_are_400(client):
    r = client.post("/api/notifications/test/telegram")
    assert r.status_code == 400 and "non configurato" in r.json()["detail"]


# ------------------------------------------------------------------ backup

def test_backup_and_restore(client, core):
    sid = create(client)["search"]["id"]
    name = client.post("/api/backups").json()["name"]
    assert [b["name"] for b in client.get("/api/backups").json()] == [name]
    client.delete(f"/api/searches/{sid}")
    assert client.get("/api/searches").json() == []
    assert client.post(f"/api/backups/{name}/restore").status_code == 200
    assert [s["name"] for s in client.get("/api/searches").json()] == ["iPhone"]
    assert len(client.get("/api/backups").json()) == 2          # copia di sicurezza prima del ripristino
    assert client.get(f"/api/backups/{name}").content[:15] == b"SQLite format 3"
    r = client.post("/api/backups/upload/restore", content=b"non un database",
                    headers={"content-type": "application/octet-stream"})
    assert r.status_code == 400
    assert client.get("/api/backups/..%2Fsubito.db").status_code in (400, 404)
    assert client.post("/api/maintenance/cleanup", params={"days": 30}).json()["removed"] == 0


# ------------------------------------------------------------------ sicurezza

def test_untrusted_host_rejected(core):
    with TestClient(create_app(core), base_url="http://evil.example") as c:
        assert c.get("/api/meta").status_code == 400


def test_cross_site_writes_rejected(client):
    assert client.post("/api/seen", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/seen", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post("/api/seen", headers={"origin": "http://testserver"}).status_code == 200
    assert client.get("/api/meta", headers={"origin": "https://evil.example"}).status_code == 200


def test_lan_mode_requires_pin(client, core):
    core.settings.update("server", {"lan": True, "pin": "2468"})
    # il client di test non è 127.0.0.1: viene trattato come un dispositivo della rete
    assert client.get("/api/meta").status_code == 401
    assert client.get("/", follow_redirects=False).status_code == 303
    assert "PIN errato" in client.post("/login", content="pin=0000",
                                       headers={"content-type": "application/x-www-form-urlencoded"}).text
    r = client.post("/login", content="pin=2468", follow_redirects=False,
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 303 and "subito_auth" in r.cookies
    client.cookies.set("subito_auth", r.cookies["subito_auth"])
    assert client.get("/api/meta").status_code == 200
    for _ in range(5):
        client.post("/login", content="pin=1", headers={"content-type": "application/x-www-form-urlencoded"})
    assert "Troppi tentativi" in client.post("/login", content="pin=2468",
                                             headers={"content-type": "application/x-www-form-urlencoded"}).text
