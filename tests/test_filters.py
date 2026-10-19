from __future__ import annotations

import pytest

from core.filters import excluded_by, normalize, parse_words, passes_filters, price_in_range


@pytest.mark.parametrize("price, lo, hi, expected", [
    (100, None, None, True),
    (100, 100, 200, True),       # estremi inclusi
    (200, 100, 200, True),
    (99, 100, None, False),
    (201, None, 200, False),
    (None, 100, 200, True),      # prezzo sconosciuto passa sempre (come l'originale)
    (0, 0, None, True),
])
def test_price_in_range(price, lo, hi, expected):
    assert price_in_range(price, lo, hi) is expected


def test_normalize():
    assert normalize("Perché ÀRIA") == "perche aria"


def test_parse_words():
    assert parse_words("rotto, ricambi;  cover \n") == ["rotto", "ricambi", "cover"]
    assert parse_words(["Rotto", "rotto", " ", "non  funzionante"]) == ["Rotto", "non funzionante"]
    assert parse_words(None) == []


@pytest.mark.parametrize("title, words, expected", [
    ("iPhone 12 ROTTO schermo", ["rotto"], "rotto"),
    ("iPhone 12 rotta", ["rott"], "rott"),                 # prefisso di parola
    ("Discovery channel DVD", ["cover"], None),            # non a metà parola
    ("Cover per iPhone", ["cover"], "cover"),
    ("Telefono non funzionante", ["non funzionante"], "non funzionante"),
    ("Città perfetta", ["citta"], "citta"),                # accenti ignorati
    ("iPhone 13", [], None),
    ("Ricambi iPhone", ["rotto", "ricambi"], "ricambi"),
])
def test_excluded_by(title, words, expected):
    assert excluded_by(title, words) == expected


def test_passes_filters():
    assert passes_filters("iPhone 13", 300, 100, 500, ["rotto"])
    assert not passes_filters("iPhone 13 rotto", 300, 100, 500, ["rotto"])
    assert not passes_filters("iPhone 13", 50, 100, 500, [])
