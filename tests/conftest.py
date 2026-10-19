from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_NEXT = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


@pytest.fixture
def page_html() -> str:
    return (FIXTURES / "search_iphone_veneto.html").read_text(encoding="utf-8")


@pytest.fixture
def next_data(page_html: str) -> dict[str, Any]:
    return json.loads(_NEXT.search(page_html).group(1))


def to_html(data: dict[str, Any]) -> str:
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'


@pytest.fixture
def make_html(next_data):
    """Costruisce una pagina modificando una copia dei dati reali."""
    def build(mutate) -> str:
        data = copy.deepcopy(next_data)
        mutate(data)
        return to_html(data)
    return build


def items_of(data: dict[str, Any]) -> list[dict[str, Any]]:
    return data["props"]["pageProps"]["initialState"]["items"]["originalList"]
