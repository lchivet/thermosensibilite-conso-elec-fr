"""
Modélisation de la thermosensibilité de la consommation électrique française.

Modèle : régression linéaire (OLS) de la consommation moyenne journalière (MW) sur :
  - les degrés-jours de chauffe (HDD, base 18°C)   -> capture l'effet chauffage (hiver)
  - les degrés-jours de climatisation (CDD, base 24°C) -> capture l'effet clim (été)
  - des effets fixes jour de la semaine (comportement structurel de la demande)
  - un effet fixe mois (saisonnalité résiduelle : luminosité, activité économique...)
  - une tendance annuelle (efficacité énergétique, sobriété, structure du parc)
  - un indicateur jour férié

La relation conso/température n'est PAS linéaire sur toute la plage (forme en "U" :
la conso augmente quand il fait froid ET quand il fait très chaud). Utiliser HDD/CDD
au lieu de la température brute permet de capturer cette forme en U avec un modèle
qui reste linéaire dans ses paramètres (donc simple à estimer et à interpréter).

Sortie :
  - outputs/figures/*.png
  - outputs/model_summary.txt (résumé complet de la régression)
  - outputs/key_results.json (chiffres clés réutilisés par le rapport)
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "daily_dataset.csv"
FIG_DIR = ROOT / "outputs" / "figures"
OUT_DIR = ROOT / "outputs"

# 2020 est une année atypique (confinements COVID) : conso structurellement décorrélée
# de la météo pendant plusieurs mois. On l'exclut de l'estimation par défaut et on le
# documente comme limite / choix de modélisation assumé.
EXCLUDE_YEARS = {2020}


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df["jour_semaine"] = df["jour_semaine"].astype("category")
    df["mois"] = df["mois"].astype("category")
    return df


def train_test_split_by_time(df: pd.DataFrame, test_year: int = 2025) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = df[(df["annee"] < test_year) & (~df["annee"].isin(EXCLUDE_YEARS))]
    test = df[df["annee"] == test_year]
    return train, test


FORMULA = (
    "conso_moyenne_mw ~ hdd + cdd + C(jour_semaine) + C(mois) + annee + is_ferie"
)


def fit_model(train: pd.DataFrame):
    model = smf.ols(FORMULA, data=train).fit()
    return model


def evaluate(model, test: pd.DataFrame) -> dict:
    pred = model.predict(test)
    residual = test["conso_moyenne_mw"] - pred
    mae = float(residual.abs().mean())
    rmse = float(np.sqrt((residual**2).mean()))
    mape = float((residual.abs() / test["conso_moyenne_mw"]).mean() * 100)
    return {"mae_mw": mae, "rmse_mw": rmse, "mape_pct": mape, "pred": pred, "residual": residual}


def plot_scatter_temp_conso(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(df["temp_france"], df["conso_moyenne_mw"] / 1000, s=6, alpha=0.35, color="#2E5EAA")
    ax.set_xlabel("Température moyenne pondérée France (°C)")
    ax.set_ylabel("Consommation moyenne journalière (GW)")
    ax.set_title("Relation conso / température — forme en \"U\" caractéristique")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "01_scatter_conso_temperature.png", dpi=150)
    plt.close(fig)


def plot_actual_vs_predicted(test: pd.DataFrame, pred: pd.Series) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(test["date"], test["conso_moyenne_mw"] / 1000, label="Conso réelle", color="#2E5EAA", linewidth=1)
    ax.plot(test["date"], pred / 1000, label="Conso prédite (modèle)", color="#D9782D", linewidth=1, alpha=0.85)
    ax.set_ylabel("Consommation moyenne journalière (GW)")
    ax.set_title(f"Consommation réelle vs prédite — {int(test['annee'].iloc[0])} (échantillon test)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "02_actual_vs_predicted.png", dpi=150)
    plt.close(fig)


def plot_residuals_vs_temp(test: pd.DataFrame, residual: pd.Series) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(test["temp_france"], residual / 1000, s=10, alpha=0.5, color="#B23A48")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Température moyenne pondérée France (°C)")
    ax.set_ylabel("Erreur de prévision (GW) — réel minus prédit")
    ax.set_title("Où le modèle se trompe-t-il le plus ?")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "03_residuals_vs_temperature.png", dpi=150)
    plt.close(fig)


def plot_worst_days(test: pd.DataFrame, residual: pd.Series, n: int = 10) -> pd.DataFrame:
    out = test.assign(residual_mw=residual).reindex(residual.abs().sort_values(ascending=False).index)
    cols = ["date", "temp_france", "conso_moyenne_mw", "residual_mw", "is_ferie", "jour_semaine"]
    return out[cols].head(n)


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    df = load_data()

    train, test = train_test_split_by_time(df, test_year=2025)
    model = fit_model(train)
    metrics = evaluate(model, test)

    plot_scatter_temp_conso(df)
    plot_actual_vs_predicted(test, metrics["pred"])
    plot_residuals_vs_temp(test, metrics["residual"])
    worst_days = plot_worst_days(test, metrics["residual"])

    hdd_coef = model.params["hdd"]
    cdd_coef = model.params["cdd"]
    hdd_pvalue = model.pvalues["hdd"]
    cdd_pvalue = model.pvalues["cdd"]

    (OUT_DIR / "model_summary.txt").write_text(model.summary().as_text(), encoding="utf-8")

    key_results = {
        "n_jours_train": int(len(train)),
        "n_jours_test": int(len(test)),
        "periode_train": [str(train["date"].min().date()), str(train["date"].max().date())],
        "periode_test": [str(test["date"].min().date()), str(test["date"].max().date())],
        "r2_in_sample": float(model.rsquared),
        "r2_adj_in_sample": float(model.rsquared_adj),
        "hdd_coef_mw_par_degre_jour": float(hdd_coef),
        "hdd_pvalue": float(hdd_pvalue),
        "cdd_coef_mw_par_degre_jour": float(cdd_coef),
        "cdd_pvalue": float(cdd_pvalue),
        "mae_test_mw": metrics["mae_mw"],
        "rmse_test_mw": metrics["rmse_mw"],
        "mape_test_pct": metrics["mape_pct"],
        "conso_moyenne_test_mw": float(test["conso_moyenne_mw"].mean()),
        "pire_jours": worst_days.assign(date=worst_days["date"].astype(str)).to_dict(orient="records"),
    }
    (OUT_DIR / "key_results.json").write_text(json.dumps(key_results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 70)
    print(f"Thermosensibilité (hiver) : {hdd_coef:,.0f} MW par degré-jour de chauffe (p={hdd_pvalue:.1e})")
    print(f"Thermosensibilité (été)   : {cdd_coef:,.0f} MW par degré-jour de clim (p={cdd_pvalue:.1e})")
    print(f"R² (in-sample, train)     : {model.rsquared:.3f}")
    print(f"MAE  (test {test['annee'].iloc[0]})       : {metrics['mae_mw']:,.0f} MW ({metrics['mape_pct']:.2f}% de la conso moyenne)")
    print(f"RMSE (test {test['annee'].iloc[0]})       : {metrics['rmse_mw']:,.0f} MW")
    print("=" * 70)
    print("\nPires jours de prévision (échantillon test) :")
    print(worst_days.to_string(index=False))


if __name__ == "__main__":
    main()
