"""Database SQLite: connessione condivisa thread-safe e migrazioni dello schema."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Ogni elemento è una migrazione; la posizione (1-based) è il numero di versione.
# Non modificare mai una migrazione già rilasciata: aggiungerne una nuova in coda.
MIGRATIONS: list[str] = [
    # 1 — schema iniziale
    """
    CREATE TABLE searches (
        id                 INTEGER PRIMARY KEY,
        name               TEXT NOT NULL UNIQUE COLLATE NOCASE,
        url                TEXT NOT NULL,
        params             TEXT,                 -- JSON dei parametri del form (NULL = solo URL)
        min_price          INTEGER,              -- filtro locale
        max_price          INTEGER,
        exclude_words      TEXT NOT NULL DEFAULT '[]',  -- JSON list
        enabled            INTEGER NOT NULL DEFAULT 1,
        interval_sec       INTEGER,              -- NULL = intervallo globale
        active_from        TEXT,                 -- HH:MM, NULL = sempre
        active_to          TEXT,
        notify_new         INTEGER NOT NULL DEFAULT 1,
        notify_price_drop  INTEGER NOT NULL DEFAULT 0,
        notify_max_price   INTEGER,              -- notifica solo sotto questa soglia
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL,
        seen_at            TEXT,                 -- annunci trovati dopo questo istante = "nuovi"
        last_run_at        TEXT,
        last_ok_at         TEXT,
        last_error         TEXT,
        consecutive_errors INTEGER NOT NULL DEFAULT 0,
        last_found         INTEGER,
        last_new           INTEGER
    );

    CREATE TABLE ads (
        id             INTEGER PRIMARY KEY,
        ad_key         TEXT NOT NULL UNIQUE,     -- id numerico subito (dedup tra ricerche)
        urn            TEXT,
        link           TEXT NOT NULL,
        title          TEXT NOT NULL,
        price          INTEGER,                  -- NULL = prezzo sconosciuto
        location       TEXT,
        town           TEXT,
        province       TEXT,
        region         TEXT,
        category       TEXT,
        ad_type        TEXT,
        shipping       INTEGER,                  -- NULL = informazione non disponibile
        company        INTEGER,
        image          TEXT,
        published_at   TEXT,
        first_seen_at  TEXT NOT NULL,
        last_seen_at   TEXT NOT NULL,
        sold_at        TEXT,
        favorite       INTEGER NOT NULL DEFAULT 0,
        hidden         INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_ads_first_seen ON ads(first_seen_at);

    CREATE TABLE search_ads (
        search_id  INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
        ad_id      INTEGER NOT NULL REFERENCES ads(id) ON DELETE CASCADE,
        found_at   TEXT NOT NULL,
        PRIMARY KEY (search_id, ad_id)
    );
    CREATE INDEX ix_search_ads_ad ON search_ads(ad_id);

    CREATE TABLE price_history (
        id        INTEGER PRIMARY KEY,
        ad_id     INTEGER NOT NULL REFERENCES ads(id) ON DELETE CASCADE,
        price     INTEGER,
        seen_at   TEXT NOT NULL
    );
    CREATE INDEX ix_price_history_ad ON price_history(ad_id, seen_at);

    CREATE TABLE events (
        id         INTEGER PRIMARY KEY,
        time       TEXT NOT NULL,
        level      TEXT NOT NULL,
        kind       TEXT NOT NULL,
        message    TEXT NOT NULL,
        search_id  INTEGER,
        data       TEXT
    );
    CREATE INDEX ix_events_time ON events(time);

    CREATE TABLE settings (
        key    TEXT PRIMARY KEY,
        value  TEXT NOT NULL                     -- JSON
    );
    """,
]


class Database:
    """Una connessione SQLite condivisa, serializzata da un lock.

    Il carico è minimo (un utente, poche scritture al minuto), quindi una sola
    connessione protetta da RLock è più semplice e sicura di un pool.
    Ogni `transaction()` è atomica: o tutte le scritture o nessuna.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self.migrate()

    # --- schema -------------------------------------------------------------
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        with self._lock:
            current = self.schema_version()
            for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
                # executescript fa un COMMIT implicito: BEGIN/COMMIT espliciti nello script.
                self._conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")

    # --- accesso -------------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: Any = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Any = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        """Singola istruzione in autocommit (già atomica)."""
        with self._lock:
            return self._conn.execute(sql, params)

    def backup_to(self, dest: Path | str) -> None:
        """Copia consistente del database (API di backup di SQLite)."""
        with self._lock:
            target = sqlite3.connect(str(dest))
            try:
                self._conn.backup(target)
            finally:
                target.close()

    @staticmethod
    def check_backup(path: Path | str) -> int:
        """Verifica che il file sia un database di questa app; restituisce la versione dello schema."""
        try:
            src = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        except sqlite3.Error as e:
            raise ValueError(f"File non leggibile: {e}") from e
        try:
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Il database è danneggiato (integrity_check fallito)")
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            missing = {"searches", "ads", "search_ads", "price_history", "settings"} - tables
            if missing:
                raise ValueError(f"Non è un backup di Subito Searcher (mancano: {', '.join(sorted(missing))})")
            version = src.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise ValueError("Backup creato da una versione più recente dell'app")
            return version
        except sqlite3.DatabaseError as e:
            raise ValueError(f"Non è un database SQLite valido: {e}") from e
        finally:
            src.close()

    def restore_from(self, path: Path | str) -> None:
        """Sostituisce il contenuto del database con quello del backup (stessa connessione)."""
        self.check_backup(path)
        with self._lock:
            src = sqlite3.connect(str(path))
            try:
                src.backup(self._conn)
            finally:
                src.close()
            self._conn.execute("PRAGMA foreign_keys = ON")
            self.migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
