"""Avvio automatico all'accesso a Windows.

Crea uno script .vbs nella cartella "Esecuzione automatica" dell'utente
(%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup): avvia il server in background,
senza finestra, con il Python in uso (quello del virtualenv se l'app è partita da avvia.bat).
Niente registro di sistema né privilegi di amministratore: per disattivarlo basta eliminare il file.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from .config import PROJECT_DIR

FILE_NAME = "Subito Searcher.vbs"


class AutostartError(RuntimeError):
    pass


def supported() -> bool:
    return platform.system() == "Windows"


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise AutostartError("Cartella APPDATA non trovata")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _pythonw(python: Path) -> Path:
    """pythonw.exe accanto a python.exe evita la finestra della console."""
    candidate = python.with_name("pythonw.exe")
    return candidate if candidate.exists() else python


def script_text(python: Path, server: Path) -> str:
    def vbs(s: str) -> str:  # stringa VBScript tra virgolette doppie, con le virgolette interne raddoppiate
        return '"' + s.replace('"', '""') + '"'

    command = f'"{_pythonw(python)}" "{server}"'
    return ("' Creato da Subito Searcher: avvia il server all'accesso a Windows.\r\n"
            "' Per disattivare l'avvio automatico elimina questo file (o usa Impostazioni nell'app).\r\n"
            'Set shell = CreateObject("WScript.Shell")\r\n'
            f"shell.CurrentDirectory = {vbs(str(server.parent))}\r\n"
            f"shell.Run {vbs(command)}, 0, False\r\n")


class Autostart:
    def __init__(self, folder: Path | None = None, python: Path | None = None, server: Path | None = None):
        self._folder = folder
        self.python = python or Path(sys.executable)
        self.server = server or PROJECT_DIR / "server.py"

    @property
    def path(self) -> Path:
        return (self._folder or startup_dir()) / FILE_NAME

    def status(self) -> dict[str, object]:
        if not supported() and self._folder is None:
            return {"supported": False, "enabled": False, "path": None}
        try:
            path = self.path
        except AutostartError:
            return {"supported": False, "enabled": False, "path": None}
        return {"supported": True, "enabled": path.exists(), "path": str(path)}

    def enable(self) -> None:
        if not supported() and self._folder is None:
            raise AutostartError("L'avvio automatico è disponibile solo su Windows")
        path = self.path
        if not path.parent.is_dir():
            raise AutostartError(f"Cartella di esecuzione automatica non trovata: {path.parent}")
        # VBScript legge i file nella codifica ANSI di sistema: mbcs = codepage corrente di Windows
        encoding = "mbcs" if supported() else "utf-8"
        try:
            path.write_text(script_text(self.python, self.server), encoding=encoding, newline="")
        except (OSError, UnicodeEncodeError) as e:
            raise AutostartError(f"Impossibile creare {path.name}: {e}") from e

    def disable(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as e:
            raise AutostartError(f"Impossibile rimuovere {FILE_NAME}: {e}") from e
