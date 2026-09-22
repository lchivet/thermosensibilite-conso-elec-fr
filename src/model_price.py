"""
Modélisation du prix spot day-ahead France — sur données de prix réelles (ENTSO-E).

Objectif : expliquer les variations horaires du prix day-ahead à partir de la demande
et du mix de production, et caractériser les heures à prix négatif ou très bas.

Modèle : régression OLS du prix horaire (€/MWh) sur la consommation, la part
renouvelable (éolien + solaire) / consommation, la production nucléaire, et des effets
fixes heure de la journée / jour de la semaine.

Prérequis : avoir exécuté src/fetch_price.py (nécessite une clé ENTSOE_API_KEY).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import statsmodels.formula.api as smf

matplotlib.use("Agg")
plt.rcParams.update(
    {
        "figure.facecolor": "#fcfcfb",
        "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": "#c3c2b7",
        "axes.grid": True,
        "grid.color": "#e1e0d9",
        "grid.linewidth": 0.8,
        "font.size": 11,
    }
)

COL_BLUE = "#2a78d6"
COL_RED = "#e34948"

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "outputs" / "figures"
OUT_DIR = ROOT / "outputs"

PRICE_PATH = RAW_DIR / "prix_day_ahead_fr.csv"
CONSO_PATH = RAW_DIR / "conso_national.csv"


def load_hourly_conso() -> pd.DataFrame:
    df = pd.read_csv(CONSO_PATH, sep=";")
    df["date_heure"] = pd.to_datetime(df["date_heure"], utc=True)
    df = df.set_index("date_heure")
    for col in ["consommation", "eolien", "solaire", "nucleaire"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    hourly = df[["consommation", "eolien", "solaire", "nucleaire"]].resample("1h").mean()
    return hourly


def load_hourly_price() -> pd.DataFrame:
    df = pd.read_csv(PRICE_PATH, parse_dates=["date_heure"])
    df["date_heure"] = pd.to_datetime(df["date_heure"], utc=True)
    df = df.set_index("date_heure")
    hourly = df[["prix_eur_mwh"]].resample("1h").mean()
    return hourly


def build_hourly_dataset() -> pd.DataFrame:
    conso = load_hourly_conso()
    price = load_hourly_price()
    df = conso.join(price, how="inner").dropna()
    df["part_renouvelable"] = (df["eolien"] + df["solaire"]) / df["consommation"]
    df["heure"] = df.index.tz_convert("Europe/Paris").hour.astype("category")
    df["jour_semaine"] = df.index.tz_convert("Europe/Paris").dayofweek.astype("category")
    df["prix_negatif"] = df["prix_eur_mwh"] < 0
    return df


def plot_price_vs_renewable(df: pd.DataFrame) -> None:
    colors = df["prix_negatif"].map({True: COL_RED, False: COL_BLUE})

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    ax1.scatter(df["part_renouvelable"] * 100, df["prix_eur_mwh"], s=5, alpha=0.25, c=colors)
    ax1.axhline(0, color="black", linewidth=0.8)
    ax1.set_ylim(-100, 300)
    ax1.set_xlabel("Part éolien + solaire dans la consommation (%)")
    ax1.set_ylabel("Prix day-ahead réel (€/MWh)")
    ax1.set_title("Vue rapprochée (-100 à 300 €/MWh)")

    ax2.scatter(df["part_renouvelable"] * 100, df["prix_eur_mwh"], s=5, alpha=0.25, c=colors)
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_xlabel("Part éolien + solaire dans la consommation (%)")
    ax2.set_title("Vue complète (incl. pics de la crise 2021-2022)")

    fig.suptitle("Prix spot réel vs part renouvelable — rouge = prix négatif", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "31_prix_reel_vs_renouvelable.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_negative_price_hours(df: pd.DataFrame) -> None:
    counts = df[df["prix_negatif"]]["heure"].value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(counts.index.astype(int), counts.values, color=COL_RED)
    ax.set_xlabel("Heure de la journée (heure locale Paris)")
    ax.set_ylabel("Nombre d'heures à prix négatif (2018-2026)")
    ax.set_title("Distribution horaire des prix négatifs — données réelles ENTSO-E")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "32_heures_prix_negatif_reel.png", dpi=150)
    plt.close(fig)


def plot_negative_price_trend(df: pd.DataFrame) -> None:
    annual = df.groupby(df.index.tz_convert("Europe/Paris").year).agg(
        pct_negatif=("prix_negatif", "mean"), n_heures=("prix_negatif", "size")
    )
    annual = annual[annual["n_heures"] > 4000]  # années complètes seulement
    annual["pct_negatif"] *= 100

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(annual.index.astype(str), annual["pct_negatif"], color=COL_BLUE)
    ax.set_ylabel("% d'heures à prix négatif dans l'année")
    ax.set_title("Fréquence des prix négatifs par année — données réelles")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "33_tendance_prix_negatif.png", dpi=150)
    plt.close(fig)
    return annual


def main() -> None:
    if not PRICE_PATH.exists():
        print(
            f"[model_price] Fichier de prix introuvable : {PRICE_PATH}\n"
            "-> Lancer d'abord : python src/fetch_price.py",
            file=sys.stderr,
        )
        sys.exit(1)

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    df = build_hourly_dataset()

    formula = "prix_eur_mwh ~ consommation + part_renouvelable + nucleaire + C(heure) + C(jour_semaine)"
    model = smf.ols(formula, data=df).fit()
    (OUT_DIR / "model_price_summary.txt").write_text(model.summary().as_text(), encoding="utf-8")

    plot_price_vs_renewable(df)
    plot_negative_price_hours(df)
    annual_trend = plot_negative_price_trend(df)

    neg = df[df["prix_negatif"]]
    key_results = {
        "periode": [str(df.index.min().date()), str(df.index.max().date())],
        "n_heures": int(len(df)),
        "n_heures_prix_negatif": int(len(neg)),
        "pct_heures_prix_negatif": float(len(neg) / len(df) * 100),
        "part_renouvelable_moyenne_heures_negatives_pct": float(neg["part_renouvelable"].mean() * 100) if len(neg) else None,
        "part_renouvelable_moyenne_globale_pct": float(df["part_renouvelable"].mean() * 100),
        "prix_moyen_eur_mwh": float(df["prix_eur_mwh"].mean()),
        "prix_ecart_type_eur_mwh": float(df["prix_eur_mwh"].std()),
        "prix_median_eur_mwh": float(df["prix_eur_mwh"].median()),
        "prix_min_eur_mwh": float(df["prix_eur_mwh"].min()),
        "prix_max_eur_mwh": float(df["prix_eur_mwh"].max()),
        "r2": float(model.rsquared),
        "coef_part_renouvelable": float(model.params.get("part_renouvelable", float("nan"))),
        "coef_consommation": float(model.params.get("consommation", float("nan"))),
        "tendance_annuelle_pct_negatif": {str(k): float(v) for k, v in annual_trend["pct_negatif"].items()},
    }
    (OUT_DIR / "key_results_price.json").write_text(json.dumps(key_results, indent=2, ensure_ascii=False), encoding="utf-8")

    # Dataset horaire prix+conso, pour réutilisation (pricing.py) et pour que le dépôt
    # reste auto-suffisant sans que chaque lecteur doive obtenir sa propre clé ENTSO-E.
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.reset_index().to_csv(PROCESSED_DIR / "hourly_price_dataset.csv", index=False)

    print("=" * 70)
    print(f"Période couverte : {key_results['periode'][0]} -> {key_results['periode'][1]}")
    print(f"Prix moyen : {key_results['prix_moyen_eur_mwh']:.1f} €/MWh (médiane {key_results['prix_median_eur_mwh']:.1f}, écart-type {key_results['prix_ecart_type_eur_mwh']:.1f})")
    print(f"Heures à prix négatif : {len(neg):,} / {len(df):,} ({key_results['pct_heures_prix_negatif']:.2f}%)")
    if len(neg):
        print(
            f"  -> part renouvelable moyenne sur ces heures : "
            f"{key_results['part_renouvelable_moyenne_heures_negatives_pct']:.1f}% "
            f"(vs {key_results['part_renouvelable_moyenne_globale_pct']:.1f}% en moyenne globale)"
        )
    print(f"R² du modèle : {model.rsquared:.3f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
