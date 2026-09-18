# ODds — analyse des probabilités de marché

Outil d'analyse des cotes sportives : retirer correctement la marge d'un livre, mesurer la
calibration réelle du marché, cartographier les championnats.

## Ce que l'outil fait — et ne fait pas

**Il ne produit aucun signal de pari.** Ce n'est pas une limitation temporaire, c'est une
conclusion mesurée.

Le projet a commencé comme un moteur de probabilités destiné à détecter des écarts exploitables.
La première étape a consisté à tester cette hypothèse avant de construire quoi que ce soit.
Résultat, sur 150 626 matchs et 23 championnats ([research/RESULTS.md](research/RESULTS.md)) :

| Hypothèse | Verdict |
|---|---|
| Dixon-Coles bat la clôture Pinnacle | **Rejetée** — +0,0151 de Brier, 0 championnat sur 23 |
| L'écart est meilleur sur les petits championnats | **Rejetée** — corrélation marge/écart = +0,057 |
| Le modèle apporte de l'information orthogonale | **Rejetée** — poids de mélange négatif |
| Dixon-Coles bat la cote précoce | **Rejetée** — 5,9× l'information tardive totale |
| Shin calibre mieux que la normalisation proportionnelle | **Confirmée** |

Un modèle de comptage sur données publiques ne bat ni la clôture, ni le prix précoce, nulle part.
Ce qui reste — et qui est réel — est outillé ici.

## Installation

```bash
uv sync --extra dev
```

### Configuration (optionnelle)

Nécessaire seulement pour brancher une API de cotes. La source gratuite
football-data.co.uk fonctionne sans aucune clé.

```bash
uv run odds config --init     # crée .env à partir de .env.example
uv run odds config            # état de la configuration, clés masquées
```

`.env` est dans `.gitignore`. **Ne collez jamais une clé dans un message, un ticket ou une
capture d'écran** : elle est utilisable telle quelle par quiconque la lit. `odds config`
n'affiche jamais qu'un masque (`abcd**********efgh`), et un test vérifie que la valeur en clair
ne peut pas fuiter dans cette sortie.

| Réglage | Rôle |
|---|---|
| `ODDS_API_KEY` | Clé The Odds API — [offre gratuite, 500 crédits/mois](https://the-odds-api.com/#get-access) |
| `ODDS_API_SPORTS` | Championnats interrogés (1 crédit chacun par passe) |
| `ODDS_API_REGIONS` | `eu` (Pinnacle, Betfair…), `uk`, `us`, `au` |
| `ODDS_API_MARKETS` | `h2h` (1X2), `totals`, `spreads` |
| `ODDS_API_BUDGET_JOUR` | Garde-fou en crédits par jour |

`odds config` calcule le coût d'une passe et le nombre de passes quotidiennes que le budget
autorise, puis avertit si la configuration dépasse les 500 crédits mensuels de l'offre gratuite.
Le tarif est de **1 crédit par championnat × par marché × par région** ; `/events` et `/sports`
sont gratuits et illimités.

## Utilisation

### Retirer la marge d'un livre

```bash
uv run odds devig 1.80 3.60 4.80
```

Compare les quatre méthodes (Shin, power, odds ratio, proportionnelle), donne la cote juste, et
chiffre l'erreur que commettrait la normalisation proportionnelle.

### Tableau de bord

```bash
uv run odds app
```

Six pages : **matchs par date**, dévig interactif, calibration du marché, cartographie,
explorateur de matchs, suivi de la collecte.

> Après modification d'un module sous `src/`, redémarrer l'application : Streamlit recharge le
> script mais pas les modules importés.

#### Matchs par date

Choisissez une date, l'analyse est calculée automatiquement pour tous les matchs du jour. La
source bascule toute seule :

| Date | Source | Contenu |
|---|---|---|
| couverte par la collecte | `odds_history.db` | jusqu'à 8 bookmakers, dernière cote observée |
| sinon | `matches.parquet` | clôture Pinnacle, score et résultat connus |

Filtre par championnat, et tous les matchs de la journée pour ceux retenus.

#### Pourquoi une date à venir peut être vide

football-data **ne publie ses fixtures que deux fois par semaine environ** : une fois en milieu
de semaine, une fois avant le week-end. Entre deux publications, aucune date à venir n'apparaît,
et il n'existe donc **pas de fenêtre glissante de « matchs du jour » en continu** avec cette
source gratuite.

L'outil affiche en permanence la fraîcheur du flux amont (date de publication, âge, période
couverte) et explique une journée vide au lieu de la laisser sans motif. Le collecteur horaire
prend la publication suivante automatiquement.

Pour une couverture quotidienne réelle, il faut une API de cotes dédiée — c'est l'option B de
[`PLAN.md`](PLAN.md) §7.2, explicitement différée après le rejet de H1.

#### « Quelle issue choisir ? » — deux lectures, jamais une seule

L'outil affiche **deux** colonnes qui répondent à des questions différentes et se contredisent
régulièrement :

| | Question | Statut |
|---|---|---|
| **① Marché** | Quelle issue le marché juge-t-il la plus probable ? | Lecture factuelle. **Pas une recommandation** : au prix juste, miser sur le favori a une espérance nulle. |
| **② Prix** | Où le meilleur prix disponible s'écarte-t-il le plus du consensus ? | Price shopping. Observation sur la dispersion des prix, **pas une prédiction**, et biaisée à la hausse. |

Le biais de ② mérite d'être compris : prendre le maximum sur N bookmakers retient
disproportionnellement la cote périmée ou erronée, et l'effet est maximal sur les gros outsiders.
Exemple réel du 2026-09-16 : sur Barcelone–Santander, ① donne la victoire à domicile à 91,8 %,
tandis que ② pointe le **nul** à la cote 21,00 avec +11,8 % — un prix isolé sur une issue à 4 %,
c'est-à-dire le cas où l'indicateur est le moins fiable.

Une colonne « Accord » signale les divergences, et un avertissement compte combien de matchs du
jour sont concernés.

Un `⌀` devant un nom indique un **agrégat de marché**, pas un bookmaker : la cote existe quelque
part, mais il faut consulter le tableau livre par livre pour savoir chez qui.

Pour chaque match : probabilités dévigées, cotes justes, marge, nombre de bookmakers, dispersion
entre eux. Le détail d'un match donne le tableau livre par livre et un nuage de points de la
dispersion.

**Sur la dispersion et le « meilleur écart ».** La dispersion mesure le désaccord entre
bookmakers à un instant — c'est un indicateur d'incertitude du marché, pas d'opportunité. Le
meilleur écart vaut `(probabilité consensus x meilleure cote) − 1` : c'est du **price shopping**,
une observation factuelle sur la dispersion des prix, jamais une prédiction. Il est de surcroît
biaisé à la hausse, puisque prendre le maximum sur N bookmakers retient disproportionnellement la
cote périmée ou erronée.

Deux entrées sont volontairement **exclues du consensus** : les agrégats de marché (`_max`,
`_moyenne`), qui ne sont pas des bookmakers, et les cotes relevées à un autre instant
(`pinnacle_precoce`), qui sont le même book plus tôt. Les inclure gonflait la dispersion et
faisait apparaître comme « meilleur prix » une cote qui n'était plus disponible.

### Collecte de cotes en continu

```bash
uv run odds collect            # une passe
uv run odds collect --resume   # état de l'historique
```

Pinnacle n'étant plus publié après le **2026-01-14**, aucune mesure en avant n'est possible sans
un historique que l'on constitue soi-même. La collecte ne coûte rien mais prend des mois : elle
doit tourner avant qu'on en ait besoin.

Deux sources alimentent la collecte :

| Source | Cadence | Bookmakers | Clé requise |
|---|---|---|---|
| **The Odds API** | continue | ~24, dont **Pinnacle** et **Betfair Exchange** | oui |
| football-data.co.uk | 2×/semaine | 8, sans Pinnacle depuis 2026-01 | non |

The Odds API ramène Pinnacle, perdu en janvier. Le tableau de bord la préfère quand elle couvre
la date demandée. **Les deux sources ne sont jamais mélangées** : les noms d'équipe diffèrent et
un appariement approximatif créerait des doublons silencieux.

#### Économie de crédits

L'offre gratuite donne 500 crédits/mois. Le tarif est de 1 crédit par championnat × marché ×
région, et un appel renvoie **tous** les matchs à venir du championnat.

La passe interroge d'abord `/events`, **gratuit et illimité**, pour savoir quels championnats
jouent réellement dans les 36 h — puis ne dépense un crédit que sur ceux-là. Un championnat au
repos ne coûte rien. `ODDS_API_BUDGET_JOUR` plafonne la consommation quotidienne, et la passe
s'arrête net une fois le plafond atteint.

> **Les tests ne consomment jamais de crédits.** `tests/conftest.py` neutralise la configuration
> et bloque la couche réseau du client pour toute la suite. Sans ce garde-fou, lancer les tests
> dépensait de l'argent réel — c'est arrivé, pour ~100 crédits.

Stockage : `research/data/odds_history.db` (SQLite), format long — une ligne par
(match, bookmaker, marché, sélection, instant). `observed_at` est **notre** horodatage UTC, pas
celui du match : c'est la seule date qui autorise un backtest honnête. Seuls les **changements**
sont écrits, l'historique est donc une série de mouvements et non un journal de sondages.

#### Planification

Un agent `launchd` collecte toutes les heures :

```bash
launchctl list | grep odds                  # état
tail -f logs/collect.log                    # journal
```

Pour le désinstaller :

```bash
launchctl unload ~/Library/LaunchAgents/com.odds.collect.plist
rm ~/Library/LaunchAgents/com.odds.collect.plist
```

### Autres commandes

```bash
uv run odds ingest                          # télécharger / mettre à jour les données
uv run odds carte                           # marges et information tardive par championnat
uv run odds calibration --championnat E0    # calibration réelle du marché
uv run odds calibration --depuis 2020-01-01 --methode power
```

## Pourquoi le choix de la méthode de dévig compte

`1 / cote` n'est pas une probabilité : la somme dépasse 1. La normalisation proportionnelle
(`p / Σp`) redistribue cet excédent uniformément — ce qui est faux, car la marge est concentrée
sur les outsiders.

Mesuré sur 128 734 matchs :

| Plage de probabilité | Erreur de la proportionnelle vs Shin |
|---|---|
| 0 – 5 % | **+16,6 %** en relatif |
| 10 – 20 % | +2,5 % |
| 70 – 100 % | −1,3 % |

L'écart de calibration agrégée entre méthodes est négligeable. Mais le choix décide **d'où l'on
croirait avoir de l'edge** : bâti sur la proportionnelle, un moteur signalerait des opportunités
systématiques et entièrement fictives sur les outsiders.

## Données

[football-data.co.uk](https://www.football-data.co.uk) — 159 671 matchs, 35 championnats,
2012 → 2026, dont 150 626 avec cotes de clôture Pinnacle.

**Attention :** Pinnacle closing n'est plus publié sur cette source après le **14 janvier 2026**.
L'historique reste complet, mais aucune mesure en avant ne peut s'y appuyer.

## Structure

```text
src/odds/
├── market/devig.py          Shin, power, odds ratio, proportionnelle (scalaire + vectorisé)
├── data/footballdata.py     ingestion et normalisation
├── models/football/         Dixon-Coles (time decay, shrinkage, pyramides)
├── pit/walk_forward.py      harnais point-in-time
├── backtest/                découpage temporel, Brier, log loss, bootstrap par blocs
├── config.py                configuration locale (.env), secrets masqués
├── data/oddsapi.py          client The Odds API, budget et /events gratuit
├── data/collect.py          collecte propre, horodatée, dédupliquée
├── analysis.py              noyau partagé CLI / tableau de bord
└── cli.py

app/dashboard.py             tableau de bord Streamlit
prereg/                      hypothèses pré-enregistrées, datées, avec leurs verdicts
research/RESULTS.md          journal des résultats mesurés
tests/                       182 tests, dont le test anti-fuite
```

## Tests

```bash
uv run pytest
```

Le test central est [`tests/test_no_lookahead.py`](tests/test_no_lookahead.py) : il vérifie que
les prédictions d'une période sont **bit pour bit identiques** selon que le jeu de données
contient ou non des matchs postérieurs. Sans cette garantie, tout résultat de backtest serait
décoratif.

## Méthode

Le répertoire [`prereg/`](prereg/) contient les hypothèses écrites **avant** de voir les
résultats : seuils d'échantillon, découpage temporel, critères d'acceptation, et même le
pronostic subjectif de l'auteur. Le journal en fin de chaque fichier exige une raison écrite pour
toute modification — « les résultats sont décevants » n'en est pas une.

C'est ce dispositif qui a permis de répondre à la question du projet en une session, plutôt que
de la découvrir après six mois d'infrastructure.
