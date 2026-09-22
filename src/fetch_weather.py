"""
Téléchargement de températures horaires historiques (Open-Meteo Historical Weather API,
gratuit, sans clé) pour un panier de villes françaises, puis calcul d'une température
"France" proxy par moyenne pondérée par la population régionale.

Limite assumée : une vraie thermosensibilité RTE utilise un maillage de ~32 stations
Météo-France pondérées par la consommation régionale. Ici on approxime avec 10 grandes
villes et des poids de population par région (ordre de grandeur INSEE). C'est une
simplification à assumer explicitement dans les conclusions.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# (latitude, longitude, poids ~ population de la région rattachée)
CITIES: dict[str, tuple[float, float, float]] = {
    "Paris": (48.8566, 2.3522, 0.19),
    "Lyon": (45.7640, 4.8357, 0.13),
    "Marseille": (43.2965, 5.3698, 0.08),
    "Toulouse": (43.6047, 1.4442, 0.09),
    "Lille": (50.6292, 3.0573, 0.09),
    "Strasbourg": (48.5734, 7.7521, 0.085),
    "Bordeaux": (44.8378, -0.5792, 0.09),
    "Nantes": (47.2184, -1.5536, 0.06),
    "Rennes": (48.1173, -1.6778, 0.05),
    "Dijon": (47.3220, 5.0415, 0.045),
    "Montpellier": (43.6108, 3.8767, 0.06),
}


def fetch_city_temperature(city: str, lat: float, lon: float, start_date: str, end_date: str) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "Europe/Paris",
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    df = pd.DataFrame(
        {
            "date_heure": data["hourly"]["time"],
            "temperature": data["hourly"]["temperature_2m"],
        }
    )
    df["ville"] = city
    return df


def fetch_weather(start_date: str, end_date: str, out_path: Path | None = None) -> pd.DataFrame:
    frames = []
    for city, (lat, lon, weight) in CITIES.items():
        print(f"[fetch_weather] {city}...")
        df = fetch_city_temperature(city, lat, lon, start_date, end_date)
        df["poids"] = weight
        frames.append(df)
    all_df = pd.concat(frames, ignore_index=True)

    out_path = out_path or (RAW_DIR / "weather_cities.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(out_path, index=False)
    print(f"[fetch_weather] {len(all_df):,} lignes -> {out_path}")
    return all_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Télécharge les températures horaires (Open-Meteo).")
    parser.add_argument("--start", default="2016-01-01", help="Date de début (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="Date de fin (YYYY-MM-DD)")
    args = parser.parse_args()

    fetch_weather(args.start, args.end)
