#!/usr/bin/env python3
"""Avvia Subito Searcher su http://127.0.0.1:8000.

Opzioni:  --port 8080   porta diversa
          --open        apre il browser all'avvio
Di default il server ascolta solo su 127.0.0.1. L'accesso dalla rete locale (telefono) si abilita
dalle impostazioni, con un PIN obbligatorio; serve riavviare il server.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser

import uvicorn

from core import App
from webapp.main import create_app

LOCAL = "127.0.0.1"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((LOCAL, port)) == 0


def lan_addresses() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({i[4][0] for i in infos if not i[4][0].startswith("127.")})


def main() -> None:
    # con pythonw.exe (avvio automatico con Windows) non c'è console: stdout/stderr sono None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Interfaccia web di Subito Searcher")
    parser.add_argument("--port", type=int, default=8000, help="porta (default 8000)")
    parser.add_argument("--open", action="store_true", help="apri il browser all'avvio")
    args = parser.parse_args()
    url = f"http://{LOCAL}:{args.port}"

    if port_in_use(args.port):
        print(f"La porta {args.port} è già in uso: probabilmente l'app è già avviata su {url}")
        if args.open:
            webbrowser.open(url)
        return

    core = App()
    server_cfg = core.settings.get("server")
    lan = bool(server_cfg.get("lan") and server_cfg.get("pin"))
    host = "0.0.0.0" if lan else LOCAL

    print(f"Subito Searcher in ascolto su {url}  (CTRL+C per chiudere)")
    print(f"Documentazione API: {url}/docs")
    if lan:
        for ip in lan_addresses():
            print(f"Accesso dalla rete locale (con PIN): http://{ip}:{args.port}")
    if args.open:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    app = create_app(core)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=args.port, log_level="warning",
                                           timeout_graceful_shutdown=5))
    app.state.shutdown = lambda: setattr(server, "should_exit", True)  # pulsante "Chiudi l'app"
    server.run()
    core.close()


if __name__ == "__main__":
    main()
