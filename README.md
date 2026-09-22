# Modélisation du marché de l'électricité français

Projet personnel de modélisation quantitative appliqué au marché de l'électricité,
construit pour illustrer une compréhension du métier de **pricing analyst** (risque
volume, thermosensibilité, merit order, mécanisme de capacité, prix négatifs) avec des
données ouvertes et un code reproductible.

Trois volets, construits sur les données RTE éCO2mix (2018-2026) et, pour le volet
pricing, sur les prix day-ahead réels ENTSO-E de la même période :

1. **Thermosensibilité de la consommation** (modèle prédictif, testé hors échantillon)
   → [`outputs/rapport.md`](outputs/rapport.md)
2. **Fondamentaux du marché** (merit order, mécanisme de capacité, prix négatifs,
   profil de consommation) illustrés sur données réelles
   → [`outputs/rapport_marche.md`](outputs/rapport_marche.md)
3. **Construction du prix d'un contrat** (coût de forme, coût de capacité, prime de
   risque volume) — méthodologie explicite, hypothèses de calibration détaillées
   → [`outputs/rapport_pricing.md`](outputs/rapport_pricing.md)

## Résultats clés

> **+1°C en dessous de 18°C ⇒ +1,5 GW de consommation moyenne journalière en France.**
> Modèle testé hors échantillon sur 2025 : erreur moyenne absolue ≈ 2 GW (4,2 % de la
> consommation moyenne).

> **La part éolien + solaire est passée de ≈ 8 % à ≈ 20 % de la consommation française
> entre 2018 et 2026** — la mécanique derrière la fréquence croissante des prix bas /
> négatifs à la mi-journée.

> **Un profil de consommation thermosensible génère un surcoût indicatif d'≈ 7,8 €/MWh
> par rapport à un profil plat**, décomposé en coût de forme, coût de capacité et prime
> de risque volume — 3 composantes sur 4 calculées sur prix de marché réels (ENTSO-E).

> **La fréquence des heures à prix négatif est passée de 0,1 % en 2018 à 5,9 % en 2025**
> (données ENTSO-E réelles) — sur ces heures, la part éolien + solaire atteint 27 % en
> moyenne contre 13 % le reste du temps.

![Relation conso/température](outputs/figures/01_scatter_conso_temperature.png)
![Merit order](outputs/figures/11_merit_order_journee_type.png)
![Construction du prix](outputs/figures/22_construction_prix.png)

## Structure du projet

```
├── src/
│   ├── fetch_conso.py         # Téléchargement conso + mix RTE éCO2mix (ODRE, opendatasoft)
│   ├── fetch_weather.py       # Téléchargement températures Open-Meteo (11 villes)
│   ├── build_dataset.py       # Fusion + feature engineering -> dataset journalier
│   ├── model_consumption.py   # Régression thermosensibilité (HDD/CDD)
│   ├── explore_market.py      # Merit order, courbe monotone, duck curve, etc.
│   ├── fetch_price.py         # Téléchargement prix day-ahead FR (ENTSO-E, clé requise)
│   ├── model_price.py         # Régression prix réel ~ demande + renouvelable + nucléaire
│   └── pricing.py             # Construction du prix : coût de forme, capacité, risque
├── data/
│   ├── raw/                   # Données brutes téléchargées (ignorées par git, ~1M+ lignes)
│   └── processed/
│       ├── daily_dataset.csv        # Dataset journalier (conso, temp, calendrier)
│       └── hourly_price_dataset.csv # Dataset horaire conso + mix + prix réel
├── outputs/
│   ├── rapport.md             # Rapport thermosensibilité
│   ├── rapport_marche.md      # Rapport fondamentaux marché (merit order, capacité...)
│   ├── rapport_pricing.md     # Rapport construction du prix d'un contrat (données réelles)
│   ├── figures/                # Graphiques générés (01-05 : thermo, 11-15 : marché, 21-22 : pricing, 31-33 : prix réel)
│   ├── key_results.json       # Chiffres clés (thermosensibilité)
│   ├── key_results_marche.json # Chiffres clés (fondamentaux marché)
│   ├── key_results_price.json # Chiffres clés (régression prix réel)
│   ├── key_results_pricing.json # Chiffres clés (construction du prix)
│   └── model_summary.txt      # Sortie statsmodels complète (régression OLS)
└── requirements.txt
```

## Reproduire les résultats

```bash
pip install -r requirements.txt

# 1. Télécharger les données brutes (conso RTE + météo, ~2-5 min)
python src/fetch_conso.py --start 2018-01-01 --end 2026-06-30
python src/fetch_weather.py --start 2018-01-01 --end 2026-06-30

# 2. Construire le dataset journalier
python src/build_dataset.py

# 3. Estimer le modèle de thermosensibilité
python src/model_consumption.py

# 4. Fondamentaux marché (merit order, courbe monotone, duck curve...)
python src/explore_market.py

# 5. Prix day-ahead réel (nécessite une clé ENTSO-E gratuite, voir ci-dessous)
python src/fetch_price.py --start-year 2018 --end-year 2025
python src/model_price.py

# 6. Construction du prix (coût de forme, capacité, prime de risque)
python src/pricing.py
```

Les figures et chiffres clés sont régénérés dans `outputs/`.

### Obtenir une clé ENTSO-E (étape 5)

Nécessaire pour `fetch_price.py` uniquement (les autres étapes fonctionnent sans) :

1. Créer un compte sur [transparency.entsoe.eu](https://transparency.entsoe.eu/)
2. Envoyer un email à `transparency@entsoe.eu`, objet "Restful API access", avec
   l'adresse email du compte
3. Une fois l'accès accordé (~3 jours ouvrés), générer un token dans
   *My Account Settings*
4. Définir la variable d'environnement avant de lancer le script :
   `$env:ENTSOE_API_KEY = "votre_clé"` (PowerShell) ou `export ENTSOE_API_KEY=...` (bash)

La clé n'est jamais écrite dans un fichier du dépôt ; `data/raw/` (où atterrit le CSV de
prix téléchargé) est ignoré par git, mais `data/processed/hourly_price_dataset.csv`
(sans donnée sensible) est versionné pour que le dépôt reste exploitable sans clé.

## Méthode en bref

1. **Données** : consommation nationale quart-horaire (RTE éCO2mix, 2018-2026) et
   température horaire pour 11 grandes villes (Open-Meteo), agrégées en une
   température "France" pondérée par la population régionale.
2. **Feature engineering** : degrés-jours de chauffe (base 18°C) et de climatisation
   (base 24°C) pour capturer la relation non-linéaire en "U" entre conso et
   température, plus calendrier (jour de semaine, mois, jours fériés, tendance
   annuelle).
3. **Modèle** : régression linéaire (OLS, `statsmodels`), entraînée sur 2018-2024
   (hors 2020, atypique COVID), validée hors échantillon sur 2025.
4. **Évaluation** : R² in-sample, MAE/RMSE/MAPE out-of-sample, et analyse qualitative
   des pires jours de prévision (vagues de froid, jours fériés atypiques).

## Sources de données

| Source | Usage | Lien |
|---|---|---|
| RTE éCO2mix (ODRE) | Consommation, mix de production | https://odre.opendatasoft.com/explore/dataset/eco2mix-national-cons-def/ |
| Open-Meteo | Températures horaires historiques | https://open-meteo.com/en/docs/historical-weather-api |
| ENTSO-E Transparency Platform | Prix day-ahead réel France | https://transparency.entsoe.eu/ |

## Limites (assumées, détaillées dans le rapport)

- Proxy de température par 11 villes pondérées population, pas le maillage officiel
  RTE (32 stations pondérées conso régionale).
- Tendance annuelle supposée linéaire (fragile sur un horizon de prévision long).
- Vacances scolaires non modélisées (source ouverte simple non trouvée).
- Effet des vagues de froid prolongées probablement sous-estimé par un modèle
  purement journalier (pas de mémoire des jours précédents).

Voir [`outputs/rapport.md`](outputs/rapport.md) section 6 pour le détail et la
discussion associée.
