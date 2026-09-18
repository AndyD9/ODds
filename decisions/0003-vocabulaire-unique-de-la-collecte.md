# 0003 — Un seul vocabulaire `(market, selection)` pour toutes les sources

**Statut :** acceptée · **Date :** 2026-09-18 · **Code :** `src/odds/market/vocabulaire.py`

## Contexte

Deux sources alimentent la base de collecte. The Odds API nomme un total `totals` / `over_2.5` ;
football-data ne publie que la ligne 2,5 et l'écrivait `OU25` / `over`. Le 1X2, lui, est
`home/draw/away` en base, `1/N/2` dans le carnet, `H/D/A` dans les résultats football-data.

La traduction entre codes de pari et lignes collectées était écrite deux fois — dans le noyau
d'analyse pour le consensus, dans le carnet pour la clôture — et chaque lecteur devait connaître
les deux graphies des totaux. Un troisième marché en aurait ajouté une.

## Décision

La base de collecte range **toute** cote sous le vocabulaire de The Odds API : `1X2` /
`home|draw|away`, `totals` / `over_2.5|under_2.5|…`. Football-data est traduit à l'ingestion,
et les bases existantes sont converties à la connexion (`collect._migrer`).

Un seul module, `odds.market.vocabulaire`, traduit dans les deux sens entre un code de pari du
catalogue (`total_over_2.5`) et le couple collecté (`totals`, `over_2.5`). Le carnet et le
consensus l'appellent tous deux.

## Options écartées

- **Ranger la collecte sous les codes du catalogue** (`total_over_2.5` directement). Un seul
  vocabulaire au lieu de deux. Écarté : le catalogue est un objet du modèle, la collecte est une
  couche de données qui doit pouvoir tourner sans lui, et le 1X2 se lit mieux en `home/draw/away`
  qu'en `1/N/2` quand on pivote une table.
- **Garder deux graphies et normaliser à la lecture.** C'était l'état antérieur. Écarté : la
  normalisation se répète dans chaque lecteur et diverge.

## Conséquences

- Le vocabulaire retenu porte la ligne dans la sélection : `over_2.5` et `over_3.5` sont deux
  marchés distincts sans changer de nom de marché.
- `paper.selections_collectees` renvoie désormais un seul couple par marché.
- Les résultats football-data (`H/D/A`) restent tels quels : ils ne sont pas des cotes et ne
  passent pas par la collecte.
