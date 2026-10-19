"""Accesso ai dati: tutte le query SQL dell'applicazione stanno qui."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .db import Database
from .models import ScrapedAd, Search, now_iso


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


@dataclass
class RecordOutcome:
    new: list[ScrapedAd]
    price_drops: list[tuple[ScrapedAd, int]]  # (annuncio, prezzo precedente)
    sold: int
    linked: int  # annunci già noti (da altre ricerche) collegati a questa ricerca


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ======================================================================= ricerche
    def list_searches(self) -> list[Search]:
        return [Search.from_row(r) for r in self.db.query("SELECT * FROM searches ORDER BY name")]

    def get_search(self, search_id: int) -> Search:
        row = self.db.query_one("SELECT * FROM searches WHERE id = ?", (search_id,))
        if not row:
            raise NotFound(f"Ricerca {search_id} non trovata")
        return Search.from_row(row)

    def find_search(self, name: str) -> Search | None:
        row = self.db.query_one("SELECT * FROM searches WHERE name = ?", (name.strip(),))
        return Search.from_row(row) if row else None

    @staticmethod
    def _search_values(s: Search) -> dict[str, Any]:
        return {
            "name": s.name.strip(), "url": s.url,
            "params": json.dumps(s.params, ensure_ascii=False) if s.params is not None else None,
            "min_price": s.min_price, "max_price": s.max_price,
            "exclude_words": json.dumps(s.exclude_words, ensure_ascii=False),
            "enabled": int(s.enabled), "interval_sec": s.interval_sec,
            "active_from": s.active_from, "active_to": s.active_to,
            "notify_new": int(s.notify_new), "notify_price_drop": int(s.notify_price_drop),
            "notify_max_price": s.notify_max_price,
        }

    def create_search(self, s: Search) -> Search:
        values = self._search_values(s)
        stamp = now_iso()
        values.update(created_at=s.created_at or stamp, updated_at=stamp, seen_at=s.seen_at)
        cols = ", ".join(values)
        marks = ", ".join(f":{k}" for k in values)
        try:
            cur = self.db.execute(f"INSERT INTO searches ({cols}) VALUES ({marks})", values)
        except sqlite3.IntegrityError as e:
            raise Conflict(f"Esiste già una ricerca chiamata '{s.name.strip()}'") from e
        return self.get_search(cur.lastrowid)

    def update_search(self, search_id: int, s: Search, reset_results: bool = False) -> Search:
        """Aggiorna i campi modificabili. Con reset_results scollega gli annunci trovati
        (es. URL cambiato) e azzera lo stato dell'ultima esecuzione."""
        self.get_search(search_id)
        values = self._search_values(s)
        values["updated_at"] = now_iso()
        assignments = ", ".join(f"{k} = :{k}" for k in values)
        try:
            with self.db.transaction() as c:
                c.execute(f"UPDATE searches SET {assignments} WHERE id = :id", {**values, "id": search_id})
                if reset_results:
                    c.execute("DELETE FROM search_ads WHERE search_id = ?", (search_id,))
                    c.execute("""UPDATE searches SET seen_at = NULL, last_run_at = NULL, last_ok_at = NULL,
                                 last_error = NULL, consecutive_errors = 0, last_found = NULL, last_new = NULL
                                 WHERE id = ?""", (search_id,))
        except sqlite3.IntegrityError as e:
            raise Conflict(f"Esiste già una ricerca chiamata '{s.name.strip()}'") from e
        return self.get_search(search_id)

    def set_enabled(self, search_id: int, enabled: bool) -> None:
        self.db.execute("UPDATE searches SET enabled = ?, updated_at = ? WHERE id = ?",
                        (int(enabled), now_iso(), search_id))

    def delete_search(self, search_id: int) -> None:
        """Elimina la ricerca e gli annunci che non appartengono ad altre ricerche
        (tranne i preferiti, che restano)."""
        self.get_search(search_id)
        with self.db.transaction() as c:
            c.execute("DELETE FROM searches WHERE id = ?", (search_id,))
            c.execute("""DELETE FROM ads WHERE favorite = 0
                         AND id NOT IN (SELECT ad_id FROM search_ads)""")

    def record_run(self, search_id: int, *, ok: bool, error: str | None = None,
                   found: int | None = None, new: int | None = None) -> None:
        stamp = now_iso()
        if ok:
            self.db.execute("""UPDATE searches SET last_run_at = ?, last_ok_at = ?, last_error = NULL,
                               consecutive_errors = 0, last_found = ?, last_new = ? WHERE id = ?""",
                            (stamp, stamp, found, new, search_id))
        else:
            self.db.execute("""UPDATE searches SET last_run_at = ?, last_error = ?,
                               consecutive_errors = consecutive_errors + 1 WHERE id = ?""",
                            (stamp, error, search_id))

    def mark_seen(self, search_id: int | None = None) -> None:
        if search_id is None:
            self.db.execute("UPDATE searches SET seen_at = ?", (now_iso(),))
        else:
            self.db.execute("UPDATE searches SET seen_at = ? WHERE id = ?", (now_iso(), search_id))

    # ======================================================================= annunci
    def record_results(self, search_id: int, ads: list[ScrapedAd], stamp: str | None = None) -> RecordOutcome:
        """Salva gli annunci (già filtrati) trovati da una ricerca, in un'unica transazione.

        - annuncio mai visto            -> inserito, storico prezzi, "nuovo"
        - già noto (anche da altre ricerche) -> aggiorna dati, collega alla ricerca
        - prezzo cambiato               -> storico prezzi; se sceso è un "ribasso"
        - marcato venduto dalla pagina  -> sold_at valorizzato
        Un annuncio già noto non è mai "nuovo" (niente doppie notifiche tra ricerche);
        gli annunci nascosti vengono aggiornati ma non generano ribassi.
        """
        stamp = stamp or now_iso()
        out = RecordOutcome([], [], 0, 0)
        with self.db.transaction() as c:
            for ad in ads:
                row = c.execute("SELECT id, price, hidden, sold_at FROM ads WHERE ad_key = ?",
                                (ad.ad_key,)).fetchone()
                if ad.sold:
                    if row and not row["sold_at"]:
                        c.execute("UPDATE ads SET sold_at = ?, last_seen_at = ? WHERE id = ?",
                                  (stamp, stamp, row["id"]))
                        out.sold += 1
                    continue

                if row is None:
                    cur = c.execute(
                        """INSERT INTO ads (ad_key, urn, link, title, price, location, town, province, region,
                               category, ad_type, shipping, company, image, published_at, first_seen_at, last_seen_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (ad.ad_key, ad.urn, ad.link, ad.title, ad.price, ad.location, ad.town, ad.province,
                         ad.region, ad.category, ad.ad_type, _bool(ad.shipping), _bool(ad.company), ad.image,
                         ad.published_at, stamp, stamp))
                    ad_id = cur.lastrowid
                    c.execute("INSERT INTO price_history (ad_id, price, seen_at) VALUES (?, ?, ?)",
                              (ad_id, ad.price, stamp))
                    out.new.append(ad)
                else:
                    ad_id = row["id"]
                    old_price = row["price"]
                    c.execute(
                        """UPDATE ads SET urn = ?, link = ?, title = ?, price = ?, location = ?, town = ?,
                               province = ?, region = ?, category = ?, ad_type = ?,
                               shipping = COALESCE(?, shipping), company = COALESCE(?, company),
                               image = COALESCE(?, image), published_at = COALESCE(?, published_at),
                               last_seen_at = ?, sold_at = NULL
                           WHERE id = ?""",
                        (ad.urn, ad.link, ad.title, ad.price, ad.location, ad.town, ad.province, ad.region,
                         ad.category, ad.ad_type, _bool(ad.shipping), _bool(ad.company), ad.image,
                         ad.published_at, stamp, ad_id))
                    if ad.price != old_price:
                        c.execute("INSERT INTO price_history (ad_id, price, seen_at) VALUES (?, ?, ?)",
                                  (ad_id, ad.price, stamp))
                        if (old_price is not None and ad.price is not None and ad.price < old_price
                                and not row["hidden"]):
                            out.price_drops.append((ad, old_price))

                linked = c.execute("INSERT OR IGNORE INTO search_ads (search_id, ad_id, found_at) VALUES (?, ?, ?)",
                                   (search_id, ad_id, stamp)).rowcount
                if linked and row is not None:
                    out.linked += 1
        return out

    def ads_for_search(self, search_id: int) -> list[sqlite3.Row]:
        return self.db.query(
            """SELECT a.*, sa.found_at FROM ads a JOIN search_ads sa ON sa.ad_id = a.id
               WHERE sa.search_id = ? ORDER BY sa.found_at DESC, a.id DESC""", (search_id,))

    def count_ads(self, search_id: int | None = None) -> int:
        if search_id is None:
            return self.db.query_one("SELECT COUNT(*) FROM ads")[0]
        return self.db.query_one("SELECT COUNT(*) FROM search_ads WHERE search_id = ?", (search_id,))[0]

    def price_history(self, ad_id: int) -> list[sqlite3.Row]:
        return self.db.query("SELECT price, seen_at FROM price_history WHERE ad_id = ? ORDER BY seen_at, id",
                             (ad_id,))

    def set_ad_flags(self, ad_id: int, *, favorite: bool | None = None, hidden: bool | None = None) -> None:
        if favorite is not None:
            self.db.execute("UPDATE ads SET favorite = ? WHERE id = ?", (int(favorite), ad_id))
        if hidden is not None:
            self.db.execute("UPDATE ads SET hidden = ? WHERE id = ?", (int(hidden), ad_id))

    # ======================================================================= consultazione annunci
    # "nuovo" = trovato da una ricerca dopo che l'utente l'ha segnata come vista
    _IS_NEW = """EXISTS (SELECT 1 FROM search_ads x JOIN searches s ON s.id = x.search_id
                         WHERE x.ad_id = a.id AND x.found_at > COALESCE(s.seen_at, s.created_at))"""
    # penultimo prezzo noto: serve per RIBASSO e per mostrare il prezzo barrato
    _PREV_PRICE = """(SELECT h.price FROM price_history h WHERE h.ad_id = a.id AND h.price IS NOT NULL
                       ORDER BY h.seen_at DESC, h.id DESC LIMIT 1 OFFSET 1)"""
    SORTS = {
        "found_desc": "a.first_seen_at DESC, a.id DESC",
        "found_asc": "a.first_seen_at ASC, a.id ASC",
        "price_asc": "a.price IS NULL, a.price ASC, a.id DESC",
        "price_desc": "a.price IS NULL, a.price DESC, a.id DESC",
        # senza data di pubblicazione: in fondo, ordinati per quando sono stati trovati
        "published_desc": "a.published_at IS NULL, a.published_at DESC, a.first_seen_at DESC, a.id DESC",
    }

    def _ad_filters(self, *, search_id: int | None = None, text: str | None = None,
                    min_price: int | None = None, max_price: int | None = None, shipping: bool | None = None,
                    status: str | None = None, ad_id: int | None = None) -> tuple[str, list[Any]]:
        """Condizione WHERE comune a elenco, statistiche ed esportazione.
        status: new | drop | sold | favorite | hidden | active | any.
        Gli annunci nascosti compaiono solo con status="hidden" (o "any")."""
        where = ["1 = 1"]
        params: list[Any] = []
        if ad_id is not None:
            where.append("a.id = ?")
            params.append(ad_id)
        if search_id is not None:
            where.append("EXISTS (SELECT 1 FROM search_ads y WHERE y.ad_id = a.id AND y.search_id = ?)")
            params.append(search_id)
        if text:
            where.append("(a.title LIKE ? OR a.location LIKE ?)")
            params += [f"%{text}%", f"%{text}%"]
        if min_price is not None:
            where.append("a.price >= ?")
            params.append(min_price)
        if max_price is not None:
            where.append("a.price <= ?")
            params.append(max_price)
        if shipping:
            where.append("a.shipping = 1")
        if status == "hidden":
            where.append("a.hidden = 1")
        elif status != "any":
            where.append("a.hidden = 0")
        if status == "new":
            where.append(self._IS_NEW)
        elif status == "drop":
            where.append(f"a.price < {self._PREV_PRICE}")
        elif status == "sold":
            where.append("a.sold_at IS NOT NULL")
        elif status == "active":
            where.append("a.sold_at IS NULL")
        elif status == "favorite":
            where.append("a.favorite = 1")
        return " AND ".join(where), params

    def query_ads(self, *, search_id: int | None = None, text: str | None = None,
                  min_price: int | None = None, max_price: int | None = None, shipping: bool | None = None,
                  status: str | None = None, sort: str = "found_desc", limit: int = 50, offset: int = 0,
                  ad_id: int | None = None) -> tuple[list[dict[str, Any]], int]:
        """Annunci deduplicati con filtri (vedi _ad_filters), ordinati e paginati."""
        cond, params = self._ad_filters(search_id=search_id, text=text, min_price=min_price,
                                        max_price=max_price, shipping=shipping, status=status, ad_id=ad_id)
        order = self.SORTS.get(sort, self.SORTS["found_desc"])
        total = self.db.query_one(f"SELECT COUNT(*) FROM ads a WHERE {cond}", params)[0]
        rows = self.db.query(
            f"""SELECT a.*, {self._PREV_PRICE} AS prev_price, {self._IS_NEW} AS is_new,
                   (SELECT json_group_array(json_object('id', s.id, 'name', s.name))
                      FROM search_ads z JOIN searches s ON s.id = z.search_id WHERE z.ad_id = a.id) AS searches
                FROM ads a WHERE {cond} ORDER BY {order} LIMIT ? OFFSET ?""",
            [*params, max(1, min(limit, 500)), max(0, offset)])
        items = []
        for r in rows:
            d = dict(r)
            d["searches"] = json.loads(d["searches"] or "[]")
            d["is_new"] = bool(d["is_new"])
            d["is_drop"] = d["prev_price"] is not None and d["price"] is not None and d["price"] < d["prev_price"]
            for key in ("favorite", "hidden"):
                d[key] = bool(d[key])
            for key in ("shipping", "company"):
                d[key] = None if d[key] is None else bool(d[key])
            items.append(d)
        return items, total

    def get_ad(self, ad_id: int) -> dict[str, Any]:
        items, _ = self.query_ads(ad_id=ad_id, status="any")
        if not items:
            raise NotFound(f"Annuncio {ad_id} non trovato")
        ad = items[0]
        ad["history"] = [dict(h) for h in self.price_history(ad_id)]
        return ad

    def price_stats(self, **filters: Any) -> dict[str, Any]:
        """Statistiche di prezzo sugli annunci filtrati (stessi filtri dell'elenco).
        I venduti restano esclusi salvo status="sold": il loro prezzo non è più un'offerta disponibile."""
        cond, params = self._ad_filters(**filters)
        if filters.get("status") not in ("sold", "any"):
            cond += " AND a.sold_at IS NULL"
        total = self.db.query_one(f"SELECT COUNT(*) FROM ads a WHERE {cond}", params)[0]
        prices = [r[0] for r in self.db.query(
            f"SELECT a.price FROM ads a WHERE {cond} AND a.price IS NOT NULL AND a.price > 0 ORDER BY a.price",
            params)]
        shipping = self.db.query_one(f"SELECT COUNT(*) FROM ads a WHERE {cond} AND a.shipping = 1", params)[0]
        return {"count": total, "priced": len(prices), "shipping": shipping, **price_summary(prices),
                "published": self.publish_stats(**filters)}

    def publish_stats(self, now: datetime | None = None, **filters: Any) -> dict[str, Any]:
        """Quanti annunci vengono pubblicati (data di pubblicazione di subito.it), venduti compresi.

        La media giornaliera è una stima: si divide per il periodo effettivamente coperto dagli annunci
        raccolti (dal più vecchio della finestra a ora), non per 7 giorni fissi. Così una ricerca molto
        attiva, di cui l'app vede solo le ultime ore, non risulta falsamente "lenta"."""
        now = now or datetime.now()
        cond, params = self._ad_filters(**{**filters, "status": "any" if filters.get("status") in (None, "active")
                                           else filters.get("status")})
        cond += " AND a.hidden = 0" if filters.get("status") != "hidden" else ""
        since30 = (now - timedelta(days=29)).date().isoformat()
        stamps = []
        for (value,) in self.db.query(
                f"SELECT a.published_at FROM ads a WHERE {cond} AND a.published_at >= ?", [*params, since30]):
            try:
                stamps.append(datetime.fromisoformat(str(value).replace("T", " ")))
            except ValueError:
                continue

        def rate(days: int) -> tuple[int, float | None, float]:
            start = now - timedelta(days=days)
            inside = [t for t in stamps if t >= start]
            if not inside:
                return 0, None, 0.0
            covered = max((now - max(min(inside), start)).total_seconds() / 86400, 1 / 24)
            return len(inside), round(len(inside) / covered, 1), round(covered, 2)

        last7, avg7, span7 = rate(7)
        last30, avg30, _ = rate(30)
        today = now.date()
        per_day = []
        for i in range(13, -1, -1):
            day = today - timedelta(days=i)
            per_day.append({"day": day.isoformat(), "count": sum(1 for t in stamps if t.date() == day)})
        return {"today": per_day[-1]["count"], "last7": last7, "avg_day": avg7, "span_days": span7,
                "last30": last30, "avg_day_30": avg30, "per_day": per_day}

    def search_stats(self) -> dict[int, dict[str, Any]]:
        """Per ogni ricerca: totale annunci, nuovi non visti, attivi."""
        rows = self.db.query(
            """SELECT s.id,
                      COUNT(a.id) AS total,
                      SUM(CASE WHEN sa.found_at > COALESCE(s.seen_at, s.created_at) AND a.hidden = 0
                               THEN 1 ELSE 0 END) AS new,
                      SUM(CASE WHEN a.sold_at IS NULL AND a.hidden = 0 THEN 1 ELSE 0 END) AS active
               FROM searches s
               LEFT JOIN search_ads sa ON sa.search_id = s.id
               LEFT JOIN ads a ON a.id = sa.ad_id
               GROUP BY s.id""")
        return {r["id"]: {"total": r["total"], "new": r["new"] or 0, "active": r["active"] or 0} for r in rows}

    def dashboard(self, days: int = 30) -> dict[str, Any]:
        today = now_iso()[:10]
        one = lambda sql, *p: self.db.query_one(sql, p)[0]  # noqa: E731
        since = (datetime.now() - timedelta(days=days - 1)).date().isoformat()
        series = self.db.query(
            """SELECT substr(first_seen_at, 1, 10) AS day, COUNT(*) AS n FROM ads
               WHERE first_seen_at >= ? GROUP BY day ORDER BY day""", (since,))
        return {
            "searches_total": one("SELECT COUNT(*) FROM searches"),
            "searches_active": one("SELECT COUNT(*) FROM searches WHERE enabled = 1"),
            "ads_total": one("SELECT COUNT(*) FROM ads WHERE hidden = 0"),
            "ads_active": one("SELECT COUNT(*) FROM ads WHERE hidden = 0 AND sold_at IS NULL"),
            "new_today": one("SELECT COUNT(*) FROM ads WHERE first_seen_at >= ?", today),
            "sold_total": one("SELECT COUNT(*) FROM ads WHERE sold_at IS NOT NULL"),
            "favorites": one("SELECT COUNT(*) FROM ads WHERE favorite = 1"),
            "per_day": [{"day": r["day"], "count": r["n"]} for r in series],
        }

    def cleanup_ads(self, days: int) -> int:
        """Elimina gli annunci non più visti da `days` giorni (preferiti esclusi)."""
        if days <= 0:
            return 0
        cutoff = (datetime.now() - timedelta(days=int(days))).isoformat(timespec="seconds")
        cur = self.db.execute("DELETE FROM ads WHERE favorite = 0 AND last_seen_at < ?", (cutoff,))
        return cur.rowcount

    # ======================================================================= impostazioni
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)))

    # ======================================================================= eventi
    def add_event(self, time: str, level: str, kind: str, message: str,
                  search_id: int | None, data: dict[str, Any] | None) -> int:
        cur = self.db.execute(
            "INSERT INTO events (time, level, kind, message, search_id, data) VALUES (?, ?, ?, ?, ?, ?)",
            (time, level, kind, message, search_id, json.dumps(data, ensure_ascii=False) if data else None))
        return cur.lastrowid

    def events_after(self, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM (SELECT * FROM events WHERE id > ? ORDER BY id DESC LIMIT ?) "
                             "ORDER BY id", (after_id, limit))
        out = []
        for r in rows:
            e = dict(r)
            e.update(json.loads(e.pop("data") or "{}"))
            out.append(e)
        return out

    def prune_events(self, keep: int = 5000) -> None:
        self.db.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (keep,))


def price_summary(prices: list[int]) -> dict[str, Any]:
    """Minimo, massimo, media e mediana di una lista di prezzi già ordinata (0 = "prezzo da concordare", escluso a monte)."""
    if not prices:
        return {"min": None, "max": None, "mean": None, "median": None, "p25": None, "p75": None}
    n = len(prices)
    mid = n // 2
    median = prices[mid] if n % 2 else (prices[mid - 1] + prices[mid]) / 2

    def quantile(q: float) -> float:  # interpolazione lineare, come statistics.quantiles(method="inclusive")
        pos = (n - 1) * q
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        return round(prices[lo] + (prices[hi] - prices[lo]) * (pos - lo), 2)

    return {"min": prices[0], "max": prices[-1], "mean": round(sum(prices) / n, 2), "median": median,
            "p25": quantile(0.25), "p75": quantile(0.75)}


def _bool(value: bool | None) -> int | None:
    return None if value is None else int(value)
