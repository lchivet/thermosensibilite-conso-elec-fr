"""
Construction indicative du prix d'un contrat de fourniture — angle pricing analyst.

Objectif : montrer, à partir des données déjà collectées (consommation, mix de
production, degrés-jours), comment un profil de consommation se traduit en
composantes de prix (coût de forme, coût de capacité, prime de risque volume),
sans disposer de vraies données de prix de marché.

Principe : en l'absence de prix spot réel, on construit un indice de prix relatif
dérivé du merit order (rang de la charge résiduelle = consommation − éolien − solaire :
plus elle est élevée, plus le système fait appel à des moyens de production coûteux).
Cet indice sert à comparer des profils entre eux — il n'a pas vocation à reproduire un
niveau de prix en euros réel. Chaque paramètre non directement calculé à partir des
données (poids des profils synthétiques, prix de la garantie de capacité, prime de
risque, marge) est un paramètre explicite, réuni dans PARAMETRES ci-dessous.

Sortie : outputs/figures/2x_*.png + outputs/key_results_pricing.json
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")
plt.rcParams.update(
    {
        "figure.facecolor": "#fcfcfb",
        "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": "#c3c2b7",
        "axes.labelcolor": "#0b0b0b",
        "text.color": "#0b0b0b",
        "xtick.color": "#52514e",
        "ytick.color": "#52514e",
        "axes.grid": True,
        "grid.color": "#e1e0d9",
        "grid.linewidth": 0.8,
        "font.size": 11,
    }
)

COL_BLUE = "#2a78d6"
COL_ORANGE = "#eb6834"
COL_AQUA = "#1baf7a"
COL_VIOLET = "#4a3aa7"
COL_RED = "#e34948"
COL_GREY = "#c3c2b7"

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "outputs" / "figures"
OUT_DIR = ROOT / "outputs"

# ---------------------------------------------------------------------------
# Paramètres explicites (hypothèses de construction, non calculés sur les données)
# ---------------------------------------------------------------------------
PARAMETRES = {
    "part_marche_portefeuille_illustratif_pct": 1.0,  # portefeuille = 1% de la conso française
    "prix_capacite_illustratif_eur_par_mw_an": 30000,  # ordre de grandeur des enchères RTE, à remplacer par la vraie valeur publiée
    "volatilite_prix_illustrative_eur_par_mwh": 80,  # prime de risque : coût d'achat complémentaire en période de tension
    "prix_proxy_bas_eur_mwh": 30,  # prix illustratif associé au percentile 0 (heures très abondantes, proche des prix négatifs)
    "prix_proxy_haut_eur_mwh": 150,  # prix illustratif associé au percentile 100 (heures de forte tension système)
    "marge_commerciale_eur_mwh": 3.0,  # marge commerciale forfaitaire
    "seuil_heures_pointe": 200,  # définition de la "zone de pointe" (cf. courbe monotone, rapport_marche.md section 2)
}

HEATING_HOURS = {7, 8, 9, 18, 19, 20, 21}


def load_hourly() -> pd.DataFrame:
    df = pd.read_csv(RAW_DIR / "conso_national.csv", sep=";")
    df["date_heure"] = pd.to_datetime(df["date_heure"], utc=True)
    df = df.set_index("date_heure").sort_index()
    for col in ["consommation", "eolien", "solaire"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    hourly = df[["consommation", "eolien", "solaire"]].resample("1h").mean().dropna()
    hourly.index = hourly.index.tz_convert("Europe/Paris")
    hourly["residuelle"] = hourly["consommation"] - hourly["eolien"] - hourly["solaire"]
    hourly["annee"] = hourly.index.year
    hourly["mois"] = hourly.index.month
    hourly["heure"] = hourly.index.hour
    hourly["jour_semaine"] = hourly.index.dayofweek
    hourly["date"] = hourly.index.date
    return hourly


def add_price_rank(hourly: pd.DataFrame) -> pd.DataFrame:
    """Indice de prix proxy = percentile (0-100) de la charge résiduelle, calculé
    séparément chaque mois pour ne pas confondre effet saisonnier et effet horaire."""
    hourly = hourly.copy()
    hourly["prix_rang_percentile"] = (
        hourly.groupby([hourly["annee"], hourly["mois"]])["residuelle"]
        .rank(pct=True)
        * 100
    )
    return hourly


def flag_peak_hours(hourly: pd.DataFrame, top_n: int) -> pd.DataFrame:
    hourly = hourly.copy()
    hourly["est_heure_pointe"] = False
    for year, sub in hourly.groupby("annee"):
        if len(sub) < top_n:
            continue
        threshold = sub["consommation"].nlargest(top_n).min()
        hourly.loc[sub.index, "est_heure_pointe"] = sub["consommation"] >= threshold
    return hourly


def load_daily_hdd() -> pd.DataFrame:
    df = pd.read_csv(PROCESSED_DIR / "daily_dataset.csv", parse_dates=["date"])
    return df[["date", "hdd", "annee"]]


def build_profiles(hourly: pd.DataFrame, daily_hdd: pd.DataFrame) -> pd.DataFrame:
    profiles = pd.DataFrame(index=hourly.index)

    # Profil "plat" : référence, poids uniforme
    profiles["plat"] = 1.0

    # Profil "tertiaire" : bureaux, actif en semaine 8h-19h
    is_weekday = hourly["jour_semaine"] < 5
    is_office_hours = hourly["heure"].between(8, 18)
    profiles["tertiaire"] = np.select(
        [is_weekday & is_office_hours, is_weekday & ~is_office_hours],
        [1.0, 0.3],
        default=0.15,
    )

    # Profil "thermosensible" : chauffage électrique résidentiel, pondéré par le vrai HDD du jour
    hdd_by_date = daily_hdd.set_index("date")["hdd"]
    hdd_of_hour = pd.Series(hourly["date"].values, index=hourly.index).map(
        lambda d: hdd_by_date.get(pd.Timestamp(d), 0.0)
    )
    is_heating_hour = hourly["heure"].isin(HEATING_HOURS)
    boost = np.where(is_heating_hour, 0.15, 0.03)
    profiles["thermosensible"] = 1.0 + boost * hdd_of_hour.values

    # Normalisation : chaque profil est une distribution de probabilité sur l'année (somme = 1)
    for col in profiles.columns:
        profiles[col] = profiles[col] / profiles[col].sum()

    return profiles


def compute_profile_metrics(hourly: pd.DataFrame, profiles: pd.DataFrame) -> dict:
    results = {}
    for name in profiles.columns:
        w = profiles[name]
        percentile_pondere = float((w * hourly["prix_rang_percentile"]).sum())
        contribution_pointe = float((w * hourly["est_heure_pointe"]).sum() * 100)
        results[name] = {
            "percentile_prix_pondere": percentile_pondere,
            "contribution_pointe_pct": contribution_pointe,
        }
    return results


def plot_profile_comparison(metrics: dict) -> None:
    labels = ["Plat\n(référence)", "Tertiaire\n(bureaux 8h-19h)", "Thermosensible\n(chauffage résidentiel)"]
    keys = ["plat", "tertiaire", "thermosensible"]
    percentiles = [metrics[k]["percentile_prix_pondere"] for k in keys]
    contributions = [metrics[k]["contribution_pointe_pct"] for k in keys]
    x = np.arange(len(keys))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    b1 = ax1.bar(x, percentiles, color=COL_BLUE, width=0.55)
    ax1.axhline(50, color=COL_GREY, linestyle="--", linewidth=1, zorder=0)
    ax1.set_ylim(0, 100)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("Percentile de prix pondéré (référence plat = 50)")
    ax1.set_title("Coût de forme")
    for rect, val in zip(b1, percentiles):
        ax1.annotate(f"{val:.0f}", (rect.get_x() + rect.get_width() / 2, val), ha="center", va="bottom", fontsize=9)

    b2 = ax2.bar(x, contributions, color=COL_ORANGE, width=0.55)
    ax2.set_ylim(0, max(contributions) * 1.35)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("Contribution aux heures de pointe système (%)")
    ax2.set_title("Coût de capacité")
    for rect, val in zip(b2, contributions):
        ax2.annotate(f"{val:.1f}%", (rect.get_x() + rect.get_width() / 2, val), ha="center", va="bottom", fontsize=9)

    fig.suptitle("Trois profils, même volume annuel, coût de forme et de capacité différents", fontsize=12.5)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "21_comparaison_profils.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_price_waterfall(metrics: dict, params: dict, prime_risque_eur_mwh: float) -> dict:
    """Construit le SURCOÛT (en €/MWh) d'un profil thermosensible par rapport à un
    profil plat — pas un prix absolu (inconnu, faute de données de marché réelles)."""
    plat = metrics["plat"]
    thermo = metrics["thermosensible"]

    ecart_percentile = thermo["percentile_prix_pondere"] - plat["percentile_prix_pondere"]
    ecart_pointe_pts = thermo["contribution_pointe_pct"] - plat["contribution_pointe_pct"]

    # Coût de forme : conversion percentile -> €/MWh via une droite illustrative
    # reliant le percentile de prix (0-100, réel) à un ordre de grandeur de prix (€/MWh, illustratif)
    pente_prix = (params["prix_proxy_haut_eur_mwh"] - params["prix_proxy_bas_eur_mwh"]) / 100
    cout_forme = ecart_percentile * pente_prix

    # Coût de capacité : écart de contribution à la pointe (réel) x prix de la garantie
    # de capacité ramené à une base horaire (1 MW retenu 1h = 1 MWh-équivalent)
    cout_capacite = (ecart_pointe_pts / 100) * (params["prix_capacite_illustratif_eur_par_mw_an"] / 8760)

    prime_risque = prime_risque_eur_mwh
    marge = params["marge_commerciale_eur_mwh"]
    total = cout_forme + cout_capacite + prime_risque + marge

    labels = ["Coût de\nforme", "Coût de\ncapacité", "Prime de\nrisque volume", "Marge", "Surcoût\ntotal"]
    values = [cout_forme, cout_capacite, prime_risque, marge, total]
    cumulative = [0, cout_forme, cout_forme + cout_capacite, cout_forme + cout_capacite + prime_risque, 0]

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    colors = [COL_ORANGE, COL_VIOLET, COL_RED, COL_AQUA, COL_BLUE]
    for i, val in enumerate(values):
        if i == len(labels) - 1:
            ax.bar(i, val, color=colors[i], width=0.6)
            ax.annotate(f"{val:.1f} €/MWh", (i, val + total * 0.02), ha="center", fontsize=10, fontweight="bold")
        else:
            bottom = cumulative[i]
            ax.bar(i, val, bottom=bottom, color=colors[i], width=0.6)
            ax.annotate(f"+{val:.1f}", (i, bottom + val + total * 0.02), ha="center", fontsize=10)

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Surcoût vs profil plat (€/MWh)")
    ax.set_title("Surcoût indicatif d'un profil thermosensible vs un profil plat")
    ax.set_ylim(0, total * 1.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "22_construction_prix.png", dpi=150)
    plt.close(fig)

    return {
        "ecart_percentile_prix": ecart_percentile,
        "ecart_contribution_pointe_pts": ecart_pointe_pts,
        "cout_forme_eur_mwh": cout_forme,
        "cout_capacite_eur_mwh": cout_capacite,
        "prime_risque_eur_mwh": prime_risque,
        "marge_eur_mwh": marge,
        "surcout_total_eur_mwh": total,
    }


def compute_real_climate_risk(daily_hdd: pd.DataFrame, conso_france_annuelle_mwh: float) -> dict:
    """Variabilité interannuelle RÉELLE des degrés-jours (2018-2025, hors 2020) et
    traduction en risque volume et prix pour un portefeuille de taille illustrative."""
    annual_hdd = (
        daily_hdd[(daily_hdd["annee"] >= 2018) & (daily_hdd["annee"] <= 2025) & (daily_hdd["annee"] != 2020)]
        .groupby("annee")["hdd"]
        .sum()
    )
    hdd_mean = float(annual_hdd.mean())
    hdd_std = float(annual_hdd.std())

    part_marche = PARAMETRES["part_marche_portefeuille_illustratif_pct"] / 100
    hdd_coef_systeme_mw = 1515.0  # coefficient réel estimé (rapport.md, section 4)
    hdd_coef_portefeuille_mw = hdd_coef_systeme_mw * part_marche

    variation_volume_mwh = hdd_coef_portefeuille_mw * hdd_std * 24  # écart-type -> MWh sur l'année
    variation_cout_eur = variation_volume_mwh * PARAMETRES["volatilite_prix_illustrative_eur_par_mwh"]

    portefeuille_volume_mwh = conso_france_annuelle_mwh * part_marche
    prime_risque_eur_mwh = variation_cout_eur / portefeuille_volume_mwh

    return {
        "hdd_annuel_moyen": hdd_mean,
        "hdd_annuel_ecart_type": hdd_std,
        "hdd_coef_portefeuille_mw_par_dj": hdd_coef_portefeuille_mw,
        "portefeuille_volume_annuel_mwh": portefeuille_volume_mwh,
        "variation_volume_ecart_type_mwh": variation_volume_mwh,
        "variation_cout_ecart_type_eur": variation_cout_eur,
        "prime_risque_eur_mwh": prime_risque_eur_mwh,
    }


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    hourly = load_hourly()
    hourly = add_price_rank(hourly)
    hourly = flag_peak_hours(hourly, PARAMETRES["seuil_heures_pointe"])
    daily_hdd = load_daily_hdd()

    profiles = build_profiles(hourly, daily_hdd)
    metrics = compute_profile_metrics(hourly, profiles)
    plot_profile_comparison(metrics)

    # Consommation annuelle française réelle (moyenne des années complètes, hors 2020)
    annual_conso = (
        hourly[(hourly["annee"] >= 2018) & (hourly["annee"] <= 2025) & (hourly["annee"] != 2020)]
        .groupby("annee")["consommation"]
        .sum()
    )
    conso_france_annuelle_mwh = float(annual_conso.mean())

    climate_risk = compute_real_climate_risk(daily_hdd, conso_france_annuelle_mwh)
    waterfall = plot_price_waterfall(metrics, PARAMETRES, climate_risk["prime_risque_eur_mwh"])

    results = {
        "parametres": PARAMETRES,
        "conso_france_annuelle_moyenne_mwh": conso_france_annuelle_mwh,
        "metriques_profils": metrics,
        "risque_climatique_reel": climate_risk,
        "construction_prix": waterfall,
    }
    (OUT_DIR / "key_results_pricing.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
