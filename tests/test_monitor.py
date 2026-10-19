from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from core import App, Paths, Search
from core.monitor import BLOCK_PAUSE, MAX_BACKOFF, block_pause, next_delay, window_ok
from core.scraper import ScrapeError
from tests.helpers import FakeFetch, make_ad


class Clock:
    def __init__(self, start: datetime = datetime(2026, 10, 19, 12, 0, 0)):
        self.t = start.timestamp()

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def env(tmp_path: Path):
    app = App(Paths(legacy=tmp_path, data=tmp_path / "data"), file_logging=False, throttle=False)
    app.engine._fetch = FakeFetch()
    app.settings.update("monitor", {"jitter_sec": 0, "interval_sec": 300, "sync": False})
    clock = Clock()
    app.monitor.clock = clock
    sent: list[tuple[str, int, int]] = []
    app.notifier.notify = lambda name, sid, new, drops: sent.append((name, len(new), len(drops)))
    yield app, clock, sent
    app.close()


def add(app: App, name: str, **kw) -> Search:
    return app.repo.create_search(Search(id=None, name=name, url=f"https://www.subito.it/{name}", **kw))


def step(app: App) -> float:
    return asyncio.run(app.monitor._step())


# ------------------------------------------------------------------ funzioni pure

def test_next_delay_backoff():
    assert next_delay(300, 0) == 300
    assert next_delay(300, 1) == 600
    assert next_delay(300, 3) == 2400
    assert next_delay(300, 10) == MAX_BACKOFF            # tetto
    assert next_delay(60, 1, "blocked") == BLOCK_PAUSE    # un blocco aspetta almeno 15 minuti
    assert next_delay(10_000, 1) == 10_000               # intervallo oltre il tetto: si usa l'intervallo


def test_block_pause_grows():
    assert [block_pause(n) for n in (1, 2, 3, 4, 5)] == [900, 1800, 3600, 7200, 7200]


def test_window_ok():
    noon = datetime(2026, 1, 1, 12, 0)
    night = datetime(2026, 1, 1, 23, 30)
    assert window_ok(noon, None, None)
    assert window_ok(noon, "08:00", "20:00") and not window_ok(night, "08:00", "20:00")
    assert window_ok(night, "22:00", "07:00") and not window_ok(noon, "22:00", "07:00")


# ------------------------------------------------------------------ ciclo

def test_first_run_silent_then_notifies_and_respects_interval(env):
    app, clock, sent = env
    s = add(app, "a")
    app.engine._fetch.default = [make_ad("1")]
    step(app)                                  # primo giro: salva senza notificare
    assert sent == [] and app.monitor.next_due[s.id] == clock() + 300
    assert step(app) == pytest.approx(300)     # niente da fare: attende l'intervallo
    clock.advance(301)
    app.engine._fetch.default = [make_ad("1"), make_ad("2")]
    step(app)
    assert sent == [("a", 1, 0)]


def test_per_search_interval_and_order(env):
    app, clock, _ = env
    fast = add(app, "fast", interval_sec=60)
    slow = add(app, "slow")
    step(app)
    step(app)
    calls = app.engine._fetch.calls
    assert len(calls) == 2
    assert app.monitor.next_due[fast.id] == clock() + 60
    assert app.monitor.next_due[slow.id] == clock() + 300
    clock.advance(61)
    step(app)
    assert calls[-1].endswith("/fast") and len(calls) == 3


def test_backoff_on_errors(env):
    app, clock, _ = env
    s = add(app, "a")
    app.engine._fetch.pages[s.url] = ScrapeError("rete", "network")
    step(app)
    assert app.monitor.next_due[s.id] == clock() + 600           # 1 errore: intervallo x2
    clock.advance(601)
    step(app)
    assert app.monitor.next_due[s.id] == clock() + 1200          # 2 errori: x4
    app.engine._fetch.pages[s.url] = [make_ad("1")]
    clock.advance(1201)
    step(app)
    assert app.monitor.next_due[s.id] == clock() + 300           # torna normale


def test_block_pauses_everything(env):
    app, clock, _ = env
    a = add(app, "a")
    add(app, "b")
    app.engine._fetch.pages[a.url] = ScrapeError("403", "blocked")
    step(app)
    assert app.monitor.state != "checking"
    assert app.monitor.cooldown_until == clock() + BLOCK_PAUSE
    calls = len(app.engine._fetch.calls)
    step(app)
    assert app.monitor.state == "cooldown" and len(app.engine._fetch.calls) == calls  # "b" non parte
    assert any("bloccando" in a for a in app.monitor.health()["alerts"])
    clock.advance(BLOCK_PAUSE + 1)
    step(app)
    assert len(app.engine._fetch.calls) == calls + 1


def test_global_window_pauses(env):
    app, clock, _ = env
    add(app, "a")
    app.settings.update("monitor", {"active_from": "20:00", "active_to": "23:00"})  # ora finta: 12:00
    step(app)
    assert app.monitor.state == "paused" and app.engine._fetch.calls == []


def test_search_window_and_disabled_are_skipped(env):
    app, clock, _ = env
    add(app, "night", active_from="22:00", active_to="06:00")
    add(app, "off", enabled=False)
    on = add(app, "on")
    step(app)
    step(app)
    assert app.engine._fetch.calls == [on.url]


def test_structure_alert(env):
    app, clock, _ = env
    s = add(app, "a")
    app.engine._fetch.pages[s.url] = ScrapeError("Struttura della pagina cambiata: x", "structure")
    step(app)
    assert any("struttura" in a.lower() for a in app.monitor.health()["alerts"])


def test_deleted_search_during_run(env):
    app, clock, _ = env
    s = add(app, "a")

    def fetch_and_delete(url, session=None):
        app.repo.delete_search(s.id)
        return []
    app.engine._fetch = fetch_and_delete
    step(app)
    assert s.id not in app.monitor.next_due


def test_start_stop_real_loop(env):
    app, clock, _ = env
    app.monitor.clock = __import__("time").time
    add(app, "a")

    async def scenario():
        assert await app.monitor.start()
        assert not await app.monitor.start()          # già avviato
        for _ in range(100):
            if app.engine._fetch.calls:
                break
            await asyncio.sleep(0.02)
        assert app.monitor.status()["running"]
        assert await app.monitor.stop()
        assert app.monitor.status()["state"] == "stopped"

    asyncio.run(scenario())
    assert app.engine._fetch.calls


# ------------------------------------------------------------------ modalità sincronizzata

@pytest.fixture
def sync_env(env):
    app, clock, sent = env
    app.settings.update("monitor", {"sync": True})
    return app, clock, sent


def run_cycle(app: App) -> float:
    """Esegue passi finché il giro in corso finisce; restituisce l'attesa fino al giro dopo."""
    wait = step(app)
    while app.monitor.queue or wait == 0:
        wait = step(app)
    return wait


def test_sync_runs_all_searches_together(sync_env):
    app, clock, _ = sync_env
    a, b, c = add(app, "a"), add(app, "b"), add(app, "c")
    assert run_cycle(app) == 300
    assert app.engine._fetch.calls == [a.url, b.url, c.url]
    status = app.monitor.status()
    assert status["sync"] and status["next_check"] is None   # monitor non avviato: nessun conto alla rovescia
    clock.advance(150)
    assert step(app) == 150 and len(app.engine._fetch.calls) == 3   # nessuno parte da solo a metà
    clock.advance(150)
    run_cycle(app)
    assert app.engine._fetch.calls[3:] == [a.url, b.url, c.url]


def test_sync_manual_run_does_not_desync(sync_env):
    """'Esegui ora' su una ricerca non la sposta: al giro successivo parte con le altre."""
    app, clock, _ = sync_env
    a, b = add(app, "a"), add(app, "b")
    run_cycle(app)
    clock.advance(200)
    app.monitor.note_run(app.engine.run_search(a.id, notify=False))
    clock.advance(100)
    run_cycle(app)
    assert app.engine._fetch.calls[-2:] == [a.url, b.url]


def test_sync_longer_interval_and_backoff_skip_cycles(sync_env):
    app, clock, _ = sync_env
    a = add(app, "a")
    slow = add(app, "slow", interval_sec=600)
    bad = add(app, "bad")
    app.engine._fetch.pages[bad.url] = ScrapeError("giù", "network")
    run_cycle(app)
    calls = len(app.engine._fetch.calls)
    clock.advance(300)
    run_cycle(app)                                   # giro 2: "slow" (600 s) e "bad" (backoff 600 s) saltano
    assert app.engine._fetch.calls[calls:] == [a.url]
    clock.advance(300)
    run_cycle(app)                                   # giro 3: tutte e tre
    assert sorted(app.engine._fetch.calls[calls + 1:]) == sorted([a.url, slow.url, bad.url])


def test_sync_disabled_search_leaves_cycle(sync_env):
    app, clock, _ = sync_env
    a, b = add(app, "a"), add(app, "b")
    step(app)                                        # giro iniziato: "a" fatta, "b" in coda
    app.repo.set_enabled(b.id, False)
    run_cycle(app)
    assert app.engine._fetch.calls == [a.url]


def test_sync_manual_run_all_restarts_countdown(sync_env):
    app, clock, _ = sync_env
    add(app, "a")
    run_cycle(app)
    clock.advance(250)
    app.monitor.note_cycle()
    assert app.monitor.cycle_due == clock() + 300
