"""
Construit le dataset journalier conso / température / calendrier utilisé pour la
modélisation de la thermosensibilité.

Entrées : data/raw/conso_national.csv, data/raw/weather_cities.csv
Sortie  : data/processed/daily_dataset.csv
"""
from __future__ import annotations

from pathlib import Path

import holidays
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

HEATING_BASE_TEMP = 18.0  # °C : base standard des degrés-jours de chauffe (DJU)
COOLING_BASE_TEMP = 24.0  # °C : seuil au-delà duquel la clim tire sur le réseau


def load_daily_conso() -> pd.DataFrame:
    df = pd.read_csv(RAW_DIR / "conso_national.csv", sep=";")
    df["date_heure"] = pd.to_datetime(df["date_heure"], utc=True)
    df["date"] = pd.to_datetime(df["date"])

    daily = (
        df.groupby("date")
        .agg(
            conso_moyenne_mw=("consommation", "mean"),
            conso_max_mw=("consommation", "max"),
            conso_min_mw=("consommation", "min"),
            eolien_moyen_mw=("eolien", "mean"),
            solaire_moyen_mw=("solaire", "mean"),
            nucleaire_moyen_mw=("nucleaire", "mean"),
        )
        .reset_index()
    )
    return daily


def load_daily_temperature() -> pd.DataFrame:
    df = pd.read_csv(RAW_DIR / "weather_cities.csv")
    df["date_heure"] = pd.to_datetime(df["date_heure"])
    df["date"] = df["date_heure"].dt.floor("D")

    # Moyenne journalière par ville, puis moyenne pondérée par la population -> proxy national
    city_daily = df.groupby(["date", "ville"]).agg(temp=("temperature", "mean"), poids=("poids", "first")).reset_index()

    def weighted_mean(g: pd.DataFrame) -> float:
        return float(np.average(g["temp"], weights=g["poids"]))

    daily_temp = city_daily.groupby("date").apply(weighted_mean, include_groups=False).reset_index()
    daily_temp.columns = ["date", "temp_france"]
    return daily_temp


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["annee"] = df["date"].dt.year
    df["mois"] = df["date"].dt.month
    df["jour_semaine"] = df["date"].dt.dayofweek  # 0 = lundi
    df["is_weekend"] = df["jour_semaine"].isin([5, 6])

    fr_holidays = holidays.France(years=range(df["annee"].min(), df["annee"].max() + 1))
    df["is_ferie"] = df["date"].dt.date.astype("O").isin(fr_holidays)
    df["is_jour_ouvre"] = ~(df["is_weekend"] | df["is_ferie"])

    # Vacances scolaires non modélisées ici faute de source ouverte simple -> limite assumée.
    return df


def add_degree_days(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hdd"] = (HEATING_BASE_TEMP - df["temp_france"]).clip(lower=0)  # degrés-jours de chauffe
    df["cdd"] = (df["temp_france"] - COOLING_BASE_TEMP).clip(lower=0)  # degrés-jours de clim
    return df


def build() -> pd.DataFrame:
    conso = load_daily_conso()
    temp = load_daily_temperature()

    df = conso.merge(temp, on="date", how="inner")
    df = add_calendar_features(df)
    df = add_degree_days(df)
    df = df.sort_values("date").reset_index(drop=True)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "daily_dataset.csv"
    df.to_csv(out_path, index=False)
    print(f"[build_dataset] {len(df):,} jours -> {out_path}")
    print(df[["date", "conso_moyenne_mw", "temp_france", "hdd", "cdd"]].tail())
    return df


if __name__ == "__main__":
    build()
