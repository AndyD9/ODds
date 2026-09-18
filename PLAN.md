# Projet — Sports Probability Engine

> **Version 2** — révision du plan initial après revue critique.
> Changement principal : le plan ne commence plus par l'infrastructure, mais par le test qui
> détermine si le projet a un sens. Tout le reste est conditionné à ce résultat.
> Version 1 archivée : `~/Downloads/sports_probability_engine_plan.md`.

## Décisions actées — 2026-09-18

| Décision | Choix | Section |
|---|---|---|
| Source de cotes | **Option A** — gratuit (football-data.co.uk) + collecte propre démarrée immédiatement. Aucun abonnement avant le résultat de l'étape 1. | §7.2 |
| Book de référence | **Pinnacle closing**, dévigé par Shin | §0.2 |
| Staking | **Kelly fractionnaire, `f_base = 0.10`**, modulé par la confiance de cellule, plafonds 1 % / match et 5 % d'exposition simultanée | §15.1 |
| Mode d'exploitation | **Papier uniquement**, jusqu'à une saison complète de CLV positif en avant | §15.2 |
| Seuils N_min | 500 / 2 000 / 20 000 / 5 000 (voir `prereg/0001-seuils-et-staking.md`) | §11.2 |

Ces décisions sont fermées. Les rouvrir demande une raison écrite, pas un résultat décevant.

---

# 0. Hypothèse centrale et critère d'arrêt

Avant toute ligne de code d'infrastructure, le projet doit énoncer ce qu'il cherche à prouver.

## 0.1 Hypothèse

> Il est possible, à partir de données publiques ou accessibles, de produire des probabilités
> **mieux calibrées que la cote de clôture dévigée** sur au moins un sous-ensemble identifiable
> de compétitions et de marchés.

Cette hypothèse est probablement **fausse** sur les grands championnats et les marchés
principaux, où la clôture d'un book à forte liquidité intègre déjà les compositions, les
blessures, la météo et l'argent informé. Le projet consiste à déterminer s'il existe un
sous-ensemble où elle est vraie, et de combien.

## 0.2 Benchmark

Le benchmark n'est **pas** un baseline naïf (Elo simple, fréquences de base). Ces baselines sont
triviaux à battre et ne prouvent rien.

Le benchmark est **la cote de clôture Pinnacle, dévigée par Shin**. C'est la meilleure prévision
publique existante, elle est disponible gratuitement dans football-data.co.uk (colonnes
`PSCH` / `PSCD` / `PSCA`), et c'est la référence standard de la littérature.

Betfair SP est une alternative valable mais suppose de modéliser la commission et n'est pas
retenue à ce stade. Le book de référence est **fixé** : le changer en cours de route pour un book
plus flatteur est une forme de surapprentissage.

```text
Modèle validé  ⟺  Brier(modèle) < Brier(clôture dévigée)
                  ET l'intervalle de confiance de l'écart exclut 0
                  ET sur données strictement hors échantillon
```

## 0.3 Métrique opérationnelle : CLV, pas ROI

Le ROI converge trop lentement pour piloter des décisions (voir §11.1). La métrique de travail
est le **CLV** (closing line value) :

```text
CLV = (cote_prise / cote_clôture_dévigée) - 1
```

Un CLV moyen positif et stable est le signe d'un edge réel. Un ROI positif sur petit échantillon
ne l'est pas.

## 0.4 Critère d'arrêt (pré-enregistré)

À inscrire maintenant, à respecter plus tard :

```text
Si après l'étape 1 (§3) le modèle ne bat pas la clôture dévigée
en Brier score sur ≥ 20 000 matchs hors échantillon,
avec un écart significatif :

  → NE PAS construire l'infrastructure.
  → Soit pivoter vers une source de données propriétaire.
  → Soit redéfinir le projet comme outil personnel d'analyse
    et de calibration, sans prétention à battre le marché.
```

Sans critère d'arrêt écrit à l'avance, le projet s'ajuste indéfiniment.

---

# 1. Vision

Construire un moteur de probabilités sportives **mesurable, backtestable et transparent**,
capable d'analyser plusieurs sports à terme (football d'abord, puis éventuellement tennis,
hockey, basket).

Le moteur :

1. reconstruit un état du monde **point-in-time** (ce qui était connu à l'instant *t*) ;
2. produit une distribution de probabilités sur les issues d'un marché ;
3. la compare à la probabilité de marché **après retrait correct de la marge** ;
4. mesure sa propre calibration et son propre écart au benchmark ;
5. exprime l'incertitude de chaque estimation.

L'IA intervient uniquement pour **verbaliser des attributions calculées**, jamais pour produire
ou justifier une probabilité (§17).

> **Objectif réel :** savoir, chiffres à l'appui, si et où le modèle apporte quelque chose que le
> marché n'a pas déjà.

---

# 2. La tension centrale du projet

À énoncer explicitement, parce qu'elle conditionne toutes les décisions de périmètre :

```text
Grands championnats    → données riches, historique profond
                       → MAIS marché très efficient, edge quasi nul

Petits championnats    → marché plus faible, inefficiences plausibles
                       → MAIS données pauvres, historique court,
                         couverture statistique lacunaire,
                         limites de mise basses
```

Le projet ne consiste pas à choisir un côté, mais à **cartographier cet arbitrage** : pour chaque
compétition, mesurer conjointement la qualité des données et l'efficience du marché, et
identifier les zones où le rapport est favorable.

Cette cartographie est un livrable à part entière, indépendamment de tout signal exploitable.

---

# 3. Étape 1 — Le test de viabilité (2 semaines, sans infrastructure)

**C'est la première chose à faire.** Pas de Docker, pas de Postgres, pas de FastAPI, pas d'API
payante. Un notebook et des CSV.

## 3.1 Données

`football-data.co.uk` publie gratuitement, en CSV :

- une vingtaine de championnats européens ;
- résultats et statistiques de base depuis les années 1990 pour les principaux ;
- **cotes de clôture** (dont Pinnacle) sur 1X2, Over/Under 2.5 et handicap asiatique,
  sur la décennie récente.

C'est exactement le jeu de données nécessaire au test, et il est immédiatement disponible.

## 3.2 Protocole

```text
1. Charger 10 championnats × 15 saisons
2. Découpage temporel strict :
     entraînement  : saisons les plus anciennes
     validation    : saisons intermédiaires
     test          : saisons les plus récentes (touchées UNE SEULE FOIS)
3. Modèle : Dixon-Coles avec time decay ξ ajusté sur la validation
   - reconstruction point-in-time stricte (§13)
   - refit glissant, jamais de fit global
4. Dévig des cotes de clôture Pinnacle (`PSCH`/`PSCD`/`PSCA`)
   par la méthode de Shin (§9)
5. Comparaison :
     Brier(modèle)   vs  Brier(clôture dévigée)
     LogLoss(modèle) vs  LogLoss(clôture dévigée)
   avec intervalles de confiance (bootstrap par blocs temporels)
6. Décomposition de l'écart : par championnat, par marché,
   par plage de probabilité — en respectant §11.2
```

## 3.3 Sortie attendue

Un seul chiffre, avec son intervalle de confiance, et sa décomposition. Ce chiffre décide de la
suite du projet.

## 3.4 Ce qu'on apprend au passage

Même si le résultat est négatif, l'étape 1 produit :

- une implémentation Dixon-Coles validée et réutilisable ;
- une implémentation Shin validée ;
- un harnais de backtest point-in-time ;
- une première mesure de l'efficience de marché par championnat.

Aucun de ces éléments n'est perdu.

---

# 4. Principes du projet

## 4.1 Séparer les responsabilités

```text
1. Data (ingestion, validation, normalisation)
2. Point-in-time store (qu'est-ce qui était connu, et quand)
3. Modèles statistiques
4. Marché / dévig
5. Comparaison & dimensionnement
6. Backtesting
7. Calibration
8. API
9. Interface
10. Couche explicative
```

## 4.2 Ne jamais faire confiance à une probabilité non mesurée

Chaque probabilité doit pouvoir être expliquée, recalculée à l'identique, backtestée, comparée au
réel, et calibrée.

## 4.3 Toute feature a deux horodatages

**Règle dure, la plus importante du projet :**

```text
event_time         : quand l'événement a eu lieu
availability_time  : quand l'information est devenue disponible
```

Aucune feature ne peut entrer dans un modèle si `availability_time` n'est pas connu et antérieur
à l'instant de prédiction. Sans cette règle, le backtest est décoratif (§13).

## 4.4 La qualité des données fait partie de la sortie

Un modèle avec 15 saisons de données sur la Premier League et un modèle avec 2 saisons sur la
deuxième division chinoise ne peuvent pas être présentés avec la même confiance.

## 4.5 Pas d'abstraction avant deux cas d'usage

Une interface conçue avant d'avoir deux implémentations réelles est toujours la mauvaise (§14).

---

# 5. Architecture cible

L'interface commune est placée à la **couche marché**, pas à la couche modèle.

```text
                 SOURCES DE DONNÉES
        (CSV historiques, API, cotes)
                       │
                       ↓
            ┌──────────────────────┐
            │     Data Engine      │
            │  ingestion + valid.  │
            └──────────┬───────────┘
                       ↓
          ┌────────────────────────────┐
          │  Point-in-time store       │
          │  (event_time + avail_time) │
          └────────────┬───────────────┘
                       ↓
              Feature builder (as-of t)
                       │
                       ↓
        ┌──────────────────────────────┐
        │   Modèles (hétérogènes)      │
        │  DC bivarié / Markov /       │
        │  diffusion possessions ...   │
        └──────────────┬───────────────┘
                       ↓
        ┌──────────────────────────────┐
        │  INTERFACE COMMUNE ICI       │
        │  MarketProbabilities:        │
        │   {selection: p}             │
        │   + incertitude              │
        │   + qualité données          │
        └──────────────┬───────────────┘
                       ↓
              Dévig (Shin / power / prop.)
                       ↓
              EV% · Kelly · CLV
                       ↓
              Calibration
                       ↓
              Backtest / Reporting
                       ↓
              API → Interface → Explication
```

Le contrat commun n'est pas `predict(match_state)` — cette signature ne veut rien dire quand on
compare une chaîne de Markov point par point (tennis) à un modèle de comptage bivarié (football).
Le contrat est la **sortie** : une distribution nommée sur les issues d'un marché, accompagnée de
son incertitude et d'un score de qualité de données.

---

# 6. Stack technique

## Étape 1 (test de viabilité) — volontairement minimale

- Python, pandas, NumPy, SciPy
- Jupyter / notebooks
- Parquet ou CSV sur disque
- pytest sur les fonctions critiques (dévig, DC, point-in-time)

**Pas de Docker. Pas de Postgres. Pas de FastAPI. Pas de frontend.**

## Étape 2+ (uniquement si l'étape 1 est concluante)

### Backend
- FastAPI, Pydantic, SQLAlchemy, Alembic, asyncio

### Base de données
- PostgreSQL (partitionnement temporel sur les tables de snapshots)

### Frontend
- Étape 2 : Streamlit ou notebooks — 90 % de la valeur pour 5 % du travail
- Étape 4 seulement : Nuxt / Vue / TypeScript / ECharts

### Infrastructure
- Local + Docker d'abord
- VPS, worker d'ingestion, Redis : uniquement quand la collecte continue démarre

---

# 7. Sources de données

## 7.1 Le problème des cotes — à trancher maintenant

C'est le point le plus sous-estimé du plan initial. « Récupérer les odds » n'est pas une ligne de
checklist.

| Besoin | Disponibilité réelle |
|---|---|
| Cotes de clôture historiques, pré-match | **OK** via football-data.co.uk (gratuit, limité aux ligues européennes principales) |
| Cotes pré-match horodatées, multi-books, large couverture | Payant (OddsAPI, agrégateurs). Historique souvent superficiel. |
| Cotes **live** historiques | **Quasi inexistant** en accès standard. Betfair Historical Data est la voie sérieuse. |
| Cotes live temps réel | Faible chez les API sportives généralistes |

**Conséquence structurelle :** si l'historique de cotes live doit être auto-construit par
collecte, alors **le backtest live n'existera pas avant 12 à 18 mois**. La phase de backtest ne
peut pas valider la phase live ; ce sont deux projets séparés par un an de latence. Le plan doit
en tenir compte plutôt que de les enchaîner.

## 7.2 Décision actée — Option A

**Gratuit + collecte propre, démarrée immédiatement. Aucun abonnement avant le résultat de
l'étape 1.**

```text
MAINTENANT : football-data.co.uk (gratuit)
             → suffisant pour trancher l'hypothèse centrale
             → couvre AUSSI les fichiers "extra" : Danemark, Norvège,
               Suède, Finlande, Pologne, Roumanie, Autriche, Chine,
               Japon, Brésil, Argentine, USA
             → soit exactement les championnats visés en §2

EN PARALLÈLE : démarrer dès aujourd'hui la collecte propre de cotes,
               horodatée par nous (observed_at), sans en dépendre
               avant ~12 mois

PLUS TARD   : arbitrage B (API commerciale) vs C (Betfair Historical)
              UNIQUEMENT après l'étape 1, quand on saura OÙ est l'edge
```

### Pourquoi le choix est différé, et non indécis

Les deux options payantes ne résolvent pas le même problème :

```text
B — API commerciale      → historique vers l'AVANT, large couverture,
                           prix indicatifs. ~10-50 €/mois.
C — Betfair Historical   → historique vers l'ARRIÈRE, profond, prix
                           réellement négociables, MAIS couverture
                           proportionnelle à la liquidité de l'échange
                           (excellente sur les grands championnats,
                            très mince sur les petites ligues)
```

Règle de décision, à appliquer après l'étape 1 :

```text
edge sur petites ligues       → B  (l'échange y est trop mince pour C)
edge en live, grands champ.   → C  (seule voie pour un backtest live)
pas d'edge                    → ni l'un ni l'autre (§0.4)
```

Acheter avant l'étape 1 revient à dépenser à l'aveugle.

### Conséquence : la collecte propre commence maintenant

Le point crucial de l'option A est que **la collecte ne coûte rien mais prend du temps**. Elle
doit donc démarrer avant d'en avoir besoin :

- un job quotidien qui enregistre les cotes visibles, avec `observed_at` horodaté par nous ;
- au minimum : pré-match J-3, J-1, T-3h, T-1h, et dernière valeur avant coup d'envoi ;
- objectif : disposer d'un historique exploitable à l'étape 3, pas le commander en urgence.

C'est la seule tâche de l'étape 2 qui doit être avancée pendant l'étape 1.

## 7.3 Budget d'appels API — à chiffrer avant de dimensionner le live

Ordre de grandeur pour le live :

```text
30 matchs simultanés × 120 min × 1 appel/min  ≈ 3 600 appels
+ cotes (par book, par marché)                 ≈ ×N
```

À comparer au quota journalier de l'offre retenue. Ce calcul conditionne la faisabilité du §15,
il doit être fait avant d'écrire le worker.

---

# 8. Modèle de données

## 8.1 Principe transversal

Toute table d'observation porte `event_time` **et** `availability_time`, plus `source` et
`ingested_at`. Toute lecture par le feature builder se fait « as-of *t* ».

## Compétitions

```text
competition
├── id
├── name
├── country
├── sport
└── season
```

`data_quality` n'est **pas** un champ stocké : c'est une valeur **calculée** (§10), qui varie par
saison, par type de statistique, et selon la présence de cotes.

## Équipes / joueurs

```text
team                          player
├── id                        ├── id
├── name                      ├── name
├── country                   ├── team_id (historisé)
└── sport                     └── sport
```

## Match

```text
fixture
├── id
├── sport
├── competition_id
├── season
├── home_team_id
├── away_team_id
├── start_time
├── status
├── home_score
└── away_score
```

## Snapshot live

```text
live_snapshot
├── fixture_id
├── event_time
├── availability_time     ← nouveau, obligatoire
├── minute / period
├── score
├── statistics (jsonb)
├── xg_provider           ← nouveau : quel fournisseur, quelle version
└── ...
```

## Cotes

```text
odds_snapshot
├── fixture_id
├── observed_at           ← quand NOUS l'avons vue, pas quand le book l'a publiée
├── bookmaker
├── market
├── selection
├── odds
├── is_closing            ← nouveau
└── status
```

Partitionner `odds_snapshot` et `live_snapshot` par mois. Ordre de grandeur : 30 matchs × 120 min
× 10 books × 3 sélections ≈ 10⁵ lignes/jour pour le seul 1X2 live.

---

# 9. Dévig — Shin dès la V1

## 9.1 Pourquoi la normalisation proportionnelle est un piège

```text
P_raw    = 1 / odds
Overround = Σ P_raw
P_market = P_raw / Overround        ← BIAISÉ, directionnellement
```

La marge du bookmaker n'est pas répartie uniformément entre les issues : elle est concentrée sur
les outsiders (favourite-longshot bias). La normalisation proportionnelle **surestime donc
systématiquement la probabilité des outsiders**.

Conséquence : le moteur d'edge signalera de façon récurrente de fausses opportunités sur les
cotes élevées. On passerait des semaines à backtester un artefact de sa propre méthode de dévig.

### Amplitude du biais — mesurée, pas supposée

Mesures sur données synthétiques (`tests/test_devig.py`). Erreur relative commise par la
proportionnelle sur l'outsider, par rapport à Shin :

```text
À MARGE CONSTANTE (6 %) :
  2 issues, 50/50                  0,00 %   ← aucun biais
  8 issues, plat (.22 → .06)       3,58 %
  3 issues, 1X2 typique            3,76 %
  2 issues, 80/20                  9,00 %
  3 issues, gros favori (.78/.08) 13,76 %   ← maximum

À LIVRE CONSTANT (1X2 .55/.27/.18) :
  marge  2 %   → 1,27 %
  marge  6 %   → 3,76 %
  marge 15 %   → 9,10 %
  marge 25 %   → 14,62 %
```

Deux moteurs, et un faux ami :

1. **La marge**, de façon quasi linéaire.
2. **L'asymétrie du livre** : nul sur un livre parfaitement équilibré (proportionnelle et Shin
   coïncident exactement), maximal quand un favori marqué côtoie un outsider long.
3. **Le nombre d'issues n'est PAS un moteur** — intuition initiale, écartée par la mesure. Un
   marché à 8 issues plat est moins biaisé qu'un 1X2 à gros favori. Ce qui compte est la
   dispersion du livre, pas sa cardinalité.

### Enjeu chiffré

```text
1X2, marge 8 %, outsider à 18 % :
  proportionnelle  18,00 %
  Shin             17,10 %
  → faux edge      +0,90 point, TOUJOURS en faveur de l'outsider
```

À comparer aux edges réels recherchés, de l'ordre de 1 à 3 points : l'artefact représenterait une
fraction majeure du signal, et toujours dans le même sens. Sur les outsiders extrêmes, l'erreur
relative atteint 10-15 %, ce qui se traduit en EV fictive massive (l'EV étant multiplicative).

Ces propriétés sont verrouillées par des tests, dont un qui documente explicitement l'intuition
fausse (`test_le_nombre_dissues_nest_pas_le_moteur`).

## 9.2 Décision

Implémenter dès l'étape 1, et comparer leur calibration :

- **Shin** (~20 lignes avec `scipy.optimize`) — méthode par défaut
- **Power method**
- **Proportionnelle** — conservée uniquement comme référence de comparaison

La méthode retenue par marché est une décision **mesurée**, pas supposée.

---

# 10. Comparaison modèle / marché

## 10.1 Les bonnes unités

```text
fair_odds = 1 / P_model
EV%       = P_model × odds - 1
kelly     = (P_model × odds - 1) / (odds - 1)
CLV       = cote_prise / cote_clôture_dévigée - 1
```

`edge = P_model − P_market` (en points de probabilité) est **abandonné comme critère de tri**.

Raison : +8 points à P = 0,64 représente ~14 % d'EV ; +8 points à P = 0,05 en représente ~160 %.
Trier sur l'edge en points concentre mécaniquement les signaux là où le modèle est le moins
fiable. L'edge en points reste affiché à titre informatif, jamais comme critère.

## 10.2 Prix réel, pas prix affiché

`EV%` doit utiliser la cote **réellement accessible à la mise envisagée** — pas une cote agrégée
d'API, pas un maximum de marché théorique, et net de toute commission.

## 10.3 Affichage

```text
Probabilité modèle  : 64 %   [IC 58 – 70 %]
Marché dévigé (Shin): 56 %
Cote disponible     : 1.92

EV                  : +22,9 %
Kelly complet       : 24,9 %   →  Kelly/5 : 5,0 %

Qualité données     : 0,91
Confiance modèle    : élevée
n (échantillon cellule) : 4 312
```

---

# 11. Backtesting

C'est la partie centrale du projet, et la plus facile à faire mal.

## 11.1 Réalité de la puissance statistique

Pour détecter un ROI de +2 % avec un écart-type par pari σ ≈ 1 (ordre de grandeur pour des cotes
proches de l'even money), à 95 % de confiance et 80 % de puissance :

```text
n = (1,96 + 0,84)² × σ² / µ²
  = 7,85 / 0,0004
  ≈ 20 000 paris
```

**Vingt mille paris pour distinguer +2 % de zéro.** Par cellule d'analyse.

C'est la contrainte dominante du projet. Elle implique :

- le ROI **ne peut pas** piloter les décisions à court ou moyen terme ;
- la calibration (Brier, log loss) converge bien plus vite et doit être la métrique de pilotage ;
- le CLV est le meilleur proxy disponible d'un edge réel.

## 11.2 Discipline sur les découpages

Le découpage sport × championnat × marché × plage de probabilité crée des centaines de cellules,
chacune avec quelques dizaines d'observations. Avec assez de cellules, on trouvera toujours un
« championnat danois en Over 2.5 à +30 % de ROI ». C'est du bruit.

Règles :

```text
1. Les hypothèses testées sont PRÉ-ENREGISTRÉES (fichier versionné, daté)
2. Correction pour tests multiples (Benjamini-Hochberg) sur toute
   analyse exploratoire
3. AUCUNE décision sur une cellule sous N_min observations.
   Seuils FIXÉS le 2026-09-18, avant tout résultat :
     comparaison de calibration (Brier)   : n >=    500
     affichage d'une cellule en interface : n >=  2 000
     toute affirmation sur le ROI         : n >= 20 000
     promotion d'un challenger            : n >=  5 000 (données non vues)
   Référence : prereg/0001-seuils-et-staking.md
4. Le jeu de test final n'est touché QU'UNE FOIS par version de modèle
5. Toute exploration se fait sur la validation, jamais sur le test
```

## 11.3 Contenu d'un enregistrement de backtest

```text
fixture · timestamp · match_state (as-of)
market · selection
odds_disponible · odds_clôture
model_probability · market_probability (méthode de dévig)
model_uncertainty · data_quality
EV% · kelly · stake
final_result · pnl · clv
model_version · data_version
```

## 11.4 Métriques

Pilotage (converge vite) : Brier, log loss, courbe de calibration, ECE, CLV.

Suivi (converge lentement, ne décide de rien seul) : ROI, variance, drawdown, fréquence des
signaux.

---

# 12. Calibration

```text
Probabilité annoncée    Fréquence réelle
50 %                    ~50 %
60 %                    ~60 %
70 %                    ~70 %
80 %                    ~80 %
```

Techniques : Platt scaling, régression isotonique, calibration par bins.

**Règle :** la calibration s'ajuste sur le jeu de validation, jamais sur le test. Une calibration
ajustée sur le test rend le test inutilisable.

La calibration est évaluée séparément **par plage de probabilité** et **par marché** — un modèle
globalement calibré peut être fortement biaisé sur les extrêmes.

---

# 13. Fuites de données — règles dures

Le plan initial sous-estimait ce risque. Trois fuites concrètes, par ordre de gravité :

## 13.1 Modèles à état (Elo, Dixon-Coles)

Elo et DC sont **stateful**. Calibrer le decay, l'avantage domicile ou les forces d'attaque sur
l'ensemble des données puis « backtester » une période antérieure fait porter aux ratings de
l'information future.

**Règle :** au match *t*, tout est recalculé à partir des seules données dont
`availability_time < t`. Refit glissant, jamais de fit global suivi d'un backtest.

## 13.2 Compositions et blessures — fuite invisible

L'API renvoie la composition **finale** et les blessures **mises à jour rétroactivement**. Ce
n'est pas ce qui était connu une heure avant le coup d'envoi.

Ces features feront exploser les métriques en backtest et s'effondrer en production. C'est la
fuite la plus dangereuse parce qu'elle est silencieuse et flatteuse.

**Règle :** aucune feature de composition ou de blessure tant que la collecte propre en
temps réel n'a pas constitué son propre historique horodaté.

## 13.3 xG et statistiques dérivées

Les modèles xG sont recalculés rétroactivement par leurs fournisseurs. La valeur visible
aujourd'hui pour un match de 2021 n'est pas celle qui existait en 2021.

**Règle :** enregistrer le fournisseur et la version. À défaut de garantie, traiter le xG
historique comme une feature de recherche, pas de production.

## 13.4 Test de non-régression

Un test automatisé doit vérifier qu'aucun feature builder n'accède à une ligne dont
`availability_time >= t`. Ce test tourne en CI.

---

# 14. Architecture des modèles

Chaque sport a un modèle de nature différente :

```text
Football  : comptage bivarié (Poisson / Dixon-Coles)
Tennis    : chaîne de Markov point → jeu → set → match
Hockey    : comptage avec états spéciaux (power play)
Basket    : diffusion sur les possessions
```

Ils ne partagent **que** leur sortie. L'interface commune est donc :

```python
@dataclass
class MarketProbabilities:
    market: str
    probabilities: dict[str, float]   # selection -> p
    uncertainty: dict[str, float]     # intervalle par sélection
    data_quality: float
    model_version: str
    as_of: datetime
```

Cette interface ne sera **figée qu'après la deuxième implémentation réelle**. Écrire une classe
de base `ProbabilityModel` avec un `predict(match_state)` abstrait avant d'avoir deux modèles qui
tournent produit invariablement la mauvaise abstraction.

## 14.1 Football — le seul sport de l'étape 1 et 2

### V1 (étape 1)
Dixon-Coles : forces d'attaque/défense par équipe, avantage domicile, **time decay ξ ajusté**,
correction de dépendance sur les scores faibles, shrinkage vers la moyenne de la ligue pour les
promus et les petits échantillons.

Points souvent négligés et qui comptent davantage que la correction τ de Dixon-Coles 1997 :
le time decay, l'avantage domicile estimé par ligue (voire par équipe), et le shrinkage.

Sorties : `P(1)`, `P(X)`, `P(2)`, `P(Over 0.5 / 1.5 / 2.5)`, `P(BTTS)`.

### V2 (étape 2, conditionnelle)
xG, tirs, tirs cadrés, corners — **uniquement avec `availability_time` garanti** (§13.3).
Compositions et blessures : exclues jusqu'à disposer d'un historique propre (§13.2).

### V3 (live) — voir §15, repositionné

## 14.2 Autres sports

Tennis, hockey, basket : **hors périmètre** jusqu'à validation complète du pipeline football,
live compris. Les spécifications du plan initial sont conservées comme notes de recherche dans
`docs/futur/`, pas dans la roadmap.

---

# 15. Dimensionnement des mises et contraintes opérationnelles

Absent du plan initial. Un edge sans dimensionnement n'est pas une stratégie.

## 15.1 Staking — paramètres actés

```text
kelly_complet = (p × odds - 1) / (odds - 1)
f_effectif    = f_base × confiance(n, data_quality, incertitude_modèle)
mise          = bankroll × kelly_complet × f_effectif

f_base                        = 0.10
plafond par match             = 1 % de bankroll
plafond exposition simultanée = 5 % de bankroll
drawdown de réexamen          = 20 %  → arrêt et audit, pas ajustement
```

`f_base` pourra être relevé plus tard sur preuve. **Jamais abaissé en réaction à une série de
pertes** : on ne baisse `f` qu'après avoir déjà encaissé le drawdown, ce qui est le pire moment.

### Pourquoi 0,10 et pas le Kelly complet

Trois raisons distinctes, qui s'additionnent.

**(a) La courbe de croissance est brutalement asymétrique.**
Avec `g(f) = f·µ − f²σ²/2`, optimum en `f* = µ/σ²` :

```text
f = f*/2   →  g = 3µ²/8σ²  =  75 % de la croissance, ~50 % de la volatilité
f = f*     →  g = 4µ²/8σ²  = 100 %
f = 2f*    →  g = 0         =  ZÉRO croissance, variance maximale
```

Sur-miser d'un facteur 2 annule intégralement la croissance ; sous-miser de moitié coûte 25 %.
Comme `f*` réel est inconnu, la seule position raisonnable est nettement en dessous de
l'estimation.

**(b) Malédiction du vainqueur sur notre propre sélection.**
On ne mise que si `p_model > p_market`. C'est une sélection **sur l'erreur d'estimation** : les
paris retenus sont disproportionnellement ceux où l'erreur est allée dans le sens favorable.
L'edge réalisé est donc systématiquement inférieur à l'edge estimé, même avec un modèle non
biaisé en moyenne. Le facteur fractionnaire corrige ce biais de sélection — ce n'est pas
seulement de l'aversion au risque.

**(c) Kelly suppose des paris séquentiels indépendants.**
Un samedi, 30 positions simultanées et corrélées (même ligue, même journée, mêmes conditions).
Kelly ne gère pas ce cas. D'où le plafond d'exposition simultanée, indépendant du Kelly par pari.

### `f` n'est pas une constante

Une cellule à n = 200 ne mérite pas le même `f` qu'une cellule à n = 20 000. La fonction
`confiance()` doit être définie **avant** le premier backtest et versionnée dans `prereg/`.

### Calibration empirique de `f_base`

À l'étape 3, rejouer le backtest avec `f_base ∈ {0.05, 0.10, 0.25, 0.50, 1.00}` et examiner la
**distribution** (pas la moyenne) : bankroll terminale aux percentiles 5/50/95, drawdown maximum,
temps passé sous le point de départ. Le choix se fait sur le drawdown supportable, pas sur
l'espérance.

## 15.2 Mode d'exploitation acté — papier uniquement

**Aucune mise réelle avant une saison complète de CLV positif mesuré en avant.**

Raison : le CLV porte la même information que le ROI, converge environ dix fois plus vite (§11.1),
et ne coûte rien. Miser de l'argent avant, c'est payer pour une information disponible
gratuitement.

```text
Condition de sortie du mode papier (pré-enregistrée) :
  CLV moyen > 0 sur >= 1 saison complète en avant
  ET n >= 2 000 sélections
  ET stabilité du CLV par trimestre (pas porté par une seule période)
  ET calibration hors échantillon tenue sur la même période
```

Le moteur de staking (§15.1) est implémenté et exécuté intégralement en mode papier : mêmes
calculs, mêmes plafonds, même suivi de bankroll simulée. La seule différence est qu'aucun ordre
n'est passé. Cela garantit que le jour où la condition est remplie, rien n'est à construire.

## 15.3 Limitation de comptes

Contrainte matérielle, à intégrer dans le plan et non à découvrir en route : les bookmakers
classiques limitent rapidement les comptes gagnants. L'univers réellement exploitable se réduit
donc aux books à forte liquidité et aux échanges — c'est-à-dire précisément les marchés les plus
efficients.

C'est le cœur du paradoxe du projet : **là où l'on peut miser durablement, l'edge est le plus
difficile à obtenir**. À documenter, pas à contourner.

Conséquence directe du mode papier : ce point ne bloque rien aujourd'hui, mais il détermine
l'univers exploitable le jour où la condition de sortie est remplie. À instruire pendant la
période papier, pas après.

## 15.4 Cadre légal et fiscal

À clarifier selon la juridiction **avant la sortie du mode papier**, pas avant. Hors périmètre
technique, dans le périmètre du projet.

---

# 16. Données live — repositionnement

Le plan initial traitait le live comme l'objectif le plus attractif. C'est en réalité la partie
**la moins viable comme source de signal**.

## 16.1 Pourquoi

- Latence d'une API sportive généraliste sur les événements live : de l'ordre de la dizaine de
  secondes à la minute ; les statistiques arrivent encore plus tard.
- Quand le but apparaît dans le flux, le marché a déjà bougé.
- Le trading live est un jeu de latence, perdu structurellement face à des acteurs qui paient des
  flux à faible latence.
- L'historique de cotes live nécessaire au backtest n'existera pas avant ~12 mois de collecte
  (§7.1).

## 16.2 Positionnement retenu

Le live est développé comme **outil d'analyse et de replay**, pas comme moteur de signal :

- rejouer un match minute par minute ;
- mesurer la calibration des probabilités live a posteriori ;
- observer la dynamique de l'écart modèle / marché dans le temps ;
- constituer le dataset qui permettra, dans 12–18 mois, de trancher sérieusement la question.

Si un signal live exploitable apparaît, ce sera une conclusion de ces mesures — pas une hypothèse
de départ.

## 16.3 Pipeline

```text
API → Ingestion → Validation → Normalisation
    → Stockage horodaté (event_time + availability_time)
    → Snapshot
    → Probability Engine
    → Market Engine
    → Mesure (pas signal)
```

---

# 17. Apprentissage continu

L'objectif n'est pas de maximiser les gains récents, mais d'améliorer la calibration hors
échantillon.

## 17.1 Boucle

```text
Nouveaux matchs
      ↓
Dataset enrichi (point-in-time)
      ↓
Réentraînement / recalibration    ← par lots, cadence fixée à l'avance
      ↓
Backtest hors échantillon
      ↓
Test pré-enregistré d'amélioration
      ├── NON → conserver le champion
      └── OUI → nouveau champion
```

## 17.2 Champion / Challenger

Le challenger ne remplace le champion que s'il démontre une amélioration **sur un test défini à
l'avance**, sur des données qu'il n'a jamais vues :

```text
Critère de promotion (à figer avant de lancer la comparaison) :
  Δ Brier < 0 avec IC excluant 0
  ET pas de dégradation de calibration sur une plage de probabilité
  ET n ≥ N_min
```

« Amélioration robuste » sans test spécifié n'est pas un critère.

Chaque version conserve : paramètres, date et période d'entraînement, features, version des
données, métriques, performance hors échantillon. Reproductibilité bit-à-bit exigée.

## 17.3 Découpage temporel

```text
2019 ───── 2023   → entraînement
2024 ───── 2025   → validation  (exploration, calibration, réglages)
2026 ────────────  → test       (touché une fois par version)
```

## 17.4 Anti-surapprentissage

À éviter : réentraîner après chaque pari ; ajuster après une série de pertes ; sélectionner les
périodes favorables ; optimiser sur le ROI d'un petit échantillon ; utiliser de l'information
future ; itérer sur le même jeu de test.

## 17.5 Modèles hiérarchiques par championnat

L'approche « modèle global + modèle spécifique » du plan initial est correcte, mais doit être
formulée comme un **modèle hiérarchique avec shrinkage** plutôt que comme des modèles séparés :
les paramètres d'une ligue à faible volume sont tirés vers la moyenne globale, proportionnellement
à leur incertitude. C'est ce qui empêche une petite ligue de produire des paramètres aberrants.

Le gain d'un niveau de spécialisation doit être **mesuré hors échantillon**, pas supposé.

---

# 18. Couche explicative (IA)

## 18.1 Le risque, énoncé clairement

Demander à un LLM « pourquoi la probabilité a évolué » sans lui fournir d'attribution calculée
produit des récits plausibles. Le danger n'est pas l'erreur ponctuelle : c'est qu'une explication
fluide rend un mauvais signal **convaincant**, et augmente la confiance exactement là où elle
devrait baisser.

## 18.2 Règle

```text
Données → Modèle → Probabilités → Dévig → EV/Kelly
                        ↓
              ATTRIBUTION CALCULÉE
      (décomposition du Δp par feature, contributions Shapley)
                        ↓
                  LLM : verbalisation uniquement
```

Le LLM ne reçoit que des attributions numériques et les verbalise. Il ne produit aucun chiffre,
n'infère aucune cause, et n'a pas accès à une sortie qui ne soit pas déjà calculée.

Toute explication affiche **l'incertitude et la qualité des données** au même niveau visuel que la
conclusion.

## 18.3 Usages légitimes

Résumer les facteurs d'une attribution ; détecter des anomalies de données ; générer une synthèse
de match ; comparer deux versions de modèle sur des métriques fournies.

---

# 19. Interface

## Étape 2 — Streamlit / notebooks
Liste de matchs, probabilités, dévig, EV, courbes de calibration, résultats de backtest.
90 % de la valeur, 5 % du travail. Suffisant tant que le modèle n'est pas prouvé.

## Étape 4 — Nuxt / Vue (conditionnel)
Dashboard, page match, graphique d'évolution modèle / marché / résultat, WebSocket.

Un frontend complet avant un modèle validé est du temps investi dans la présentation d'un
résultat qui n'existe pas encore.

## Affichage obligatoire partout

Toute probabilité affichée est accompagnée de son intervalle, de la qualité des données, et de la
taille d'échantillon de la cellule dont elle relève.

---

# 20. Roadmap révisée (avec portes de sortie)

Chaque étape a une **condition de passage**. Si elle n'est pas remplie, on ne passe pas à la
suivante.

## Étape 1 — Test de viabilité (2 semaines) · SANS INFRA

- [ ] Charger football-data.co.uk (10 ligues × 15 saisons)
- [ ] Implémenter Shin + power + proportionnelle, tests unitaires
- [ ] Implémenter Dixon-Coles avec time decay et shrinkage
- [ ] Harnais de backtest point-in-time + test anti-fuite
- [ ] Brier / log loss modèle **vs clôture dévigée**, avec IC bootstrap
- [ ] Décomposition par ligue / marché / plage, sous discipline §11.2

**Porte :** le modèle bat-il la clôture dévigée, significativement, hors échantillon ?
→ NON : appliquer §0.4. → OUI : étape 2.

## Étape 2 — Industrialisation du cœur (conditionnelle)

- [ ] Repository, Docker, Postgres, Alembic, CI
- [ ] Schéma avec `event_time` / `availability_time`
- [ ] Ingestion API (fixtures, résultats, stats) + validation
- [ ] Collecte de cotes propre en continu — **option A actée, à démarrer dès l'étape 1**
- [ ] Arbitrage B vs C tranché à la lumière des résultats de l'étape 1 (§7.2)
- [ ] Portage du modèle et du backtester
- [ ] Calibration (Platt / isotonique) sur validation
- [ ] Interface Streamlit
- [ ] Cartographie qualité données × efficience marché par compétition (§2)

**Porte :** l'edge de l'étape 1 survit-il aux données réelles, à la marge réelle, et aux cotes
réellement accessibles ?

## Étape 3 — Extension et rigueur (conditionnelle)

- [ ] Features V2 avec disponibilité garantie
- [ ] Modèle hiérarchique par ligue avec shrinkage
- [ ] Champion / challenger avec test de promotion pré-enregistré
- [ ] Moteur de staking en **mode papier** (f_base = 0.10, plafonds §15.1)
- [ ] Suivi de bankroll simulée et de drawdown
- [ ] Calibration empirique de `f_base` sur la distribution des backtests
- [ ] Suivi CLV en continu

## Étape 4 — Live comme instrument de mesure

- [ ] Ingestion live horodatée, snapshots
- [ ] Moteur de replay minute par minute
- [ ] Mesure de calibration live
- [ ] Frontend Nuxt si justifié
- [ ] WebSocket

## Étape 5 — Ouverture (sous condition stricte)

- [ ] ML (gradient boosting) **en comparaison** au modèle classique, jamais en remplacement par défaut
- [ ] Couche explicative sur attributions calculées
- [ ] Deuxième sport — et seulement alors, figer l'interface commune (§14)

## Hors roadmap

Tennis, hockey, basket, ensemble models, alertes push : notes de recherche dans `docs/futur/`.

---

# 21. Structure du repository

```text
odds/
│
├── research/                  ← étape 1 vit ici
│   ├── notebooks/
│   └── data/                  (gitignored)
│
├── src/odds/
│   ├── data/                  ingestion, validation
│   ├── pit/                   point-in-time store & feature builder
│   ├── models/
│   │   └── football/
│   ├── market/                dévig (shin, power, proportional)
│   ├── edge/                  EV, kelly, CLV
│   ├── backtest/
│   ├── calibration/
│   ├── api/
│   └── core/
│
├── tests/
│   └── test_no_lookahead.py   ← test anti-fuite, en CI
│
├── registry/                  versions de modèles, métriques, params
├── prereg/                    hypothèses pré-enregistrées, datées
├── docs/
│   └── futur/                 tennis, hockey, basket
├── scripts/
├── migrations/
├── docker/
├── .env.example
├── pyproject.toml
└── README.md
```

`prereg/` et `registry/` ne sont pas décoratifs : ce sont eux qui rendent le projet honnête avec
lui-même.

---

# 22. Critères de réussite (chiffrés)

Le projet n'est pas réussi parce qu'il produit des probabilités.

1. **Le modèle bat-il la clôture dévigée ?** Brier inférieur, IC excluant 0, ≥ 20 000 matchs hors
   échantillon.
2. **Les probabilités sont-elles calibrées ?** ECE faible, et par plage de probabilité, pas
   seulement en agrégé.
3. **Le CLV moyen est-il positif et stable** sur les sélections retenues ?
4. **La performance varie-t-elle par championnat**, et les écarts sont-ils significatifs après
   correction pour tests multiples ?
5. **La cartographie qualité × efficience est-elle établie** pour les compétitions ciblées ?
6. **Le test anti-fuite passe-t-il** en CI, et les résultats sont-ils reproductibles bit-à-bit à
   partir de `registry/` ?
7. **La marge est-elle correctement retirée** — la méthode de dévig retenue est-elle celle qui
   calibre le mieux, mesurée et non supposée ?
8. **L'edge survit-il aux coûts réels** : cote effectivement accessible, commission, limites de
   mise ?
8bis. **La condition de sortie du mode papier est-elle remplie** (§15.2) — CLV positif, stable,
   sur une saison complète en avant ?
9. **Les probabilités live restent-elles calibrées** (mesuré, indépendamment de toute
   exploitation) ?

---

# 23. Ordre de priorité

```text
QUESTION DE VIABILITÉ   ← nouveau, et d'abord
       ↓
DONNÉES POINT-IN-TIME
       ↓
MODÈLE SIMPLE
       ↓
DÉVIG CORRECT (Shin)
       ↓
BACKTEST DISCIPLINÉ
       ↓
CALIBRATION
       ↓
INFRASTRUCTURE
       ↓
LIVE (comme mesure)
       ↓
ML
       ↓
EXPLICATION
       ↓
UI avancée
```

**Ne pas commencer par l'infrastructure, l'IA ou l'interface.**

L'infrastructure sert un edge démontré ; elle ne le crée pas. Le cœur de valeur du projet est la
qualité du dataset point-in-time et la capacité à produire des probabilités correctement
calibrées — et à savoir, honnêtement, quand ce n'est pas le cas.
