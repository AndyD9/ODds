# ODds — analyse des probabilités de marché

Outil d'analyse des cotes sportives : retirer correctement la marge d'un livre, mesurer la
calibration réelle du marché, cartographier les championnats.

## Ce que l'outil fait — et ne fait pas

Outil personnel à usage éducatif. Il affiche des probabilités et tient un carnet de paris **en
papier**. Il ne prétend pas détenir un avantage, et cette prudence n'est pas une posture : c'est
une conclusion mesurée, cinq fois.

Le projet a commencé comme un moteur de probabilités destiné à détecter des écarts exploitables.
La première étape a consisté à tester cette hypothèse avant de construire quoi que ce soit.
Résultat, sur 150 626 matchs et 23 championnats ([research/RESULTS.md](research/RESULTS.md)) :

| Hypothèse | Verdict |
|---|---|
| Dixon-Coles bat la clôture Pinnacle | **Rejetée** — +0,0151 de Brier, 0 championnat sur 23 |
| L'écart est meilleur sur les petits championnats | **Rejetée** — corrélation marge/écart = +0,057 |
| Le modèle apporte de l'information orthogonale | **Rejetée** — poids de mélange négatif |
| Dixon-Coles bat la cote précoce | **Rejetée** — 5,9× l'information tardive totale |
| Dixon-Coles apporte quelque chose sur les marchés de **buts** | **Rejetée** — perd sur tous les marchés, toutes les strates (R9) |
| Shin calibre mieux que la normalisation proportionnelle | **Confirmée** |

Un modèle de comptage sur données publiques ne bat ni la clôture, ni le prix précoce, nulle part
— et pas davantage sur les buts, y compris là où le marché ne cote rien. **Le prix reste la
meilleure information disponible.** Ce qui reste — et qui est réel — est outillé ici.

## Marchés de buts

L'outil répond à « quelle probabilité pour 3 buts ou plus ? » et « pour que cette équipe en
marque 2 ? ». Ces marchés ne sont pas cotés par les sources accessibles : ils sont **dérivés**
d'une matrice de score ajustée pour reproduire les prix réellement affichés.

La qualité de cette dérivation est mesurée, et affichée match par match :

| situation | écart mesuré entre probabilité annoncée et fréquence observée |
|---|---|
| une cote over/under contraint la matrice | **0,7 point** — la calibration du marché lui-même |
| dérivé du 1X2 seul, match équilibré (favori ≤ 60 %) | moins d'un point |
| dérivé du 1X2 seul, favori à 80 % et plus | 4 à 5 points, toujours en **surestimant** les buts |

D'où le réglage `ODDS_API_MARKETS=h2h,totals` : une cote de totaux améliore aussi les marchés
que personne ne cote — sur « le domicile marque 2 buts ou plus », l'erreur de calibration passe
de 0,021 à 0,007.

## Couvrir plusieurs issues

« Couvrir », c'est répartir la mise sur plusieurs issues **du même marché** pour perdre moins
quand celle qu'on visait ne sort pas. L'outil calcule toutes les couvertures possibles d'un
marché et dit, pour chacune, ce qu'elle gagne si elle sort, ce qu'elle perd sinon, et **ce
qu'elle vaut en moyenne** — parce qu'aucune répartition ne crée d'espérance : celle d'une
couverture est la somme de celles de ses jambes, et couvrir une issue sans valeur paie la marge
une fois de plus.

```bash
uv run odds couvrir 1.90 3.76 2.90                                   # au livre dévigé
uv run odds couvrir 1.90 3.76 2.90 --probas 0.58 0.24 0.18 --mise 10  # avec vos probabilités
```

Sur Monaco – Lens à 1,90 / 3,76 / 2,90 : couvrir les trois issues garantit une perte de 12,06 %
(la marge, payée d'avance) ; couvrir Monaco et le nul est un « double chance » fabriqué à la main
à 1,262 ; aucune répartition n'a d'espérance positive au prix du livre.

La seule répartition que le moteur de mise propose est le **Kelly simultané** (Smoczynski &
Tomkins, 2010) : il ne retient que les issues qui battent le marché une fois les autres prises
en compte, et pour une seule issue redonne exactement la formule de prereg 0001 §4. Il peut
couvrir une issue **sans valeur** quand la position sur les autres est grosse — c'est de la
variance rachetée, pas de la valeur, et l'interface le dit. Les plafonds de §4 s'appliquent à la
**somme** des jambes. Cadrage : [`prereg/0004-couverture.md`](prereg/0004-couverture.md).

Dans le tableau de bord, la carte « Couvrir plusieurs issues » du détail d'un match propose le
1X2, chaque ligne de total, les totaux par équipe et BTTS. Les jambes s'inscrivent au carnet sous
un même groupe et la page « Mes paris » les juge sur leur **net**, jamais jambe par jambe
([`decisions/0006`](decisions/0006-jambes-groupees.md)).

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

#### Pronostic et score de confiance

Pour chaque match, l'issue que le marché juge la plus probable, **avec la fiabilité mesurée de
ce niveau de probabilité**. Le score n'est pas une estimation : il est calculé sur les 150 626
matchs de l'historique à clôture Pinnacle, en comptant à quelle fréquence l'issue la plus
probable s'est réellement produite.

```text
Tranche annoncée   Réussite observée   n
   37,5 %               36,8 %       31 613
   42,4 %               42,8 %       30 749
   52,4 %               52,3 %       18 538
   62,3 %               62,5 %       10 505
   72,3 %               74,5 %        5 028
   82,2 %               83,6 %        2 174
   91,9 %               93,4 %          317
```

Deux enseignements, tous deux mesurés :

- **Le marché est remarquablement calibré.** L'écart entre probabilité annoncée et fréquence
  observée ne dépasse 2,2 points sur aucune tranche.
- **Le favori du marché ne l'emporte que 50,4 % du temps**, toutes tranches confondues. « Le plus
  probable » est très loin de « probable ».

| Niveau | Probabilité | Ce que ça vaut en pratique |
|---|---|---|
| 🟢 Très élevée | ≥ 85 % | se vérifie ~89–93 % du temps |
| 🔵 Élevée | 70–85 % | ~74–84 % |
| 🟡 Modérée | 60–70 % | ~62–68 % |
| 🟠 Faible | 50–60 % | ~52–58 % |
| 🔴 Très faible | < 50 % | l'issue la plus probable reste minoritaire |

Chaque ligne affiche aussi le **taux d'échec** : même un pronostic « très élevée » se trompe
environ 7 % du temps. Sur une date passée, une colonne indique si le pronostic s'est vérifié.

#### Dispersion des prix (analyse secondaire)

En annexe, l'outil montre où le meilleur prix disponible s'écarte du consensus des **autres**
bookmakers — une observation sur le désaccord entre opérateurs, sans rapport avec la probabilité
qu'une issue se produise. Trois filtres : consensus recalculé sans le book généreux, écart au
deuxième meilleur prix, et robustesse aux quatre méthodes de dévig.

Ce dernier filtre est le plus instructif. Le 2026-09-18, Bayern Munich – Union Berlin : le nul à
la cote 23,00 affichait +6,9 % d'écart. Recalculé sous les quatre méthodes, il va de −16,8 % à
+29,4 %. Le chiffre mesurait le choix de méthode, pas le marché — conséquence directe de R3, où
les méthodes divergent de 16,6 % en relatif sous 5 % de probabilité.

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
uv run odds credits            # crédits restants et projection de fin de mois
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

Stockage : `data/odds_history.db` (SQLite), format long — une ligne par
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
├── chemins.py               emplacements : data/ (état) et research/data/ (dérivé)
├── temps.py                 horodatages UTC, un format par usage
├── config.py                configuration locale (.env), secrets masqués
├── market/devig.py          Shin, power, odds ratio, proportionnelle (scalaire + vectorisé)
├── market/couverture.py     partitions du catalogue, dutching, Kelly simultané
├── market/vocabulaire.py    traduction unique code de pari <-> (market, selection) collecté
├── data/footballdata.py     ingestion et normalisation
├── data/oddsapi.py          client The Odds API, budget et /events gratuit
├── data/collect.py          collecte propre, horodatée, dédupliquée, ordonnancée
├── models/football/         Dixon-Coles ; catalogue des marchés de buts et matrice implicite
├── pit/walk_forward.py      harnais point-in-time
├── backtest/                découpage temporel, Brier, log loss, bootstrap par blocs
├── analysis/                noyau partagé CLI / tableau de bord
│   ├── base.py              historique, dévig d'un livre, calibration, cartographies
│   ├── sources.py           lecture des deux sources au format long
│   ├── consensus.py         matchs à une date : consensus, verdict, totaux (MatchsDuJour)
│   └── fiabilite.py         réussite mesurée par tranche, 1X2 et marchés de buts
├── paper.py                 carnet papier : staking prereg §4, couvertures groupées, règlement, CLV
├── app/                     tableau de bord Streamlit (dashboard, buts_ui, paris_ui, couverture_ui, theme)
└── cli.py

data/                        ÉTAT, à sauvegarder : paper.db, odds_history.db
research/data/               dérivé, régénérable : cache brut, parquet, tables de fiabilité
decisions/                   décisions techniques : contexte, options écartées, conséquences
prereg/                      hypothèses pré-enregistrées, datées, avec leurs verdicts
research/RESULTS.md          journal des résultats mesurés
tests/                       tests, dont le test anti-fuite
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
