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
| `COMMISSION_EXCHANGE` | Votre commission sur les bourses d'échange, en % du gain (défaut : le taux de chaque bourse) |

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

#### Sûr et payant

Un pari à forte espérance tombe presque toujours sur un outsider — c'est mécanique, le favori est
le mieux coté par le marché. Pour qui veut d'abord un pari qui **passe**, l'outil affiche en tête
un second bloc, régi par deux seuils : le favori du marché en **confiance « élevée »**, soit
**70 % ou plus**, payé **1,25 net ou mieux**, au-dessus du consensus des autres livres, chez un
bookmaker réel. Le titre du bloc dit ce que ce niveau coûte, mesuré sur l'historique : **1 pari
sur 4 perd**.

Les deux seuils se contraignent — la cote juste d'un favori à p vaut `1 / p` — et l'interface le
dit plutôt que de rester vide sans motif. La règle avait été demandée à 80 % :

```text
cote juste d'un favori à 80 %  =  1 / 0,80  =  1,25
```

Les exiger ensemble revenait à demander qu'un livre paie un gros favori **à son prix juste ou
mieux**. Mesuré sur les 144 matchs collectés : les 7 favoris à 80 % et plus étaient offerts à
1,10 de cote nette médiane, pour un écart médian de −1,17 %. **Aucun** n'atteignait 1,25.

| seuil de probabilité | cote juste | candidats (cote nette ≥ 1,25 et écart > 0) | réussite mesurée |
|---|---|---|---|
| 85 % | 1,176 | **0** | 89,2 % (n = 1 085) |
| 80 % | 1,250 | **0** | 83,6 % (n = 2 174) |
| 75 % | 1,333 | 3 | 79,1 % (n = 3 173) |
| 70 % | 1,429 | 4 | 74,5 % (n = 5 028) |

Le seuil a donc été abaissé le jour même à **70 %**, la borne du niveau de confiance « Élevée »
que la page affiche déjà à côté de chaque pronostic. À ce niveau la cote juste vaut 1,43 : le
plancher de 1,25 n'écarte plus rien, c'est l'écart positif chez un livre réel qui fait le tri. Le
prix de ce point est dans la table : 74,5 % de réussite au lieu de 83,6 %. Les deux curseurs sont
dans les réglages avancés, et le titre du bloc affiche toujours les valeurs retenues, le niveau de
confiance qui leur correspond et le taux d'échec mesuré. Chaque carte
porte le verdict ordinaire du prix (soutenu, isolé, fragile) : la règle dit ce qui est sûr et
payant, le verdict dit ce que le prix vaut. Cadrage complet et ce qu'on refuse d'en conclure :
[`prereg/0006`](prereg/0006-sur-et-payant.md).

#### Valeur d'un pari

Le pronostic dit ce qui est probable ; il ne dit pas ce qui vaut d'être pris. Au prix juste,
miser sur le favori a une espérance nulle — le marché l'a déjà intégré. Ce qui départage deux
paris est leur **valeur** : l'espérance par euro misé, `p × cote − 1`, positive quand le prix
bat la cote juste `1 / p`. Un favori à 80 % coté 1,20 vaut −4 % ; un outsider à 24 % coté 4,40
vaut +5,6 %. Kelly n'en est qu'une mise à l'échelle par `cote − 1` : même signe, même seuil.

L'outil la met au premier plan, partout où l'on choisit :

- **Matchs du jour** : une colonne « Valeur » par match (issue, prix, livre), un tri par valeur,
  et un encadré « le pari à la plus forte valeur du jour » à côté du « pronostic le plus sûr » —
  les deux coïncident rarement, et c'est le premier qui justifie de prendre un pari plutôt qu'un
  autre ;
- **formulaire de pari** : la valeur de chaque issue au meilleur prix relevé figure dans le menu
  même, puis la valeur du prix saisi ouvre la rangée de chiffres, avec une phrase qui dit
  pourquoi ce pari — ou pourquoi il n'y a pas de valeur à ce prix ;
- **Mes paris** : la valeur annoncée de chaque pari au moment de le prendre, et au bilan
  l'espérance cumulée en face du profit réalisé. L'écart entre les deux est la variance des
  résultats, pas un jugement sur la sélection.

**Une cote d'exchange est comptée nette de commission.** Une bourse (Betfair, Matchbook,
Smarkets) ne prend presque rien dans le prix — d'où des cotes systématiquement plus hautes — et
se paie sur le gain : `cote nette = 1 + (cote − 1) × (1 − c)`. Comparée brute à un bookmaker,
elle gagne presque toujours, et pour rien. Mesuré sur les 144 matchs collectés, avant correction :
**14 des 21 « écarts soutenus » portaient sur Betfair Exchange**, alors qu'à 5 % de commission un
écart de +1,8 % à la cote 2,38 vaut −1,1 %. En net, il reste **10 écarts soutenus sur les mêmes
144 matchs**, aucun sur une bourse — et là où une bourse reste le prix le mieux payant, son écart
moyen est de −1,24 %.

L'outil affiche donc les deux prix — « à 6,00 chez Matchbook · 5,92 net » — et calcule sur le
second : espérance, Kelly, mise proposée, profit du carnet et CLV. La probabilité, elle, reste lue
sur la cote brute : la commission prélève sur le gain, elle n'apprend rien sur le match. Réglez
`COMMISSION_EXCHANGE` avec le taux de votre compte ; cadrage complet dans
[`decisions/0008`](decisions/0008-commission-des-exchanges.md).

Ce que cette valeur mesure, et rien de plus : `p` est le **consensus dévigé des autres
bookmakers**, recalculé sans le livre qui affiche le prix. Une valeur positive dit que ce prix
bat les autres opérateurs — pas qu'il bat la vérité, qu'aucun modèle de ce projet n'approche
mieux que le marché (R8, R9). Trois filtres séparent une valeur d'une cote périmée, et seuls les
trois réunis donnent le badge vert « écart soutenu » : écart d'au moins 1 %, au moins deux
livres à 1 % du meilleur prix et pas plus de 2 % au-dessus du deuxième, même signe sous les
quatre méthodes de dévig. Un écart isolé ou fragile est affiché, mais coloré comme du bruit, et
le formulaire le rappelle au moment de parier dessus.

#### Dispersion des prix (analyse secondaire)

En annexe, le détail de ces écarts : où le meilleur prix disponible s'écarte du consensus des
**autres** bookmakers — une observation sur le désaccord entre opérateurs, sans rapport avec la
probabilité qu'une issue se produise. Trois filtres : consensus recalculé sans le book généreux,
écart au deuxième meilleur prix, et robustesse aux quatre méthodes de dévig.

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

### Héberger l'application, sur invitation

Hors du poste, l'application tourne sur **Streamlit Community Cloud** (gratuit), ne s'ouvre
qu'avec un **lien personnel** envoyé à chaque invité, et chaque personne tient **son** carnet — le règlement d'un
match, lui, vaut pour tout le monde : un score est un fait. L'état (carnet, base de collecte,
parquets) vit dans un seau privé **Supabase Storage**, copié fichier entier à chaque écriture ;
la collecte horaire passe sur **GitHub Actions**. Le raisonnement, ce qu'on y perd et ce qui
ferait changer d'approche : [`decisions/0009`](decisions/0009-heberger-sur-invitation.md).

Sans rien configurer, rien ne change : `uv run odds app` reste local, sans porte d'entrée.

Mise en service, une fois :

1. **Un dépôt GitHub** (privé suffit) qui contient ce projet.
2. **Un projet Supabase**. Noter l'URL du projet et la clé **secrète** (`sb_secret_…`, dans
   *Project Settings → API Keys → Secret keys*) — pas la clé publiable, qui ne voit pas un seau
   privé. Elle ne doit jamais apparaître côté client ni dans le dépôt. Le seau privé `etat` est
   créé par l'étape 4 s'il n'existe pas.
3. **Une clé par invité**, vous compris :

   ```bash
   uv run odds inviter paul
   ```

   La commande imprime le lien à envoyer à Paul, et la ligne `paul = "…"` à coller dans la
   section `[invites]` des secrets. Un lien est une clé de maison : qui l'a entre au nom de Paul.
4. **Amorcer le seau** depuis le disque local, avec les deux variables Supabase dans `.env` :

   ```bash
   uv run odds etat pousser
   ```

5. **Déployer sur Community Cloud** : nouvelle application, dépôt ci-dessus, fichier principal
   `src/odds/app/dashboard.py`, Python 3.12. Dans *Settings → Secrets*, coller
   [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) rempli :
   `ODDS_PROPRIETAIRE`, `ODDS_URL`, les valeurs Supabase et la section `[invites]`.
6. **Brancher la collecte** : dans le dépôt GitHub, *Settings → Secrets and variables → Actions*,
   définir `ODDS_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`. Le workflow
   [`collecte.yml`](.github/workflows/collecte.yml) tourne chaque heure à h+7 ; désinstaller
   l'agent `launchd` local, sinon deux collecteurs écriraient le même fichier.

Ajouter un invité : `odds inviter <nom>`, coller la ligne dans les secrets, envoyer le lien.
Révoquer : retirer la ligne. Dans les deux cas l'application redémarre seule. Dépannage : `uv run odds etat tirer` ramène l'état du seau sur le
poste ; l'application locale et la version hébergée lisent alors le même carnet.

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
├── config.py                configuration locale (.env, secrets Streamlit), secrets masqués
├── stockage.py              copie distante de l'état dans un seau Supabase (decisions/0009)
├── market/devig.py          Shin, power, odds ratio, proportionnelle (scalaire + vectorisé)
├── market/commission.py     bourses d'échange : cote nette, taux par livre
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
├── paper.py                 carnet papier par utilisateur : staking prereg §4, couvertures, règlement, CLV
├── app/                     tableau de bord Streamlit (dashboard, buts_ui, paris_ui, couverture_ui, theme)
│   └── acces.py             connexion et liste d'invités de l'application hébergée
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
