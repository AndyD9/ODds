# Pré-enregistrement 0002 — Le modèle bat-il la cote précoce ?

**Date d'enregistrement :** 2026-09-18
**Statut :** actif
**Enregistré avant :** tout chargement des colonnes PSH/PSD/PSA et tout calcul.

Fait suite au rejet de H1 et H2 (prereg 0001, research/RESULTS.md R5). Ce document existe parce
que le jeu de test a été consommé : réutiliser librement la même donnée après un premier verdict
est exactement ce que la discipline interdit.

---

## 1. Motivation

Battre la **clôture** est le test le plus dur qui existe : elle intègre toute l'information
arrivée jusqu'au coup d'envoi. Mais **on ne mise jamais à la clôture**. On mise à un prix
antérieur, et le cadre CLV du projet (PLAN §0.3) repose entièrement là-dessus.

Un modèle inférieur à la clôture peut donc produire un CLV positif s'il bat le prix auquel on
peut réellement miser. C'est la seule question que le rejet de H1 ne ferme pas.

## 2. Nature exacte de la donnée — à ne pas surinterpréter

Les colonnes `PSH`/`PSD`/`PSA` de football-data.co.uk sont des cotes Pinnacle relevées **en amont
du week-end** (relevés de milieu de semaine), et non l'ouverture stricte du marché.

Conséquences actées :

- on parlera de **cote précoce**, pas de cote d'ouverture ;
- l'écart réel entre ouverture stricte et clôture est donc **sous-estimé** par cette mesure ;
- ces colonnes n'existent **que dans les fichiers principaux** (19 championnats). Les fichiers
  « extra » ne portent que la clôture. L'analyse exclut donc les petits championnats.

## 3. Pronostic enregistré AVANT mesure

Écrit pour pouvoir être confronté au résultat, et pour rendre visible tout ajustement a
posteriori du discours :

```text
DC est à +2,25 % de log loss derrière la clôture (mesuré, R5).
Si la cote précoce est ~1 à 1,5 % derrière la clôture,
alors DC reste ~1 % derrière la cote précoce  ->  ECHEC attendu.

Probabilité subjective de succès annoncée a priori : ~20 %.
```

**Confrontation au résultat (2026-09-18).** Le pronostic était trop optimiste : la cote précoce
n'est qu'à **0,32 %** de log loss derrière la clôture, et non 1 à 1,5 %. L'écart entre prix
précoce et clôture est donc bien plus faible qu'annoncé, ce qui rend le rejet de H5 d'autant plus
net. Le pronostic écrit à l'avance rend cette erreur visible plutôt que rétroactivement lissée.

## 4. Protocole

Exécuté dans cet ordre. Aucune étape n'est réordonnée après avoir vu un résultat.

| Étape | Contenu | Jeu de données |
|---|---|---|
| 1 | Charger `PSH`/`PSD`/`PSA` dans le schéma | — |
| 2 | **Mesure** : écart de calibration cote précoce vs clôture, par championnat | train + validation |
| 3 | **Test de H5** : DC bat-il la cote précoce ? | **validation uniquement** |
| 4 | Si H5 rejetée → arrêt, conclusion définitive | — |
| 5 | Si H5 acceptée → concevoir une confirmation propre dans un prereg 0003, **sans réutiliser le test consommé par H1** | — |

**Aucun paramètre n'est réajusté.** La configuration Dixon-Coles reste gelée telle qu'issue de la
validation du prereg 0001 : demi-vie 365 j, ridge 1.0, refit 30 j, dévig Shin. C'est ce qui rend
l'étape 3 légitime sur la validation : il n'y a rien à surajuster.

## 5. Hypothèses

| # | Hypothèse | Test | Seuil | Résultat |
|---|---|---|---|---|
| H5 | Dixon-Coles bat la cote précoce Pinnacle dévigée, en Brier | Δ Brier < 0, IC95 bootstrap par blocs excluant 0 | n ≥ 500 (voir amendement) | **REJETÉE** — +0,012474, IC95 [+0,010377, +0,014659], n = 14 121 |
| H6 | La cote précoce est moins bien calibrée que la clôture (contrôle de cohérence) | Δ Brier > 0, IC95 excluant 0 | n ≥ 500 | **CONFIRMÉE** — +0,002110, IC95 [+0,001720, +0,002528], n = 77 609 |

### Amendement du 2026-09-18, AVANT tout calcul de H5

La version initiale de ce document exigeait n ≥ 20 000. Ce chiffre était **reporté à tort** de
H1 : il provient du calcul de puissance sur le **ROI** (prereg 0001 §2), et ne s'applique pas à
une comparaison de **calibration**. Le seuil applicable, fixé dans prereg 0001 §2 pour
« comparaison de calibration (Brier / log loss) », est **500**.

Données disponibles : 90 504 matchs portent à la fois cote précoce et clôture, sur 19
championnats principaux. La fenêtre de validation en compte ~13 700 — bien au-dessus du seuil
applicable, en deçà du seuil erroné.

L'amendement est enregistré **avant** toute exécution de H5. Il corrige une erreur de rédaction,
il ne relâche pas une contrainte devenue gênante au vu d'un résultat.

**Reporting imposé :** le résultat primaire est celui de la validation. Le même calcul sur
train + validation (~77 000 matchs) sera reporté en secondaire et explicitement étiqueté comme
tel — les prédictions de la période d'entraînement sont hors échantillon par construction
(walk-forward), mais les hyperparamètres ont été choisis sur la validation, ce qui les rend moins
propres.

H6 est un **contrôle**. Si la cote précoce n'était pas mesurablement moins bonne que la clôture,
la prémisse même de H5 s'effondrerait et le résultat de H5 serait ininterprétable.

## 6. Sous-produit à conserver quel que soit le verdict

La carte, par championnat, de l'amélioration entre cote précoce et clôture. Elle répond à une
question indépendante de tout modèle :

> Quelle part de l'information arrive tard ?

Un championnat à faible écart a un prix précoce déjà efficient. Un championnat à fort écart porte
de l'information tardive qu'un modèle sur données publiques n'aura jamais. Cette carte reste
utile pour toute stratégie ultérieure, y compris un pivot vers des données propriétaires.

## 7. Critère d'arrêt

```text
Si H5 est rejetée :
  → la question du projet est close.
  → atterrissage : outil personnel d'analyse et de calibration
    (dévig, calibration, cartographie), sans prétention à battre le marché.
  → le pivot vers des données propriétaires ne serait envisagé
    qu'après chiffrage préalable.
```

## Journal des modifications

| Date | Modification | Raison |
|---|---|---|
| 2026-09-18 | Création | Suite au rejet de H1/H2. |
| 2026-09-18 | H5 REJETÉE, H6 CONFIRMÉE. Critère d'arrêt §7 déclenché. | Résultats dans research/RESULTS.md (R7, R8). |
| 2026-09-18 | Seuil H5/H6 corrigé de 20 000 à 500, AVANT tout calcul | Le 20 000 provenait d'un calcul de puissance sur le ROI et ne s'applique pas à une comparaison de calibration (prereg 0001 §2). Erreur de rédaction, corrigée avant exécution. |
