"""Invio notifiche: toast Windows, Telegram, ntfy; avvisi per il browser (notifica + suono) via eventi."""

from __future__ import annotations

import base64
import html
import logging
import platform
import threading
from collections.abc import Callable
from typing import Any

import requests

from .config import Settings
from .models import ScrapedAd

logger = logging.getLogger("subito")
TIMEOUT = 15


class NotifyError(Exception):
    pass


# ============================================================================ Windows

def _load_windows_backend() -> tuple[str | None, Callable[[str, str], Any] | None]:
    """win11toast se disponibile, altrimenti plyer, altrimenti nessuna notifica (silenzioso)."""
    if platform.system() != "Windows":
        return None, None
    try:
        from win11toast import notify as win11_notify

        # app_id di default: un id personalizzato non registrato in Windows non mostra nulla.
        return "win11toast", lambda title, body: win11_notify(title, body)
    except Exception:
        pass
    try:
        from plyer import notification

        return "plyer", lambda title, body: notification.notify(title=title, message=body,
                                                                 app_name="Subito Searcher", timeout=10)
    except Exception:
        pass
    return None, None


WINDOWS_BACKEND, _windows_show = _load_windows_backend()


def windows_available() -> bool:
    return _windows_show is not None


def send_windows(title: str, body: str) -> None:
    if not _windows_show:
        raise NotifyError("Notifiche Windows non disponibili (installa win11toast)")
    show = _windows_show

    def run() -> None:  # in un thread: alcuni backend bloccano per qualche secondo
        try:
            show(title, body)
        except Exception as e:
            logger.warning("Notifica Windows fallita: %s", e)

    threading.Thread(target=run, daemon=True).start()


# ============================================================================ Telegram

def telegram_configured(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("token")) and bool(cfg.get("chatid"))


def send_telegram(cfg: dict[str, Any], text_html: str) -> None:
    """parse_mode HTML: il testo va già escapato con html.escape (vedi format_*)."""
    if not telegram_configured(cfg):
        raise NotifyError("Telegram non configurato (token e chat id)")
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    try:
        resp = requests.get(url, params={
            "chat_id": cfg["chatid"], "text": text_html, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        # non includere l'eccezione: il suo testo contiene l'URL con il token
        raise NotifyError(f"Telegram non raggiungibile ({type(e).__name__})") from None
    if resp.status_code != 200:
        try:
            desc = resp.json().get("description", "")
        except ValueError:
            desc = ""
        raise NotifyError(f"Telegram HTTP {resp.status_code}: {desc}".rstrip(": "))


# ============================================================================ ntfy

def ntfy_configured(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("server")) and bool(cfg.get("topic"))


def _rfc2047(text: str) -> str:
    """Gli header HTTP accettano solo latin-1: ntfy supporta la codifica RFC 2047."""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


def send_ntfy(cfg: dict[str, Any], message: str, title: str | None = None, click: str | None = None) -> None:
    if not ntfy_configured(cfg):
        raise NotifyError("ntfy non configurato (server e topic)")
    url = f"{cfg['server'].rstrip('/')}/{cfg['topic']}"
    headers = {}
    if title:
        headers["Title"] = _rfc2047(title)
    if click:
        headers["Click"] = click
    try:
        resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise NotifyError(f"ntfy non raggiungibile ({type(e).__name__})") from e
    if resp.status_code >= 400:
        raise NotifyError(f"ntfy HTTP {resp.status_code}: {resp.text[:200]}")


# ============================================================================ formattazione

def format_price(price: int | None) -> str:
    return "prezzo n.d." if price is None else f"€ {price:,}".replace(",", ".")


def _ship(ad: ScrapedAd) -> str:
    return " · spedizione disponibile" if ad.shipping else ""


def format_text(ad: ScrapedAd, old_price: int | None = None) -> str:
    price = format_price(ad.price)
    if old_price is not None:
        price = f"{price} (prima {format_price(old_price)})"
    return f"{ad.title}\n{price}{_ship(ad)}\n{ad.location}\n{ad.link}"


def format_html(ad: ScrapedAd, search_name: str, old_price: int | None = None) -> str:
    e = html.escape
    price = e(format_price(ad.price))
    if old_price is not None:
        price = f"📉 {price} <s>{e(format_price(old_price))}</s>"
    return (f"<i>{e(search_name)}</i>\n<b>{e(ad.title)}</b>\n{price}{e(_ship(ad))}\n"
            f"{e(ad.location)}\n<a href=\"{e(ad.link, quote=True)}\">{e(ad.link)}</a>")


def format_summary_html(search_name: str, items: list[tuple[ScrapedAd, int | None]], label: str) -> str:
    """Un unico messaggio per molti annunci (anti-flood)."""
    e = html.escape
    lines = [f"<b>{e(search_name)}</b>: {len(items)} {e(label)}"]
    for ad, old in items[:15]:
        price = format_price(ad.price) + (f" (prima {format_price(old)})" if old is not None else "")
        lines.append(f"• <a href=\"{e(ad.link, quote=True)}\">{e(ad.title)}</a> — {e(price)}")
    if len(items) > 15:
        lines.append(f"…e altri {len(items) - 15}")
    return "\n".join(lines)


# ============================================================================ servizio

class Notifier:
    """Invia le notifiche secondo le impostazioni salvate.

    `overrides` permette alla CLI di disattivare un canale solo per l'esecuzione corrente
    (--tgoff, --notifyoff, --ntfyoff) senza toccare le impostazioni salvate.
    """

    def __init__(self, settings: Settings, events, overrides: dict[str, bool] | None = None):
        self.settings = settings
        self.events = events
        self.overrides = overrides or {}

    def enabled(self, channel: str) -> bool:
        if self.overrides.get(channel) is False:
            return False
        return bool(self.settings.get("notifications").get(channel, True))

    def channels_status(self) -> dict[str, dict[str, Any]]:
        return {
            "windows": {"enabled": self.enabled("windows"), "available": windows_available(),
                        "backend": WINDOWS_BACKEND},
            "telegram": {"enabled": self.enabled("telegram"),
                         "configured": telegram_configured(self.settings.get("telegram"))},
            "ntfy": {"enabled": self.enabled("ntfy"), "configured": ntfy_configured(self.settings.get("ntfy"))},
            "browser": {"enabled": self.enabled("browser")},
            "sound": {"enabled": self.enabled("sound")},
        }

    def notify(self, search_name: str, search_id: int | None,
               new_ads: list[ScrapedAd], price_drops: list[tuple[ScrapedAd, int]]) -> None:
        if not new_ads and not price_drops:
            return
        cfg = self.settings.get("notifications")
        if cfg.get("dnd"):
            self.events.info(f"'{search_name}': notifiche sospese (non disturbare)", kind="notify",
                             search_id=search_id)
            return
        group_at = max(1, int(cfg.get("group_threshold") or 5))
        batches: list[tuple[str, list[tuple[ScrapedAd, int | None]]]] = []
        if new_ads:
            batches.append(("nuovi annunci", [(a, None) for a in new_ads]))
        if price_drops:
            batches.append(("ribassi di prezzo", [(a, old) for a, old in price_drops]))

        self._browser_alert(search_name, search_id, batches)

        if self.enabled("windows") and windows_available():
            parts = [f"{len(items)} {label}" for label, items in batches]
            try:
                send_windows("Subito Searcher", f"{search_name}: " + ", ".join(parts))
            except NotifyError as e:
                self.events.warning(str(e), kind="notify", search_id=search_id)

        tg = self.settings.get("telegram")
        if self.enabled("telegram") and telegram_configured(tg):
            self._send_batches("Telegram", search_name, search_id, batches, group_at,
                               single=lambda ad, old: send_telegram(tg, format_html(ad, search_name, old)),
                               grouped=lambda label, items: send_telegram(
                                   tg, format_summary_html(search_name, items, label)))

        nt = self.settings.get("ntfy")
        if self.enabled("ntfy") and ntfy_configured(nt):
            self._send_batches("ntfy", search_name, search_id, batches, group_at,
                               single=lambda ad, old: send_ntfy(nt, format_text(ad, old),
                                                                title=f"Subito: {search_name}", click=ad.link),
                               grouped=lambda label, items: send_ntfy(
                                   nt, "\n".join(f"• {a.title} — {format_price(a.price)}" for a, _ in items[:15]),
                                   title=f"Subito: {search_name} — {len(items)} {label}"))

    def _browser_alert(self, search_name: str, search_id: int | None,
                       batches: list[tuple[str, list[tuple[ScrapedAd, int | None]]]]) -> None:
        """Notifica del browser e suono: li mostra la pagina aperta quando riceve questo evento (SSE)."""
        browser, sound = self.enabled("browser"), self.enabled("sound")
        if not browser and not sound:
            return
        parts = [f"{len(items)} {label}" for label, items in batches]
        first = batches[0][1][0][0]
        total = sum(len(items) for _, items in batches)
        body = (f"{first.title} — {format_price(first.price)}" if total == 1
                else "\n".join(f"• {a.title} — {format_price(a.price)}" for _, items in batches for a, _ in items[:3]))
        self.events.info(f"'{search_name}': avviso nel browser ({', '.join(parts)})", kind="notify",
                         search_id=search_id,
                         alert={"title": f"{search_name}: {', '.join(parts)}", "body": body[:300],
                                "link": first.link if total == 1 else None,
                                "browser": browser, "sound": sound})

    def _send_batches(self, channel, search_name, search_id, batches, group_at, single, grouped) -> None:
        sent = 0
        try:
            for label, items in batches:
                if len(items) >= group_at:
                    grouped(label, items)
                    sent += 1
                else:
                    for ad, old in items:
                        single(ad, old)
                        sent += 1
        except NotifyError as e:
            self.events.error(f"{channel}: {e}", kind="notify", search_id=search_id)
        if sent:
            self.events.info(f"{channel}: inviati {sent} messaggi per '{search_name}'", kind="notify",
                             search_id=search_id)

    def test(self, channel: str) -> None:
        """Messaggio di prova (anche se il canale è disattivato)."""
        msg = "Messaggio di prova da Subito Searcher ✅"
        if channel == "telegram":
            send_telegram(self.settings.get("telegram"), html.escape(msg))
        elif channel == "ntfy":
            send_ntfy(self.settings.get("ntfy"), msg, title="Subito Searcher - prova")
        elif channel == "windows":
            send_windows("Subito Searcher", msg)
        elif channel in ("browser", "sound"):  # percorso completo: evento -> SSE -> pagina aperta
            self.events.info(f"Avviso di prova ({channel})", kind="notify",
                             alert={"title": "Subito Searcher", "body": msg, "link": None,
                                    "browser": channel == "browser", "sound": channel == "sound"})
        else:
            raise NotifyError(f"Canale sconosciuto: {channel}")
