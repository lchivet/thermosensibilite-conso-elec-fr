# Thermosensibilité de la consommation électrique française — Rapport

*Généré à partir de `src/model_consumption.py`. Les chiffres ci-dessous viennent de
`outputs/key_results.json` et des figures dans `outputs/figures/`.*

## 1. Question posée

**Quelle est la sensibilité de la consommation électrique française à la température,
et que révèle-t-elle sur le risque volume pour un fournisseur d'électricité ?**

Une partie de l'erreur de forecast vient de la météo,
et cette part doit être quantifiée pour être couverte (hedging volumétrique) ou provisionnée dans le prix.

## 2. Méthode (en une phrase)

Régression linéaire (OLS) de la consommation moyenne journalière sur des **degrés-jours
de chauffe et de climatisation** (plutôt que la température brute, pour capturer la forme
en "U" de la relation conso/température), avec effets fixes jour de semaine, mois,
tendance annuelle et jours fériés — entraînée sur 2018-2024 (hors 2020, année atypique
COVID), testée sur 2025.

## 3. Données

| Source | Contenu | Période |
|---|---|---|
| RTE éCO2mix (ODRE / opendatasoft) | Consommation nationale, quart-horaire | 2018-01-01 → 2026-06-30 |
| Open-Meteo Historical Weather API | Température horaire, 11 villes | idem |

La température "France" est une **moyenne pondérée par la population régionale** sur 11
grandes villes (Paris, Lyon, Marseille, Toulouse, Lille, Strasbourg, Bordeaux, Nantes,
Rennes, Dijon, Montpellier) — une approximation du maillage officiel RTE (~32 stations
Météo-France pondérées par la consommation régionale), assumée comme simplification
(voir section 6).

## 4. Résultat chiffré marquant

> **+1°C de baisse en dessous de 18°C ⇒ +1,5 GW de consommation moyenne journalière en
> France** (coefficient HDD = 1 515 MW/degré-jour, p < 0,001).
>
> Côté été, chaque degré au-dessus de 24°C ajoute environ **+1,0 GW** (climatisation,
> coefficient CDD = 972 MW/degré-jour, p < 0,001) — un effet plus faible qu'en hiver
> (le parc de chauffage électrique français est bien plus développé que la climatisation),
> mais déjà statistiquement net.

Qualité du modèle :
- **R² = 0,946** sur la période d'entraînement (2018-2024, hors 2020)
- Sur l'année 2025 (jamais vue par le modèle) : **erreur moyenne absolue (MAE) ≈ 2,0 GW**,
  soit **4,2 % de la consommation moyenne** (≈ 50,7 GW) — RMSE ≈ 2,5 GW.

Pour donner un ordre de grandeur : le coefficient hiver (1,5 GW/°C en moyenne
journalière) est cohérent avec les chiffres publiquement communiqués par RTE pour la
thermosensibilité à la pointe (RTE annonce ~2,4 GW/°C à la pointe 19h en hiver) — notre
estimation porte sur la moyenne journalière, donc logiquement plus faible que l'effet
au pic horaire du soir.

## 5. Où le modèle se trompe le plus (échantillon test 2025)

| Date | Contexte | Erreur (réel − prédit) |
|---|---|---|
| 2025-11-01 | Jour férié (Toussaint) tombant un samedi | +8,0 GW |
| 2025-11-23 → 2025-11-28 | Vague de froid fin novembre (plusieurs jours consécutifs) | +4,9 à +6,3 GW |
| 2025-05-29 | Jour férié (Ascension) | +5,8 GW |

Deux familles d'erreurs se dégagent nettement :
1. **Les jours fériés qui tombent un week-end ou en position atypique** : l'effet férié
   est capturé de façon uniforme par le modèle, alors que son impact réel dépend du jour
   de la semaine sur lequel il tombe.
2. **Les vagues de froid prolongées** : le résidu reste positif (conso sous-estimée)
   plusieurs jours d'affilée fin novembre 2025, ce qui suggère un effet non-linéaire —
   un froid qui *dure* fait davantage monter la conso qu'un froid ponctuel de même
   intensité (relance du chauffage électrique dans des bâtiments qui se sont refroidis,
   effet cumulatif que les seuls degrés-jours du jour même ne capturent pas).

## 6. Limites

- **Proxy de température, pas le maillage officiel RTE.** 11 villes pondérées par
  population régionale plutôt que le maillage RTE/Météo-France pondéré par la
  consommation réelle de chaque zone. Ordre de grandeur correct, mais pas la précision
  d'un modèle industriel.
- **Tendance annuelle linéaire.** Le modèle suppose une évolution linéaire de la
  consommation structurelle (efficacité énergétique, sobriété). Or la baisse de
  consommation liée à la crise énergétique 2022-2023 n'a pas continué au même rythme en
  2025 — les résidus du test 2025 sont légèrement biaisés positivement (conso
  légèrement sous-estimée), signe que l'extrapolation linéaire de la tendance a ses
  limites au-delà de l'horizon d'entraînement.
- **2020 exclu** de l'entraînement (confinements COVID, conso déconnectée de la météo) :
  choix de modélisation assumé plutôt que méthode automatique de détection d'anomalies.
- **Pas de vacances scolaires** dans le modèle, faute de source ouverte simple à
  intégrer — une partie de la variance résiduelle inter-semaine vient probablement de là.
- **Relation HDD/CDD linéaire par morceaux**, alors que l'effet d'une vague de froid
  *prolongée* semble non-linéaire (cf. section 5) — un modèle avec une variable de froid
  cumulé (ex. moyenne mobile des HDD sur 3-5 jours) capturerait probablement mieux ces
  épisodes.

## 7. Lien avec le métier de pricing analyst

Un coefficient de thermosensibilité chiffré (**1,5 GW/°C en hiver**) transforme un aléa
météo en un **risque volume quantifiable** :

- **Prévision / forecast** : l'écart type de l'erreur de prévision (~2-2,5 GW, ~4 % de
  la conso) donne un ordre de grandeur du risque à couvrir jour par jour sur un
  portefeuille de clients — c'est directement l'écart entre le forecast et la conso
  effective qu'un pricing analyst cherche à minimiser.
- **Risque volume vs risque prix** : quand il fait plus froid que prévu, un fournisseur
  qui a vendu un volume fixe à un client doit acheter le complément sur le marché spot —
  souvent au moment où les prix sont les plus hauts (forte demande système). La
  thermosensibilité chiffre donc directement l'exposition croisée volume × prix qu'un
  pricing analyst doit intégrer dans la prime de risque d'une offre à prix fixe.
- **Structuration produit** : connaître la forme en "U" (chauffage l'hiver, clim l'été,
  faible en mi-saison) aide à calibrer des produits indexés climat ou des clauses de
  révision, et à dimensionner les couvertures (swaps, options) sur les mois les plus
  exposés.
