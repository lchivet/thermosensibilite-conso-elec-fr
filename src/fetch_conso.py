"""
Téléchargement de la consommation électrique française (RTE éCO2mix, via le portail
Open Data Réseaux Énergies / ODRE, opendatasoft).

Dataset "eco2mix-national-cons-def" : pas de temps quart-horaire, données consolidées
puis définitives, disponible depuis janvier 2012 jusqu'à environ J-1.
Documentation : https://odre.opendatasoft.com/explore/dataset/eco2mix-national-cons-def/
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
EXPORT_URL = (
    "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "eco2mix-national-cons-def/exports/csv"
)

FIELDS = [
    "date_heure",
    "date",
    "heure",
    "consommation",
    "prevision_j1",
    "prevision_j",
    "eolien",
    "solaire",
    "nucleaire",
    "hydraulique",
    "gaz",
    "charbon",
    "fioul",
    "bioenergies",
    "pompage",
    "ech_physiques",
    "taux_co2",
]


def fetch_conso(start_date: str, end_date: str, out_path: Path | None = None) -> pd.DataFrame:
    """Télécharge la consommation (et le mix de production) sur [start_date, end_date]."""
    params = {
        "where": f"date_heure >= date'{start_date}' AND date_heure <= date'{end_date}'",
        "select": ",".join(FIELDS),
        "order_by": "date_heure",
        "limit": -1,
    }
    resp = requests.get(EXPORT_URL, params=params, timeout=120)
    resp.raise_for_status()

    tmp_path = out_path or (RAW_DIR / f"conso_{start_date}_{end_date}.csv")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(resp.content)

    df = pd.read_csv(tmp_path, sep=";")
    print(f"[fetch_conso] {len(df):,} lignes téléchargées -> {tmp_path}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Télécharge la conso RTE éCO2mix (national).")
    parser.add_argument("--start", default="2016-01-01", help="Date de début (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="Date de fin (YYYY-MM-DD)")
    args = parser.parse_args()

    fetch_conso(args.start, args.end, RAW_DIR / "conso_national.csv")
