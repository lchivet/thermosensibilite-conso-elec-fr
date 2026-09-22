"""
Téléchargement du prix spot day-ahead France (ENTSO-E Transparency Platform, API REST).

Nécessite une clé API gratuite ENTSO-E, fournie via la variable d'environnement
ENTSOE_API_KEY (jamais écrite dans un fichier du dépôt) :
  PowerShell : $env:ENTSOE_API_KEY = "votre_clé"
  bash       : export ENTSOE_API_KEY=votre_clé

L'API limite les requêtes de prix day-ahead à une fenêtre d'un an environ : ce script
interroge donc année par année et concatène le résultat.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
API_URL = "https://web-api.tp.entsoe.eu/api"
DOMAIN_FR = "10YFR-RTE------C"
NS = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}


def _parse_document(xml_bytes: bytes) -> pd.DataFrame:
    root = ET.fromstring(xml_bytes)
    if root.tag.endswith("Acknowledgement_MarketDocument"):
        reason = root.find(".//ns:text", NS)
        msg = reason.text if reason is not None else "réponse d'erreur ENTSO-E sans détail"
        raise RuntimeError(f"ENTSO-E a renvoyé une erreur : {msg}")

    rows = []
    for ts in root.findall("ns:TimeSeries", NS):
        for period in ts.findall("ns:Period", NS):
            start = pd.Timestamp(period.find("ns:timeInterval/ns:start", NS).text)
            resolution = period.find("ns:resolution", NS).text
            step = pd.Timedelta(hours=1) if resolution == "PT60M" else pd.Timedelta(minutes=15)

            points = {}
            for point in period.findall("ns:Point", NS):
                position = int(point.find("ns:position", NS).text)
                price = float(point.find("ns:price.amount", NS).text)
                points[position] = price

            if not points:
                continue
            max_position = max(points)
            last_price = None
            for position in range(1, max_position + 1):
                if position in points:
                    last_price = points[position]
                rows.append({"date_heure": start + (position - 1) * step, "prix_eur_mwh": last_price})

    return pd.DataFrame(rows)


def fetch_year(api_key: str, year: int) -> pd.DataFrame:
    params = {
        "securityToken": api_key,
        "documentType": "A44",
        "in_Domain": DOMAIN_FR,
        "out_Domain": DOMAIN_FR,
        "periodStart": f"{year}01010000",
        "periodEnd": f"{year + 1}01010000",
    }
    resp = requests.get(API_URL, params=params, timeout=60)
    resp.raise_for_status()
    return _parse_document(resp.content)


def fetch_day_ahead_prices(start_year: int, end_year: int, out_path: Path | None = None) -> pd.DataFrame:
    api_key = os.environ.get("ENTSOE_API_KEY")
    if not api_key:
        print(
            "[fetch_price] ENTSOE_API_KEY non défini. Voir l'en-tête de src/fetch_price.py.",
            file=sys.stderr,
        )
        sys.exit(1)

    frames = []
    for year in range(start_year, end_year + 1):
        print(f"[fetch_price] {year}...")
        try:
            df_year = fetch_year(api_key, year)
        except RuntimeError as exc:
            print(f"[fetch_price]   -> {exc} (année ignorée)", file=sys.stderr)
            continue
        frames.append(df_year)
        time.sleep(1)  # ménager l'API

    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="date_heure").sort_values("date_heure")

    out_path = out_path or (RAW_DIR / "prix_day_ahead_fr.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"[fetch_price] {len(df):,} lignes -> {out_path}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Télécharge le prix spot day-ahead France (ENTSO-E).")
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()

    fetch_day_ahead_prices(args.start_year, args.end_year)
