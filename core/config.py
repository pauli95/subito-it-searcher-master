"""Percorsi e impostazioni dell'applicazione (salvate nella tabella `settings`)."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .repo import Repository

PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Paths:
    """`legacy` contiene i file della vecchia versione; `data` il database."""

    legacy: Path
    data: Path

    @classmethod
    def default(cls) -> "Paths":
        base = Path(os.environ["SUBITO_DATA_DIR"]) if os.environ.get("SUBITO_DATA_DIR") else None
        return cls(legacy=base or PROJECT_DIR, data=(base or PROJECT_DIR) / "data")

    @property
    def db(self) -> Path:
        return self.data / "subito.db"

    @property
    def backups(self) -> Path:
        return self.data / "backups"

    @property
    def log(self) -> Path:
        return self.data / "subito-searcher.log"

    # file storici (solo lettura, per l'import)
    @property
    def legacy_searches(self) -> Path:
        return self.legacy / "searches.tracked"

    @property
    def legacy_telegram(self) -> Path:
        return self.legacy / "telegram_api_credentials"

    @property
    def legacy_ntfy(self) -> Path:
        return self.legacy / "ntfy_config"

    @property
    def legacy_settings(self) -> Path:  # versione web precedente (file JSON)
        return self.legacy / "settings.json"

    @property
    def legacy_state(self) -> Path:
        return self.legacy / "app_state.json"


DEFAULTS: dict[str, Any] = {
    "monitor": {
        "interval_sec": 300,       # intervallo predefinito per ricerca (min 60)
        "active_from": "00:00",    # fascia globale (uguali = sempre attivo)
        "active_to": "00:00",
        "autostart": False,
        "jitter_sec": 8,           # pausa casuale massima tra due richieste
        "min_gap_sec": 3,          # pausa minima tra due richieste
        "first_run_silent": True,  # primo controllo dopo l'avvio senza notifiche
        "sync": True,              # tutte le ricerche nello stesso giro, con un unico conto alla rovescia
    },
    "notifications": {
        "windows": True,
        "telegram": True,
        "ntfy": True,
        "browser": False,
        "sound": False,
        "dnd": False,              # non disturbare
        "group_threshold": 5,      # oltre N annunci insieme: un solo messaggio riassuntivo
    },
    "telegram": {"token": "", "chatid": ""},
    "ntfy": {"server": "", "topic": ""},
    "maintenance": {"cleanup_days": 0},  # 0 = non cancellare mai
    "server": {"lan": False, "pin": ""},  # accesso dalla rete locale (richiede riavvio)
}


def _merge(defaults: dict[str, Any], data: dict[str, Any] | None) -> dict[str, Any]:
    out = deepcopy(defaults)
    for key, value in (data or {}).items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Settings:
    """Sezioni di impostazioni con valori predefiniti."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def get(self, section: str) -> dict[str, Any]:
        return _merge(DEFAULTS.get(section, {}), self.repo.get_setting(section, {}))

    def update(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        current = self.repo.get_setting(section, {}) or {}
        current.update(values)
        self.repo.set_setting(section, current)
        return self.get(section)

    def all(self) -> dict[str, dict[str, Any]]:
        return {section: self.get(section) for section in DEFAULTS}


class SettingsError(ValueError):
    """Valore di impostazione non valido (messaggio per l'utente)."""


def _bool(values: dict[str, Any], key: str) -> bool:
    value = values[key]
    if not isinstance(value, bool):
        raise SettingsError(f"{key}: atteso vero/falso")
    return value


def _int(values: dict[str, Any], key: str, lo: int, hi: int) -> int:
    try:
        number = int(values[key])
    except (TypeError, ValueError) as e:
        raise SettingsError(f"{key}: numero non valido") from e
    if not lo <= number <= hi:
        raise SettingsError(f"{key}: deve essere tra {lo} e {hi}")
    return number


def _str(values: dict[str, Any], key: str, max_len: int = 200) -> str:
    value = values[key]
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > max_len:
        raise SettingsError(f"{key}: testo non valido")
    return value.strip()


def clean_settings(section: str, values: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Valida i campi inviati per una sezione; restituisce solo quelli da salvare."""
    import re

    from .timeutil import format_hour

    if section not in DEFAULTS:
        raise SettingsError(f"Sezione sconosciuta: {section}")
    out: dict[str, Any] = {}
    unknown = set(values) - set(DEFAULTS[section]) - {"clear_token"}
    if unknown:
        raise SettingsError(f"Campi sconosciuti: {', '.join(sorted(unknown))}")

    for key in values:
        if key == "clear_token":
            continue
        default = DEFAULTS[section][key]
        if section == "monitor" and key in ("active_from", "active_to"):
            try:
                out[key] = format_hour(values[key])
            except ValueError as e:
                raise SettingsError(str(e)) from e
        elif isinstance(default, bool):
            out[key] = _bool(values, key)
        elif isinstance(default, int):
            limits = {"interval_sec": (60, 86400), "jitter_sec": (0, 120), "min_gap_sec": (0, 60),
                      "group_threshold": (1, 100), "cleanup_days": (0, 3650)}[key]
            out[key] = _int(values, key, *limits)
        else:
            out[key] = _str(values, key)

    if section == "telegram":
        if values.get("clear_token"):
            out["token"] = ""
        elif not out.get("token"):
            out.pop("token", None)  # campo password vuoto = lascia invariato
        elif not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", out["token"]):
            raise SettingsError("Token Telegram non valido (formato atteso 123456789:ABC...)")
    if section == "ntfy":
        if out.get("server") and not re.fullmatch(r"https?://[^\s/]+(/[^\s]*)?", out["server"]):
            raise SettingsError("Server ntfy: indirizzo non valido (es. https://ntfy.sh)")
        if out.get("topic") and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", out["topic"]):
            raise SettingsError("Topic ntfy: solo lettere, numeri, - e _ (max 64)")
    if section == "server":
        pin = out.get("pin", current.get("pin", ""))
        if pin and not re.fullmatch(r"\d{4,12}", pin):
            raise SettingsError("PIN: da 4 a 12 cifre")
        if out.get("lan", current.get("lan")) and not pin:
            raise SettingsError("Per l'accesso dalla rete locale serve un PIN")
    return out
