"""
Fondamentaux du marché électrique français, illustrés à partir des données RTE
éCO2mix déjà téléchargées (mix de production quart-horaire, 2018-2026).

Chaque graphique correspond à un concept du métier de pricing analyst :
  1. Merit order        -> stack de production, journée type hiver vs été
  2. Mécanisme de capacité -> courbe monotone de charge + zone de pointe
  3. Profil de conso / shape cost -> heatmap heure x jour de semaine
  4. Prix négatifs (logique merit order) -> "duck curve" charge résiduelle
  5. Enjeux actuels -> trajectoire de la part renouvelable dans le temps

Sortie : outputs/figures/1x_*.png + outputs/key_results_marche.json
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

# Palette catégorielle fixe (skill dataviz) — un slot = une filière, jamais réordonné
COL_NUCLEAIRE = "#2a78d6"
COL_GAZ = "#eb6834"
COL_HYDRAULIQUE = "#1baf7a"
COL_SOLAIRE = "#eda100"
COL_BIOENERGIES = "#e87ba4"
COL_EOLIEN = "#008300"
COL_CHARBON = "#4a3aa7"
COL_FIOUL = "#e34948"
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95", "#0d366b"]

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
FIG_DIR = ROOT / "outputs" / "figures"
OUT_DIR = ROOT / "outputs"

FILIERES = ["nucleaire", "hydraulique", "gaz", "eolien", "solaire", "charbon", "fioul", "bioenergies"]
FILIERE_COLORS = {
    "nucleaire": COL_NUCLEAIRE,
    "hydraulique": COL_HYDRAULIQUE,
    "gaz": COL_GAZ,
    "eolien": COL_EOLIEN,
    "solaire": COL_SOLAIRE,
    "charbon": COL_CHARBON,
    "fioul": COL_FIOUL,
    "bioenergies": COL_BIOENERGIES,
}
FILIERE_LABELS = {
    "nucleaire": "Nucléaire",
    "hydraulique": "Hydraulique",
    "gaz": "Gaz",
    "eolien": "Éolien",
    "solaire": "Solaire",
    "charbon": "Charbon",
    "fioul": "Fioul",
    "bioenergies": "Bioénergies",
}


def load_raw() -> pd.DataFrame:
    df = pd.read_csv(RAW_DIR / "conso_national.csv", sep=";")
    df["date_heure"] = pd.to_datetime(df["date_heure"], utc=True)
    df = df.set_index("date_heure").sort_index()
    df["date_heure_paris"] = df.index.tz_convert("Europe/Paris")
    df["heure_locale"] = df["date_heure_paris"].dt.hour
    df["mois"] = df["date_heure_paris"].dt.month
    df["annee"] = df["date_heure_paris"].dt.year
    df["jour_semaine"] = df["date_heure_paris"].dt.dayofweek
    for f in FILIERES:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["consommation"] = pd.to_numeric(df["consommation"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# 1. Merit order : stack de production, journée type hiver vs été
# ---------------------------------------------------------------------------
def plot_merit_order(df: pd.DataFrame) -> dict:
    hiver = df[df["mois"].isin([12, 1, 2])]
    ete = df[df["mois"].isin([6, 7, 8])]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    for ax, sub, titre in zip(axes, [hiver, ete], ["Journée type — hiver (déc-jan-fév)", "Journée type — été (juin-juil-août)"]):
        profile = sub.groupby("heure_locale")[FILIERES].mean() / 1000  # GW
        conso_profile = sub.groupby("heure_locale")["consommation"].mean() / 1000
        ax.stackplot(
            profile.index,
            [profile[f] for f in FILIERES],
            labels=[FILIERE_LABELS[f] for f in FILIERES],
            colors=[FILIERE_COLORS[f] for f in FILIERES],
            edgecolor="#fcfcfb",
            linewidth=0.4,
        )
        ax.plot(conso_profile.index, conso_profile.values, color="#0b0b0b", linewidth=1.6, linestyle="--", label="Consommation")
        ax.set_title(titre)
        ax.set_xlabel("Heure de la journée (heure locale Paris)")
        ax.set_xlim(0, 23)
    axes[0].set_ylabel("Puissance moyenne (GW)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, -0.08))
    fig.suptitle("Merit order en pratique : qui produit, à quelle heure ?", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "11_merit_order_journee_type.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    gaz_hiver_soir = hiver[hiver["heure_locale"].isin([18, 19, 20])]["gaz"].mean() / 1000
    gaz_hiver_nuit = hiver[hiver["heure_locale"].isin([3, 4, 5])]["gaz"].mean() / 1000
    return {
        "gaz_moyen_pointe_soir_hiver_gw": float(gaz_hiver_soir),
        "gaz_moyen_creux_nuit_hiver_gw": float(gaz_hiver_nuit),
        "ratio_gaz_pointe_vs_creux": float(gaz_hiver_soir / gaz_hiver_nuit) if gaz_hiver_nuit else None,
    }


# ---------------------------------------------------------------------------
# 2. Courbe monotone de charge + zone de pointe (mécanisme de capacité)
# ---------------------------------------------------------------------------
def plot_load_duration_curve(df: pd.DataFrame, year: int = 2025) -> dict:
    sub = df[df["annee"] == year]
    hourly = sub["consommation"].resample("1h").mean().dropna() / 1000  # GW
    sorted_load = hourly.sort_values(ascending=False).reset_index(drop=True)
    sorted_load.index = sorted_load.index + 1  # 1..8760

    peak_hours_n = 200  # zone de pointe illustrative (proxy pédagogique du principe PP1)
    peak_threshold = sorted_load.iloc[peak_hours_n - 1]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.plot(sorted_load.index, sorted_load.values, color=COL_NUCLEAIRE, linewidth=1.8)
    ax.axvline(peak_hours_n, color=COL_FIOUL, linestyle="--", linewidth=1.2)
    ax.axhline(peak_threshold, color=COL_FIOUL, linestyle="--", linewidth=1.2)
    ax.fill_between(sorted_load.index[:peak_hours_n], sorted_load.values[:peak_hours_n], color=COL_FIOUL, alpha=0.12)
    ax.annotate(
        f"Zone de pointe illustrative\n(top {peak_hours_n} h de l'année, ~{peak_hours_n/8760*100:.1f}% du temps)\nseuil ≈ {peak_threshold:.1f} GW",
        xy=(peak_hours_n, peak_threshold),
        xytext=(peak_hours_n + 900, sorted_load.max() * 0.92),
        arrowprops=dict(arrowstyle="->", color="#52514e"),
        fontsize=9.5,
        color="#0b0b0b",
    )
    ax.set_xlabel(f"Nombre d'heures de l'année {year} où la demande dépasse le niveau indiqué")
    ax.set_ylabel("Puissance appelée (GW)")
    ax.set_title(f"Courbe monotone de charge — France {year}")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "12_courbe_monotone_charge.png", dpi=150)
    plt.close(fig)

    base_load = sorted_load.iloc[-int(len(sorted_load) * 0.05):].mean()  # les 5% d'heures les plus faibles
    return {
        "annee": year,
        "puissance_max_gw": float(sorted_load.max()),
        "puissance_min_gw": float(sorted_load.min()),
        "puissance_moyenne_gw": float(sorted_load.mean()),
        "seuil_zone_pointe_gw": float(peak_threshold),
        "facteur_charge_pct": float(sorted_load.mean() / sorted_load.max() * 100),
        "base_load_approx_gw": float(base_load),
    }


# ---------------------------------------------------------------------------
# 3. Heatmap heure x jour de semaine (profil de consommation / shape cost)
# ---------------------------------------------------------------------------
def plot_load_heatmap(df: pd.DataFrame) -> dict:
    hourly = df["consommation"].resample("1h").mean().dropna().to_frame()
    hourly["heure"] = hourly.index.tz_convert("Europe/Paris").hour
    hourly["jour_semaine"] = hourly.index.tz_convert("Europe/Paris").dayofweek
    pivot = hourly.groupby(["jour_semaine", "heure"])["consommation"].mean().unstack() / 1000  # GW

    fig, ax = plt.subplots(figsize=(10, 4.5))
    im = ax.imshow(pivot.values, aspect="auto", cmap=matplotlib.colors.LinearSegmentedColormap.from_list("seq_blue", SEQ_BLUE))
    ax.set_yticks(range(7))
    ax.set_yticklabels(["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"])
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels(range(0, 24, 2))
    ax.set_xlabel("Heure de la journée (heure locale Paris)")
    ax.set_title("Profil moyen de consommation — heure × jour de semaine (2018-2026)")
    ax.grid(False)
    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label("Consommation moyenne (GW)")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "13_heatmap_profil_hebdo.png", dpi=150)
    plt.close(fig)

    weekday_avg = pivot.iloc[0:5].mean(axis=0)
    weekend_avg = pivot.iloc[5:7].mean(axis=0)
    ecart_pointe_creux = float(weekday_avg.max() - weekday_avg.min())
    return {
        "conso_moyenne_semaine_gw": float(weekday_avg.mean()),
        "conso_moyenne_weekend_gw": float(weekend_avg.mean()),
        "ecart_semaine_weekend_pct": float((weekday_avg.mean() - weekend_avg.mean()) / weekend_avg.mean() * 100),
        "ecart_pointe_creux_jour_ouvre_gw": ecart_pointe_creux,
    }


# ---------------------------------------------------------------------------
# 4. "Duck curve" : charge résiduelle (conso - renouvelable variable)
# ---------------------------------------------------------------------------
def plot_duck_curve(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["residuelle"] = df["consommation"] - df["eolien"] - df["solaire"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    for ax, mois, titre in zip(
        axes,
        [[12, 1, 2], [4, 5, 6]],
        ["Hiver (peu de solaire)", "Printemps (fort solaire, conso plus faible)"],
    ):
        sub = df[df["mois"].isin(mois)]
        conso_p = sub.groupby("heure_locale")["consommation"].mean() / 1000
        resid_p = sub.groupby("heure_locale")["residuelle"].mean() / 1000
        ax.plot(conso_p.index, conso_p.values, color="#0b0b0b", linewidth=1.8, linestyle="--", label="Consommation totale")
        ax.plot(resid_p.index, resid_p.values, color=COL_SOLAIRE, linewidth=2.2, label="Charge résiduelle\n(conso − éolien − solaire)")
        ax.fill_between(conso_p.index, resid_p.values, conso_p.values, color=COL_SOLAIRE, alpha=0.15)
        ax.set_title(titre)
        ax.set_xlabel("Heure de la journée (heure locale Paris)")
        ax.set_xlim(0, 23)
    axes[0].set_ylabel("Puissance moyenne (GW)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.1))
    fig.suptitle('La "duck curve" : le creux de midi qui pousse les prix vers le bas (voire négatif)', fontsize=12.5)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "14_duck_curve.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    printemps = df[df["mois"].isin([4, 5, 6])]
    midi = printemps[printemps["heure_locale"].isin([12, 13, 14])]
    creux_residuel_midi_gw = float(midi["residuelle"].mean() / 1000)
    part_renouvelable_midi = float(((midi["eolien"] + midi["solaire"]) / midi["consommation"]).mean() * 100)
    return {
        "charge_residuelle_moyenne_midi_printemps_gw": creux_residuel_midi_gw,
        "part_renouvelable_moyenne_midi_printemps_pct": part_renouvelable_midi,
    }


# ---------------------------------------------------------------------------
# 5. Trajectoire de la part renouvelable (éolien + solaire) dans le temps
# ---------------------------------------------------------------------------
def plot_renewable_trend(df: pd.DataFrame) -> dict:
    monthly = df.resample("1ME").agg(
        conso=("consommation", "mean"),
        eolien=("eolien", "mean"),
        solaire=("solaire", "mean"),
    )
    monthly["part_renouvelable"] = (monthly["eolien"] + monthly["solaire"]) / monthly["conso"] * 100
    rolling = monthly["part_renouvelable"].rolling(12, min_periods=6).mean()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(monthly.index, monthly["part_renouvelable"], color="#c3c2b7", linewidth=1, label="Mensuel")
    ax.plot(rolling.index, rolling.values, color=COL_NUCLEAIRE, linewidth=2.2, label="Moyenne mobile 12 mois")
    ax.set_ylabel("Part éolien + solaire dans la consommation (%)")
    ax.set_title("Montée en puissance du renouvelable variable dans le mix français")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "15_trajectoire_renouvelable.png", dpi=150)
    plt.close(fig)

    debut = float(rolling.dropna().iloc[0])
    fin = float(rolling.dropna().iloc[-1])
    return {
        "part_renouvelable_debut_pct": debut,
        "part_renouvelable_fin_pct": fin,
        "progression_points_pct": fin - debut,
        "periode": [str(rolling.dropna().index[0].date()), str(rolling.dropna().index[-1].date())],
    }


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    df = load_raw()

    results = {
        "merit_order": plot_merit_order(df),
        "courbe_monotone": plot_load_duration_curve(df, year=2025),
        "profil_hebdo": plot_load_heatmap(df),
        "duck_curve": plot_duck_curve(df),
        "trajectoire_renouvelable": plot_renewable_trend(df),
    }
    (OUT_DIR / "key_results_marche.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
