# Pré-enregistrement 0001 — Seuils, staking et mode d'exploitation

**Date d'enregistrement :** 2026-09-18
**Statut :** actif
**Enregistré avant :** tout chargement de données, tout backtest, tout résultat.

Ce document fixe des valeurs **avant** d'avoir vu le moindre résultat. C'est sa seule raison
d'être. Un seuil choisi après coup n'est pas un seuil, c'est une justification.

---

## 1. Benchmark

| Paramètre | Valeur |
|---|---|
| Book de référence | Pinnacle, cotes de clôture |
| Colonnes source | `PSCH` / `PSCD` / `PSCA` (football-data.co.uk) |
| Méthode de dévig du benchmark | Shin |
| Métrique primaire | Brier score |
| Métrique secondaire | Log loss |
| Intervalles de confiance | bootstrap par blocs temporels, 95 % |

Le book de référence est fixé. En changer parce qu'un autre donne un écart plus favorable
constitue du surapprentissage et invalide le résultat.

---

## 2. Seuils de taille d'échantillon (N_min)

Aucune décision, aucun affichage, aucune affirmation sous ces seuils.

| Usage | N_min |
|---|---|
| Comparaison de calibration (Brier / log loss) | 500 |
| Affichage d'une cellule en interface | 2 000 |
| Toute affirmation portant sur le ROI | 20 000 |
| Promotion d'un challenger en champion | 5 000 sur données non vues |

### Justification du seuil ROI

Pour détecter un ROI de +2 % avec σ ≈ 1 par pari, à 95 % de confiance et 80 % de puissance :

```
n = (1,96 + 0,84)² × σ² / µ² = 7,85 / 0,0004 ≈ 20 000
```

En dessous, un ROI observé n'est pas distinguable de zéro. Il ne peut donc justifier aucune
décision, quel que soit son signe.

### Couverture du benchmark — constat du 2026-09-18

Pinnacle closing est disponible sur football-data.co.uk **du 2012-03-02 au 2026-01-14**
(150 626 matchs). Au-delà, la colonne est vide puis absente des fichiers ; seule la moyenne de
marché (`AvgCH`) subsiste.

Conséquences actées :

- l'étape 1 est intégralement réalisable (150 626 matchs, largement au-dessus des seuils) ;
- **aucune mesure en avant ne pourra utiliser Pinnacle depuis cette source** ;
- la collecte propre de cotes (PLAN §7.2, option A) devient urgente et non plus prudente.

---

## 2bis. Découpage temporel — figé le 2026-09-18

```
train      : date <  2022-01-01        105 617 matchs
validation : 2022-01-01 -> 2024-01-01   23 117 matchs
test       : date >= 2024-01-01         21 892 matchs
```

Bornes choisies sur la seule base de la **couverture des données**, avant tout ajustement de
modèle et avant tout résultat. Critère : maximiser l'entraînement sous la contrainte que le test
dépasse le seuil de 20 000 exigé pour toute affirmation portant sur le ROI.

Ces bornes sont fermées. Les déplacer après avoir vu un résultat invaliderait le test.

---

## 3. Discipline de test

1. Le jeu de **test** n'est touché **qu'une fois par version de modèle**.
2. Toute exploration, tout réglage, toute calibration se font sur la **validation**.
3. Correction Benjamini-Hochberg sur toute analyse multi-cellules exploratoire.
4. Les hypothèses testées sont listées ici avant exécution (section 6).
5. Reconstruction point-in-time stricte : aucune feature avec `availability_time >= t`.
6. Le test anti-lookahead (`tests/test_no_lookahead.py`) doit passer avant tout backtest publié.

---

## 4. Staking

| Paramètre | Valeur |
|---|---|
| `f_base` | **0.10** |
| Plafond par match | 1 % de bankroll |
| Plafond d'exposition simultanée | 5 % de bankroll |
| Drawdown de réexamen | 20 % → arrêt et audit |

```
kelly_complet = (p × odds - 1) / (odds - 1)
f_effectif    = f_base × confiance(n, data_quality, incertitude_modèle)
mise          = bankroll × kelly_complet × f_effectif
```

### Règles

- `f_base` peut être **relevé** sur preuve chiffrée (§calibration empirique, étape 3).
- `f_base` ne peut **jamais être abaissé en réaction à une série de pertes** : le drawdown est
  déjà encaissé à ce moment, la baisse ne protège de rien et biaise le suivi.
- La fonction `confiance()` doit être définie et versionnée **avant** le premier backtest avec
  staking.

### Calibration empirique de `f_base` (étape 3)

Rejouer le backtest avec `f_base ∈ {0.05, 0.10, 0.25, 0.50, 1.00}`. Examiner la **distribution**,
pas la moyenne : bankroll terminale aux percentiles 5/50/95, drawdown maximum, temps passé sous
le point de départ. Décider sur le drawdown supportable.

---

## 5. Mode d'exploitation

**Papier uniquement.** Aucune mise réelle avant que toutes les conditions suivantes soient
simultanément remplies :

```
CLV moyen > 0 sur >= 1 saison complète mesurée EN AVANT
ET n >= 2 000 sélections
ET stabilité du CLV par trimestre (non porté par une seule période)
ET calibration hors échantillon tenue sur la même période
```

Le moteur de staking tourne intégralement en mode papier : mêmes calculs, mêmes plafonds, même
suivi de bankroll simulée. Seul le passage d'ordre est absent.

---

## 6. Hypothèses pré-enregistrées pour l'étape 1

Testées dans cet ordre, sur le jeu de test, une seule fois.

| # | Hypothèse | Test | Seuil | **Résultat** |
|---|---|---|---|---|
| H1 | Dixon-Coles time-decayed bat la clôture Pinnacle dévigée en Brier, toutes ligues confondues | Δ Brier < 0, IC 95 % excluant 0 | n ≥ 20 000 matchs | **REJETÉE** (2026-09-18) — Brier DC − marché = +0,0151, IC95 [+0,0129, +0,0174], n = 21 892 |
| H2 | L'écart au benchmark est plus favorable sur les ligues « extra » (petits championnats) que sur les 5 grands | Comparaison des Δ Brier par groupe, BH-corrigée | n ≥ 500 par groupe | **REJETÉE** — 0/23 championnats ; corrélation marge/écart = +0,057 |
| H3 | Shin calibre mieux que la normalisation proportionnelle sur le 1X2 | Δ Brier des probabilités de marché dévigées | n ≥ 20 000 | **CONFIRMÉE** — Shin < proportionnelle, IC95 excluant 0, n = 128 734 |
| H4 | L'écart au benchmark varie selon la plage de probabilité | Calibration par bins, BH-corrigée | n ≥ 500 par bin | Non exécutée — sans objet après rejet de H1 |

Toute hypothèse non listée ici et testée par la suite est **exploratoire** : elle ne peut pas
justifier une décision, seulement motiver un nouveau pré-enregistrement.

---

## 7. Critère d'arrêt du projet

```
Si H1 est rejetée (le modèle ne bat pas la clôture dévigée) :
  → ne pas construire l'infrastructure
  → soit pivot vers une source de données propriétaire
  → soit redéfinition en outil personnel d'analyse et de calibration,
    sans prétention à battre le marché
```

---

## Journal des modifications

| Date | Modification | Raison |
|---|---|---|
| 2026-09-18 | Création | — |
| 2026-09-18 | H1 et H2 REJETÉES, H3 CONFIRMÉE. Critère d'arrêt §7 DÉCLENCHÉ. | Résultats consignés dans research/RESULTS.md (R3, R5, R6). Le jeu de test a été consommé pour H1 : toute nouvelle hypothèse exige un nouveau pré-enregistrement. |
| 2026-09-18 | Ajout §2bis (découpage temporel) et du constat de couverture Pinnacle | Bornes fixées d'après la disponibilité des données, avant tout résultat. Découverte que Pinnacle closing s'arrête au 2026-01-14 sur la source gratuite. |

Toute modification ultérieure exige une raison écrite ici. « Les résultats sont décevants » n'est
pas une raison.
