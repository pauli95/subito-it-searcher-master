"""Protezioni della web app locale.

1. Host consentiti: blocca il "DNS rebinding" (un sito esterno che si fa risolvere su 127.0.0.1).
2. Richieste di modifica da altri siti (CSRF): rifiutate se Origin/Sec-Fetch-Site indicano un'origine
   diversa. Senza questo, una qualsiasi pagina web aperta nel browser potrebbe chiamare le API locali.
3. Accesso dalla rete locale (opzionale): i client non locali devono inserire un PIN; il cookie di
   sessione è firmato con HMAC. Tentativi limitati per indirizzo IP.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "subito_auth"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOGIN_PATHS = {"/login"}


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


class AuthConfig:
    """Stato dell'autenticazione, letto dalle impostazioni a ogni richiesta (costo trascurabile)."""

    def __init__(self, settings, repo):
        self.settings = settings
        self.repo = repo

    @property
    def lan(self) -> bool:
        cfg = self.settings.get("server")
        return bool(cfg.get("lan") and cfg.get("pin"))

    def secret(self) -> bytes:
        value = self.repo.get_setting("auth_secret")
        if not value:
            value = secrets.token_hex(32)
            self.repo.set_setting("auth_secret", value)
        return bytes.fromhex(value)

    def token(self) -> str:
        pin = self.settings.get("server").get("pin", "")
        return hmac.new(self.secret(), f"pin:{pin}".encode(), hashlib.sha256).hexdigest()

    def check_pin(self, pin: str) -> bool:
        expected = self.settings.get("server").get("pin", "")
        return bool(expected) and hmac.compare_digest(str(pin), expected)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth: AuthConfig, trusted_hosts: set[str] | None = None):
        super().__init__(app)
        self.auth = auth
        self.trusted_hosts = trusted_hosts or {"127.0.0.1", "localhost", "[::1]"}

    async def dispatch(self, request: Request, call_next) -> Response:
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        lan = self.auth.lan
        if not lan and host not in self.trusted_hosts:
            return JSONResponse({"detail": "Host non consentito"}, status_code=400)

        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc.lower() != (request.headers.get("host") or "").lower():
                return JSONResponse({"detail": "Richiesta da un altro sito rifiutata"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Richiesta da un altro sito rifiutata"}, status_code=403)

        client = request.client.host if request.client else None
        if lan and not is_loopback(client) and request.url.path not in LOGIN_PATHS:
            cookie = request.cookies.get(COOKIE, "")
            if not hmac.compare_digest(cookie, self.auth.token()):
                if request.url.path.startswith("/api/"):
                    return JSONResponse({"detail": "Accesso richiesto (PIN)"}, status_code=401)
                return RedirectResponse("/login", status_code=303)
        return await call_next(request)


class LoginLimiter:
    """Max 5 tentativi per IP ogni 5 minuti."""

    def __init__(self, attempts: int = 5, window: float = 300):
        self.attempts = attempts
        self.window = window
        self._log: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        log = self._log[ip]
        while log and now - log[0] > self.window:
            log.popleft()
        if len(log) >= self.attempts:
            return False
        log.append(now)
        return True


LOGIN_PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Subito Searcher · Accesso</title>
<style>
:root{{--bg:#0b0e11;--panel:#12171c;--line:#24303a;--text:#d7e0e7;--muted:#7d8b96;--accent:#00e58f;--err:#ff6b6b}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);
font:15px/1.5 ui-monospace,"JetBrains Mono",Consolas,monospace}}
form{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:28px;width:min(340px,calc(100vw - 32px))}}
h1{{font-size:16px;margin:0 0 16px}} h1 span{{color:var(--accent)}}
input{{width:100%;box-sizing:border-box;background:#0b0e11;border:1px solid var(--line);color:var(--text);
padding:10px;border-radius:6px;font:inherit;letter-spacing:4px}}
input:focus{{outline:2px solid var(--accent);outline-offset:1px}}
button{{margin-top:12px;width:100%;padding:10px;border:0;border-radius:6px;background:var(--accent);color:#04120b;
font:inherit;font-weight:700;cursor:pointer}} p{{color:var(--err);min-height:1.5em;margin:10px 0 0}}
</style></head><body><form method="post" action="/login">
<h1><span>&gt;</span> subito-searcher · accesso</h1>
<label for="pin">PIN</label><input id="pin" name="pin" type="password" inputmode="numeric" autocomplete="current-password" autofocus required>
<button type="submit">Entra</button><p>{error}</p></form></body></html>"""


def login_page(error: str = "") -> HTMLResponse:
    import html

    return HTMLResponse(LOGIN_PAGE.format(error=html.escape(error)))
