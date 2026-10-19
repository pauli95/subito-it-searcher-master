#!/usr/bin/env python3
"""Rigenera core/resources/geo.json (regioni, province e comuni con gli slug di subito.it).

Uso:  python tools/build_geo.py            (con controllo incrociato ISTAT)
      python tools/build_geo.py --no-istat

Fonti (verificate a ottobre 2026):
- https://hades.subito.it/v1/geo/regions                 -> 20 regioni (key, value, friendly_name)
- https://hades.subito.it/v1/geo/regions/{id}/cities     -> province di subito (key, value, friendly_name,
                                                             short_name, istat)
- https://hades.subito.it/v1/geo/search?key={lettera}    -> ricerca per prefisso, senza limite di risultati:
                                                             26 richieste coprono tutti i comuni
- ISTAT "Elenco comuni italiani" (CSV)                   -> solo controllo incrociato e nomi accentati

Perché subito e non solo ISTAT: gli URL usano le province e gli slug di subito, che non coincidono
sempre con ISTAT (es. province sarde, comuni fusi ancora presenti, omonimi con sigla: "Calliano TN").
La regola slug = nome senza accenti, minuscolo, ogni sequenza non alfanumerica -> "-" coincide
con friendly_name per tutti i 7.911 comuni (verificato).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import string
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.geo import slugify  # noqa: E402
from core.scraper import HEADERS  # noqa: E402

API = "https://hades.subito.it/v1/geo"
ISTAT_CSV = "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv"
OUT = ROOT / "core" / "resources" / "geo.json"


def get_json(session: requests.Session, url: str, **params) -> dict:
    headers = dict(HEADERS, Accept="application/json")
    for attempt in range(3):
        try:
            r = session.get(url, params=params or None, headers=headers, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise SystemExit(f"Errore scaricando {url}: {e}")
            time.sleep(3)
    raise AssertionError


def istat_names() -> dict[str, str]:
    """codice comune ISTAT -> denominazione in italiano (con accenti)."""
    r = requests.get(ISTAT_CSV, timeout=60)
    r.raise_for_status()
    rows = list(csv.reader(io.StringIO(r.content.decode("latin-1")), delimiter=";"))
    header = rows[0]
    i_code = header.index("Codice Comune formato alfanumerico")
    i_name = header.index("Denominazione in italiano")
    return {row[i_code]: row[i_name] for row in rows[1:] if len(row) > i_name}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-istat", action="store_true", help="salta il controllo incrociato ISTAT")
    ap.add_argument("--delay", type=float, default=1.0, help="pausa tra le richieste (s)")
    args = ap.parse_args()
    s = requests.Session()

    regions = sorted(get_json(s, f"{API}/regions")["values"], key=lambda r: r["value"])
    provinces = []
    for reg in regions:
        time.sleep(args.delay)
        for c in get_json(s, f"{API}/regions/{reg['key']}/cities")["values"]:
            # le chiavi delle province sono uniche solo dentro la regione (Padova e Brescia = "2")
            provinces.append({"id": f"{reg['key']}:{c['key']}", "region_id": reg["key"], "name": c["value"],
                              "slug": c["friendly_name"], "code": c.get("short_name"), "istat": c.get("istat")})
    print(f"{len(regions)} regioni, {len(provinces)} province")

    towns: dict[str, dict] = {}
    for letter in string.ascii_lowercase:
        time.sleep(args.delay)
        for x in get_json(s, f"{API}/search", key=letter).get("data", []):
            t = x.get("town")
            if t:
                towns[t["key"]] = {"istat": t["key"], "name": t["value"], "slug": t["friendly_name"],
                                   "province_id": f"{x['region']['key']}:{x['city']['key']}"}
    print(f"{len(towns)} comuni")

    # coerenza: ogni comune deve appartenere a una provincia nota; slug unici per provincia
    prov_ids = {p["id"] for p in provinces}
    orphans = [t for t in towns.values() if t["province_id"] not in prov_ids]
    if orphans:
        raise SystemExit(f"{len(orphans)} comuni con provincia sconosciuta, es. {orphans[:3]}")
    # Solo informativo: dove le province sono state rinumerate (Friuli, Sardegna) il codice
    # del comune non ha più il prefisso della provincia; l'assegnazione resta quella di subito.
    by_id = {p["id"]: p for p in provinces}
    renumbered = sorted({by_id[t["province_id"]]["code"] for t in towns.values()
                         if by_id[t["province_id"]]["istat"] != t["istat"][:3]})
    print(f"province con codici ISTAT rinumerati: {', '.join(renumbered) or 'nessuna'}")
    rule_mismatch = [t for t in towns.values() if slugify(t["name"]) != t["slug"]]
    print(f"slug diversi dalla regola: {len(rule_mismatch)} {[(t['name'], t['slug']) for t in rule_mismatch[:5]]}")

    if not args.no_istat:
        try:
            names = istat_names()
        except requests.RequestException as e:
            print(f"Controllo ISTAT saltato: {e}")
        else:
            accented = 0
            for t in towns.values():
                official = names.get(t["istat"])
                # stesso comune, differenza solo di accenti ("Maiera'" -> "Maierà"): nome ufficiale
                if official and official != t["name"] and slugify(official) == t["slug"]:
                    t["name"] = official
                    accented += 1
            common = set(names) & set(towns)
            print(f"ISTAT: {len(names)} comuni; in comune per codice: {len(common)}; "
                  f"solo subito: {len(set(towns) - set(names))}; solo ISTAT: {len(set(names) - set(towns))}; "
                  f"nomi accentati da ISTAT: {accented}")

    data = {
        "generated": date.today().isoformat(),
        "source": "hades.subito.it/v1/geo (+ nomi ISTAT)",
        "regions": [{"id": r["key"], "name": r["value"], "slug": r["friendly_name"]} for r in regions],
        "provinces": sorted(provinces, key=lambda p: (p["name"])),
        # formato compatto: [istat, nome, slug, id provincia]
        "towns": sorted(([t["istat"], t["name"], t["slug"], t["province_id"]] for t in towns.values()),
                        key=lambda t: t[2]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Scritto {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
